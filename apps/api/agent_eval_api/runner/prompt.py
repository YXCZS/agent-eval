"""OpenAI-compatible Prompt Agent runner."""

from __future__ import annotations

import asyncio
import copy
import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from agent_eval_api.contracts import PromptConfig

_PLACEHOLDER = re.compile(r"\{\{?([A-Za-z_][A-Za-z0-9_]*)\}?\}")


class PromptRunnerError(RuntimeError):
    """Raised when an OpenAI-compatible response cannot be used."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str = "prompt_error",
        attempts: int = 1,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.attempts = attempts


@dataclass(frozen=True)
class PromptUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float | None = None


@dataclass(frozen=True)
class PromptRunResult:
    output: Any
    rendered_prompt: str
    variables_snapshot: dict[str, Any]
    messages: list[dict[str, Any]]
    usage: PromptUsage
    raw_response: dict[str, Any]
    structured_output_error: str | None = None
    attempts: int = 1


def render_template(template: str, variables: dict[str, Any]) -> str:
    """Render named placeholders while leaving ordinary JSON braces untouched."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            raise PromptRunnerError(f"missing prompt variable: {name}")
        value = variables[name]
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

    return _PLACEHOLDER.sub(replace, template)


def _parse_usage(body: dict[str, Any], config: PromptConfig) -> PromptUsage:
    raw_usage: Any = body.get("usage")
    usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
    input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
    output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
    total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens) or 0)
    raw_cost = usage.get("cost")
    cost = float(raw_cost) if raw_cost is not None else None
    if (
        cost is None
        and config.input_cost_per_1k is not None
        and config.output_cost_per_1k is not None
    ):
        cost = (input_tokens / 1000 * config.input_cost_per_1k) + (
            output_tokens / 1000 * config.output_cost_per_1k
        )
    return PromptUsage(input_tokens, output_tokens, total_tokens, cost)


def _extract_content(body: dict[str, Any]) -> Any:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise PromptRunnerError("response is missing choices[0]")
    message = choices[0].get("message")
    if not isinstance(message, dict) or "content" not in message:
        raise PromptRunnerError("response is missing choices[0].message.content")
    return message["content"]


async def run_prompt(
    config: PromptConfig,
    variables: dict[str, Any],
    *,
    input_messages: list[dict[str, Any]] | None = None,
    client: httpx.AsyncClient | None = None,
) -> PromptRunResult:
    """Render and invoke a prompt without leaking the caller's mutable variables."""

    variables_snapshot = copy.deepcopy(variables)
    rendered_prompt = render_template(config.user_template, variables_snapshot)
    messages: list[dict[str, Any]] = []
    if config.system_prompt:
        messages.append({"role": "system", "content": config.system_prompt})
    if input_messages:
        messages.extend(copy.deepcopy(input_messages))
    else:
        messages.append({"role": "user", "content": rendered_prompt})

    request_body: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "top_p": config.top_p,
    }
    if config.max_tokens is not None:
        request_body["max_tokens"] = config.max_tokens
    if config.response_format is not None:
        request_body["response_format"] = config.response_format

    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=config.timeout_seconds)
    try:
        attempt = 0
        while True:
            try:
                response = await http_client.post(str(config.endpoint), json=request_body)
                if response.status_code == 429:
                    raise PromptRunnerError(
                        "LLM provider rate limited the request",
                        error_type="rate_limit",
                    )
                if response.status_code >= 500:
                    raise PromptRunnerError(
                        f"LLM provider returned HTTP {response.status_code}",
                        error_type="service_error",
                    )
                response.raise_for_status()
                body = response.json()
                break
            except PromptRunnerError as exc:
                if attempt >= config.max_retries:
                    raise PromptRunnerError(
                        str(exc), error_type=exc.error_type, attempts=attempt + 1
                    ) from exc
            except httpx.TimeoutException as exc:
                if attempt >= config.max_retries:
                    raise PromptRunnerError(
                        "LLM request timed out",
                        error_type="timeout",
                        attempts=attempt + 1,
                    ) from exc
            except httpx.HTTPStatusError as exc:
                raise PromptRunnerError(
                    f"LLM request failed: HTTP {exc.response.status_code}",
                    error_type="provider_error",
                    attempts=attempt + 1,
                ) from exc
            except httpx.HTTPError as exc:
                if attempt >= config.max_retries:
                    raise PromptRunnerError(
                        "LLM request could not be completed",
                        error_type="connection_error",
                        attempts=attempt + 1,
                    ) from exc
            except ValueError as exc:
                raise PromptRunnerError(
                    "LLM response is not valid JSON",
                    error_type="protocol_error",
                    attempts=attempt + 1,
                ) from exc

            await asyncio.sleep(config.retry_backoff_seconds * (2**attempt))
            attempt += 1
    finally:
        if owns_client:
            await http_client.aclose()

    if not isinstance(body, dict):
        raise PromptRunnerError("LLM response must be a JSON object")
    content = _extract_content(body)
    structured_output_error = None
    output = content
    if config.response_format is not None:
        if not isinstance(content, str):
            output = content
        else:
            try:
                output = json.loads(content)
            except json.JSONDecodeError:
                structured_output_error = "invalid_json"

    return PromptRunResult(
        output=output,
        rendered_prompt=rendered_prompt,
        variables_snapshot=variables_snapshot,
        messages=messages,
        usage=_parse_usage(body, config),
        raw_response=body,
        structured_output_error=structured_output_error,
        attempts=attempt + 1,
    )
