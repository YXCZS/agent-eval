from datetime import UTC, datetime, timedelta

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
    EmbeddingProviderConfig,
    EvaluationContext,
    evaluate_prompt_deterministic,
)


def context(
    name: str,
    *,
    expected_output: object = "Hello world",
    output: object = "Hello world",
    usage: dict[str, object] | None = None,
    threshold: float = 1.0,
    direction: ScoreDirection = ScoreDirection.HIGHER_IS_BETTER,
    config: dict[str, object] | None = None,
) -> EvaluationContext:
    started_at = datetime.now(UTC)
    return EvaluationContext(
        case=DatasetCase(
            id="case-1",
            input="say hello",
            expected_output=expected_output,
            output_schema={"type": "object"},
        ),
        execution=CaseExecution(
            id="execution-1",
            run_id="run-1",
            case_id="case-1",
            status=ExecutionStatus.COMPLETED,
            output=output,
            usage=usage or {},
            started_at=started_at,
            finished_at=started_at + timedelta(milliseconds=50),
        ),
        evaluator=EvaluatorVersion(
            id=f"evaluator-{name}",
            name=name,
            version="1.0.0",
            evaluator_type=EvaluatorType.DETERMINISTIC,
            supported_agent_types=[AgentType.PROMPT],
            score_min=0,
            score_max=10_000,
            direction=direction,
            default_threshold=threshold,
            config=config or {},
        ),
    )


@pytest.mark.asyncio
async def test_prompt_exact_match_supports_explicit_normalization() -> None:
    outcome = (
        await evaluate_prompt_deterministic(
            context(
                "exact_match",
                expected_output="Hello world",
                output=" hello   WORLD ",
                config={"normalize_whitespace": True, "case_sensitive": False},
            )
        )
    )[0]

    assert outcome.status is ScoreStatus.PASSED
    assert outcome.value == 1


@pytest.mark.asyncio
async def test_prompt_token_metric_uses_total_or_sums_input_and_output() -> None:
    outcome = (
        await evaluate_prompt_deterministic(
            context(
                "token_usage",
                usage={"input_tokens": 30, "output_tokens": 12},
                threshold=50,
                direction=ScoreDirection.LOWER_IS_BETTER,
            )
        )
    )[0]

    assert outcome.status is ScoreStatus.PASSED
    assert outcome.value == 42
    assert outcome.evidence[0]["token_field"] == "total_tokens"


@pytest.mark.asyncio
async def test_prompt_json_schema_latency_and_cost_reuse_deterministic_contract() -> None:
    schema = (
        await evaluate_prompt_deterministic(
            context("json_schema", output={"answer": "ok"})
        )
    )[0]
    latency = (
        await evaluate_prompt_deterministic(
            context(
                "latency",
                threshold=100,
                direction=ScoreDirection.LOWER_IS_BETTER,
            )
        )
    )[0]
    cost = (
        await evaluate_prompt_deterministic(
            context(
                "cost",
                usage={"cost": 0.002},
                threshold=0.01,
                direction=ScoreDirection.LOWER_IS_BETTER,
            )
        )
    )[0]

    assert schema.status is ScoreStatus.PASSED
    assert latency.status is ScoreStatus.PASSED
    assert latency.value == pytest.approx(50)
    assert cost.status is ScoreStatus.PASSED


@pytest.mark.asyncio
async def test_semantic_similarity_uses_embedding_cosine_and_hides_key() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret-key"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.8, 0.2]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            },
        )

    provider = EmbeddingProviderConfig(
        endpoint="https://embedding.example.test/v1/embeddings",
        model="embed-model",
        api_key="secret-key",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = (
            await evaluate_prompt_deterministic(
                context("semantic_similarity", threshold=0.9),
                embedding_provider=provider,
                client=client,
            )
        )[0]

    assert outcome.status is ScoreStatus.PASSED
    assert outcome.value == pytest.approx(0.9701425)
    assert outcome.raw_result == {
        "provider": "openai-compatible",
        "model": "embed-model",
        "attempts": 1,
        "dimensions": 2,
    }


@pytest.mark.asyncio
async def test_semantic_similarity_missing_reference_does_not_call_provider() -> None:
    called = False

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    provider = EmbeddingProviderConfig(
        endpoint="https://embedding.example.test/v1/embeddings",
        model="embed-model",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        outcome = (
            await evaluate_prompt_deterministic(
                context("semantic_similarity", expected_output=None),
                embedding_provider=provider,
                client=client,
            )
        )[0]

    assert outcome.status is ScoreStatus.MISSING
    assert outcome.passed is None
    assert called is False
