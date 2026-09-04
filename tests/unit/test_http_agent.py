import asyncio
import json

import httpx
import pytest

from agent_eval_api.contracts import EndpointConfig
from agent_eval_api.runner import AgentAdapterError, AgentConcurrencyLimiter, run_http_agent


def endpoint(**overrides: object) -> EndpointConfig:
    values: dict[str, object] = {"url": "https://agent.example.test/run"}
    values.update(overrides)
    return EndpointConfig(**values)


@pytest.mark.asyncio
async def test_http_adapter_sends_protocol_metadata_and_normalizes_tool_calls() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Project-Key"] == "project-key"
        body = json.loads(request.content)
        assert body["input"] == {"question": "Where is 42?"}
        assert body["metadata"] == {"run_id": "run-1", "case_id": "case-1"}
        assert body["trace_id"] == "trace-1"
        return httpx.Response(
            200,
            json={
                "output": {"answer": "shipped"},
                "tool_calls": [{"name": "search_order", "arguments": {"order_id": "42"}}],
                "usage": {"input_tokens": 12, "output_tokens": 8},
                "trace": {"spans": []},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await run_http_agent(
            endpoint(),
            {"question": "Where is 42?"},
            variables={"locale": "en-US"},
            run_id="run-1",
            case_id="case-1",
            trace_id="trace-1",
            project_api_key="project-key",
            client=client,
        )

    assert result.output == {"answer": "shipped"}
    assert result.tool_calls[0].name == "search_order"
    assert result.usage["output_tokens"] == 8
    assert result.raw_response["trace"] == {"spans": []}


@pytest.mark.asyncio
async def test_http_adapter_rejects_invalid_protocol_without_partial_result() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"tool_calls": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AgentAdapterError, match="missing output"):
            await run_http_agent(
                endpoint(),
                "hello",
                run_id="run-1",
                case_id="case-1",
                trace_id="trace-1",
                client=client,
            )


@pytest.mark.asyncio
async def test_http_adapter_enforces_response_size_limit() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"output":"123456"}')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AgentAdapterError, match="exceeds configured limit"):
            await run_http_agent(
                endpoint(max_response_bytes=10),
                "hello",
                run_id="run-1",
                case_id="case-1",
                trace_id="trace-1",
                client=client,
            )


@pytest.mark.asyncio
async def test_http_adapter_retries_rate_limits_and_reports_attempts() -> None:
    attempts = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(429, json={"error": "busy"})
        return httpx.Response(200, json={"output": "ok"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await run_http_agent(
            endpoint(max_retries=2, retry_backoff_seconds=0),
            "hello",
            run_id="run-1",
            case_id="case-1",
            trace_id="trace-1",
            client=client,
        )

    assert attempts == 3
    assert result.output == "ok"


@pytest.mark.asyncio
async def test_http_adapter_does_not_retry_authentication_errors() -> None:
    attempts = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, json={"error": "unauthorized"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AgentAdapterError) as raised:
            await run_http_agent(
                endpoint(max_retries=5, retry_backoff_seconds=0),
                "hello",
                run_id="run-1",
                case_id="case-1",
                trace_id="trace-1",
                client=client,
            )

    assert raised.value.error_type == "authentication_error"
    assert raised.value.attempts == 1
    assert attempts == 1


@pytest.mark.asyncio
async def test_http_adapter_enforces_max_tool_calls() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "output": "ok",
                "tool_calls": [
                    {"name": "one"},
                    {"name": "two"},
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AgentAdapterError, match="tool call limit") as raised:
            await run_http_agent(
                endpoint(max_tool_calls=1),
                "hello",
                run_id="run-1",
                case_id="case-1",
                trace_id="trace-1",
                client=client,
            )

    assert raised.value.error_type == "tool_limit"


@pytest.mark.asyncio
async def test_http_adapter_limits_concurrent_agent_calls() -> None:
    active = 0
    peak = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(200, json={"output": "ok"})

    limiter = AgentConcurrencyLimiter(1)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await asyncio.gather(
            run_http_agent(
                endpoint(),
                "one",
                run_id="run-1",
                case_id="case-1",
                trace_id="trace-1",
                concurrency_limiter=limiter,
                client=client,
            ),
            run_http_agent(
                endpoint(),
                "two",
                run_id="run-1",
                case_id="case-2",
                trace_id="trace-2",
                concurrency_limiter=limiter,
                client=client,
            ),
        )

    assert peak == 1
