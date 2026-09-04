import json

import httpx
import pytest

from agent_eval_api.contracts import PromptConfig
from agent_eval_api.runner import PromptRunnerError, run_prompt


def config(**overrides: object) -> PromptConfig:
    values: dict[str, object] = {
        "provider": "mock",
        "model": "mock-model",
        "endpoint": "https://llm.example.test/v1/chat/completions",
        "system_prompt": "Be concise.",
        "user_template": "Answer {question} for {{locale}}.",
        "variable_names": ["question", "locale"],
        "response_format": {"type": "json_object"},
        "input_cost_per_1k": 0.1,
        "output_cost_per_1k": 0.2,
    }
    values.update(overrides)
    return PromptConfig(**values)


@pytest.mark.asyncio
async def test_prompt_runner_renders_snapshot_structured_output_and_cost() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["messages"][-1]["content"] == "Answer shipped for en-US."
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"answer":"shipped"}'}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            },
        )

    variables = {"question": "shipped", "locale": "en-US"}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await run_prompt(config(), variables, client=client)

    variables["question"] = "mutated after call"
    assert result.output == {"answer": "shipped"}
    assert result.variables_snapshot["question"] == "shipped"
    assert result.usage.total_tokens == 120
    assert result.usage.cost == pytest.approx(0.014)
    assert result.raw_response["choices"]


@pytest.mark.asyncio
async def test_prompt_runner_preserves_invalid_structured_output_for_evaluator() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not-json"}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await run_prompt(config(), {"question": "x", "locale": "en"}, client=client)

    assert result.output == "not-json"
    assert result.structured_output_error == "invalid_json"


@pytest.mark.asyncio
async def test_prompt_runner_rejects_missing_template_variable() -> None:
    with pytest.raises(PromptRunnerError, match="missing prompt variable"):
        await run_prompt(config(), {"question": "x"})


@pytest.mark.asyncio
async def test_prompt_runner_retries_transient_errors_with_exponential_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    delays: list[float] = []

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json={"choices": [{"message": {"content": '"ok"'}}]})

    async def record_delay(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("agent_eval_api.runner.prompt.asyncio.sleep", record_delay)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await run_prompt(
            config(max_retries=2, retry_backoff_seconds=0.25),
            {"question": "x", "locale": "en"},
            client=client,
        )

    assert attempts == 3
    assert delays == [0.25, 0.5]
    assert result.attempts == 3


@pytest.mark.asyncio
async def test_prompt_runner_does_not_retry_non_transient_provider_errors() -> None:
    attempts = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, json={"error": "unauthorized"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PromptRunnerError) as raised:
            await run_prompt(
                config(max_retries=5, retry_backoff_seconds=0),
                {"question": "x", "locale": "en"},
                client=client,
            )

    assert raised.value.error_type == "provider_error"
    assert raised.value.attempts == 1
    assert attempts == 1
