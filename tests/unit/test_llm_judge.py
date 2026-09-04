import json

import httpx
import pytest

from agent_eval_api.contracts import (
    AgentType,
    CaseExecution,
    DatasetCase,
    EvaluatorType,
    EvaluatorVersion,
    ExecutionStatus,
    ScoreDirection,
    ScoreStatus,
)
from agent_eval_api.evaluation import (
    EvaluationContext,
    JudgeProviderConfig,
    JudgeProviderError,
    evaluate_llm_judge,
)


def context(
    name: str = "answer_quality",
    *,
    criteria: list[str] | None = None,
    rubric: str | None = None,
) -> EvaluationContext:
    return EvaluationContext(
        case=DatasetCase(
            id="case-1",
            input="Where is order 42?",
            expected_output="It has shipped.",
            criteria=criteria or [],
        ),
        execution=CaseExecution(
            id="execution-1",
            run_id="run-1",
            case_id="case-1",
            status=ExecutionStatus.COMPLETED,
            output="Order 42 has shipped.",
        ),
        evaluator=EvaluatorVersion(
            id="judge-1",
            name=name,
            version="1.0.0",
            evaluator_type=EvaluatorType.LLM_JUDGE,
            supported_agent_types=[AgentType.PROMPT, AgentType.RAG, AgentType.TOOL],
            score_min=0,
            score_max=1,
            direction=ScoreDirection.HIGHER_IS_BETTER,
            default_threshold=0.8,
            rubric=rubric,
            judge_model="judge-model",
        ),
    )


def provider(**overrides: object) -> JudgeProviderConfig:
    values: dict[str, object] = {
        "endpoint": "https://judge.example.test/v1/chat/completions",
        "model": "judge-model",
        "api_key": "secret-key",
        "retry_backoff_seconds": 0,
    }
    values.update(overrides)
    return JudgeProviderConfig(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_llm_judge_sends_rubric_and_returns_thresholded_structured_outcome() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret-key"
        body = json.loads(request.content)
        judge_input = json.loads(body["messages"][1]["content"])
        assert judge_input["actual_output"] == "Order 42 has shipped."
        assert "unsupported claims" in judge_input["rubric"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "score": 0.9,
                                    "explanation": "Correct and supported.",
                                    "evidence": ["Matches the reference status."],
                                    "label": "good",
                                }
                            )
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = (await evaluate_llm_judge(context(), provider(), client=client))[0]

    assert outcome.status is ScoreStatus.PASSED
    assert outcome.value == 0.9
    assert outcome.passed is True
    assert outcome.evidence == [{"statement": "Matches the reference status."}]
    assert "secret-key" not in json.dumps(outcome.raw_result)
    assert outcome.raw_result["model"] == "judge-model"


@pytest.mark.asyncio
async def test_llm_judge_retries_transient_provider_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    delays: list[float] = []

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"score":0.7,"explanation":"partial","evidence":[]}'
                        }
                    }
                ]
            },
        )

    async def record_delay(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("agent_eval_api.evaluation.judge.asyncio.sleep", record_delay)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = (
            await evaluate_llm_judge(
                context(),
                provider(max_retries=2, retry_backoff_seconds=0.25),
                client=client,
            )
        )[0]

    assert attempts == 3
    assert delays == [0.25, 0.5]
    assert outcome.status is ScoreStatus.FAILED
    assert outcome.raw_result["attempts"] == 3


@pytest.mark.asyncio
async def test_llm_judge_rejects_invalid_structured_decision_without_retry() -> None:
    attempts = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not-json"}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(JudgeProviderError) as raised:
            await evaluate_llm_judge(context(), provider(max_retries=5), client=client)

    assert raised.value.error_type == "protocol_error"
    assert raised.value.attempts == 1
    assert attempts == 1


@pytest.mark.asyncio
async def test_rule_judge_returns_missing_without_criteria_or_rubric() -> None:
    called = False

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = (
            await evaluate_llm_judge(
                context("natural_language_rules"),
                provider(),
                client=client,
            )
        )[0]

    assert outcome.status is ScoreStatus.MISSING
    assert outcome.passed is None
    assert called is False
