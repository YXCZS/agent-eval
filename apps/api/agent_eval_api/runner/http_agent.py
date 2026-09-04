"""HTTP adapter for already-running user Agents."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx

from agent_eval_api.contracts import EndpointConfig, ExpectedToolCall


class AgentAdapterError(RuntimeError):
    """A protocol or transport error that can be isolated to one case."""

    def __init__(self, error_type: str, message: str, *, attempts: int = 1) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.attempts = attempts


RETRYABLE_ERRORS = {"connection_error", "timeout", "rate_limit", "service_error"}


class AgentConcurrencyLimiter:
    """Bound concurrent calls for one registered Agent."""

    def __init__(self, limit: int) -> None:
        self._semaphore = asyncio.Semaphore(limit)

    async def __aenter__(self) -> None:
        await self._semaphore.acquire()

    async def __aexit__(self, *_: Any) -> None:
        self._semaphore.release()


@asynccontextmanager
async def _request_slot(
    limiter: AgentConcurrencyLimiter | None,
) -> AsyncIterator[None]:
    if limiter is None:
        yield
    else:
        async with limiter:
            yield


@dataclass(frozen=True)
class HttpAgentRunResult:
    output: Any
    tool_calls: list[ExpectedToolCall]
    usage: dict[str, Any]
    trace: dict[str, Any] | None
    raw_response: dict[str, Any]
    request_metadata: dict[str, str]
    attempts: int = 1


def _parse_tool_calls(raw_tool_calls: Any) -> list[ExpectedToolCall]:
    if raw_tool_calls is None:
        return []
    if not isinstance(raw_tool_calls, list):
        raise AgentAdapterError("protocol_error", "tool_calls must be an array")
    parsed: list[ExpectedToolCall] = []
    for index, raw_call in enumerate(raw_tool_calls):
        if not isinstance(raw_call, dict):
            raise AgentAdapterError("protocol_error", f"tool_calls[{index}] must be an object")
        try:
            parsed.append(ExpectedToolCall.model_validate(raw_call))
        except ValueError as exc:
            raise AgentAdapterError("protocol_error", f"invalid tool_calls[{index}]") from exc
    return parsed


async def run_http_agent(
    config: EndpointConfig,
    input_value: Any,
    *,
    variables: dict[str, Any] | None = None,
    messages: list[dict[str, Any]] | None = None,
    run_id: str,
    case_id: str,
    trace_id: str,
    project_api_key: str | None = None,
    concurrency_limiter: AgentConcurrencyLimiter | None = None,
    client: httpx.AsyncClient | None = None,
) -> HttpAgentRunResult:
    """Invoke the stable /run protocol and normalize its response."""

    request_metadata = {"run_id": run_id, "case_id": case_id}
    request_body: dict[str, Any] = {
        "input": copy.deepcopy(input_value),
        "variables": copy.deepcopy(variables or {}),
        "metadata": request_metadata,
        "trace_id": trace_id,
    }
    if messages is not None:
        request_body["messages"] = copy.deepcopy(messages)
    headers = {"Content-Type": "application/json"}
    if project_api_key:
        headers["X-Project-Key"] = project_api_key

    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=config.timeout_seconds)
    try:
        attempt = 0
        while True:
            try:
                async with _request_slot(concurrency_limiter):
                    response = await http_client.request(
                        config.method,
                        str(config.url),
                        headers=headers,
                        json=request_body,
                    )
                if len(response.content) > config.max_response_bytes:
                    raise AgentAdapterError(
                        "response_too_large", "agent response exceeds configured limit"
                    )
                if response.status_code in {401, 403}:
                    raise AgentAdapterError(
                        "authentication_error", f"agent returned HTTP {response.status_code}"
                    )
                if response.status_code == 429:
                    raise AgentAdapterError("rate_limit", "agent returned HTTP 429")
                if response.status_code >= 500:
                    raise AgentAdapterError(
                        "service_error", f"agent returned HTTP {response.status_code}"
                    )
                response.raise_for_status()
                body = response.json()
                break
            except AgentAdapterError as exc:
                if exc.error_type not in RETRYABLE_ERRORS or attempt >= config.max_retries:
                    raise AgentAdapterError(exc.error_type, str(exc), attempts=attempt + 1) from exc
                await asyncio.sleep(config.retry_backoff_seconds * (2**attempt))
                attempt += 1
            except httpx.TimeoutException as exc:
                error = AgentAdapterError("timeout", "agent request timed out")
                if attempt >= config.max_retries:
                    raise AgentAdapterError("timeout", str(error), attempts=attempt + 1) from exc
                await asyncio.sleep(config.retry_backoff_seconds * (2**attempt))
                attempt += 1
            except httpx.HTTPError as exc:
                error = AgentAdapterError(
                    "connection_error", "agent request could not be completed"
                )
                if attempt >= config.max_retries:
                    raise AgentAdapterError(
                        "connection_error", str(error), attempts=attempt + 1
                    ) from exc
                await asyncio.sleep(config.retry_backoff_seconds * (2**attempt))
                attempt += 1
            except ValueError as exc:
                raise AgentAdapterError(
                    "protocol_error", "agent response is not valid JSON", attempts=attempt + 1
                ) from exc
    finally:
        if owns_client:
            await http_client.aclose()

    if not isinstance(body, dict):
        raise AgentAdapterError("protocol_error", "agent response must be a JSON object")
    if "output" not in body:
        raise AgentAdapterError("protocol_error", "agent response is missing output")
    raw_usage = body.get("usage", {})
    if not isinstance(raw_usage, dict):
        raise AgentAdapterError("protocol_error", "usage must be an object")
    raw_trace = body.get("trace")
    if raw_trace is not None and not isinstance(raw_trace, dict):
        raise AgentAdapterError("protocol_error", "trace must be an object")

    tool_calls = _parse_tool_calls(body.get("tool_calls"))
    if len(tool_calls) > config.max_tool_calls:
        raise AgentAdapterError("tool_limit", "agent response exceeds configured tool call limit")

    return HttpAgentRunResult(
        output=body["output"],
        tool_calls=tool_calls,
        usage=raw_usage,
        trace=raw_trace,
        raw_response=body,
        request_metadata=request_metadata,
        attempts=attempt + 1,
    )
