from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent_eval_api.contracts import (
    AgentType,
    AgentVersion,
    DatasetCase,
    DatasetVersion,
    EndpointConfig,
    EvaluationRun,
    EvaluatorType,
    EvaluatorVersion,
    PromptConfig,
    Score,
    ScoreDirection,
    ScoreStatus,
    Trace,
    TraceSpan,
    TraceSpanKind,
)

NOW = datetime.now(UTC)


def prompt_config() -> PromptConfig:
    return PromptConfig(
        provider="mock",
        model="mock-model",
        endpoint="https://llm.example.test/v1/chat/completions",
        user_template="Answer: {question}",
        variable_names=["question"],
    )


def endpoint_config() -> EndpointConfig:
    return EndpointConfig(url="https://agent.example.test/run", auth_ref="project-agent-key")


@pytest.mark.parametrize("agent_type", list(AgentType))
def test_all_agent_types_are_stable(agent_type: AgentType) -> None:
    config = prompt_config() if agent_type is AgentType.PROMPT else endpoint_config()
    version = AgentVersion(
        id=f"agent-version-{agent_type}",
        agent_id="agent-1",
        version=1,
        label="v1",
        agent_type=agent_type,
        prompt_config=config if agent_type is AgentType.PROMPT else None,
        endpoint_config=config if agent_type is not AgentType.PROMPT else None,
        created_at=NOW,
    )

    assert version.agent_type is agent_type


def test_agent_version_rejects_mismatched_execution_config() -> None:
    with pytest.raises(ValidationError, match="prompt agents require prompt_config only"):
        AgentVersion(
            id="agent-version-1",
            agent_id="agent-1",
            version=1,
            label="v1",
            agent_type="prompt",
            endpoint_config=endpoint_config(),
            created_at=NOW,
        )


def test_dataset_case_keeps_structured_agent_expectations() -> None:
    case = DatasetCase(
        id="case-1",
        input={"question": "Where is order 42?"},
        variables={"locale": "en-US"},
        expected_output={"status": "shipped"},
        output_schema={"type": "object"},
        expected_tools=[{"name": "search_order", "arguments": {"order_id": "42"}}],
        expected_state={"order_status": "shipped"},
        retrieval_context=[{"content": "Order 42 shipped", "document_id": "doc-1"}],
        messages=[{"role": "user", "content": "Where is order 42?"}],
        metadata={"category": "order"},
    )

    assert case.expected_tools[0].arguments["order_id"] == "42"
    assert case.retrieval_context[0].document_id == "doc-1"


def test_dataset_version_rejects_duplicate_case_ids() -> None:
    case = DatasetCase(id="case-1", input="hello")

    with pytest.raises(ValidationError, match="case ids must be unique"):
        DatasetVersion(
            id="dataset-version-1",
            dataset_id="dataset-1",
            version=1,
            cases=[case, case],
            created_at=NOW,
        )


def test_invalid_enum_and_missing_required_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        DatasetCase(id="case-1")
    with pytest.raises(ValidationError):
        AgentVersion(
            id="agent-version-1",
            agent_id="agent-1",
            version=1,
            label="v1",
            agent_type="browser",
            created_at=NOW,
        )


def test_run_rejects_inconsistent_case_counts() -> None:
    with pytest.raises(ValidationError, match="cannot exceed total_cases"):
        EvaluationRun(
            id="run-1",
            agent_version_id="agent-version-1",
            dataset_version_id="dataset-version-1",
            evaluator_version_ids=["eval-1"],
            total_cases=1,
            completed_cases=1,
            failed_cases=1,
            created_at=NOW,
        )


def test_evaluator_version_rejects_invalid_range() -> None:
    with pytest.raises(ValidationError, match="score_min must be lower"):
        EvaluatorVersion(
            id="eval-1",
            name="Task Success",
            version="1.0.0",
            evaluator_type=EvaluatorType.DETERMINISTIC,
            supported_agent_types=[AgentType.TOOL],
            score_min=1,
            score_max=0,
            direction=ScoreDirection.HIGHER_IS_BETTER,
        )


def test_score_never_defaults_failed_result_to_passed() -> None:
    score = Score(
        id="score-1",
        run_id="run-1",
        case_id="case-1",
        metric_name="task_success",
        evaluator_version_id="eval-1",
        status=ScoreStatus.MISSING,
        direction=ScoreDirection.HIGHER_IS_BETTER,
    )

    assert score.passed is None


def test_trace_requires_matching_span_trace_ids_and_preserves_extensions() -> None:
    trace = Trace(
        trace_id="trace-1",
        status="completed",
        extensions={"vendor.extra": {"attempt": 1}},
        spans=[
            TraceSpan(
                span_id="span-1",
                trace_id="trace-1",
                kind=TraceSpanKind.LLM,
                name="chat.completions",
                status="completed",
                started_at=NOW,
                extensions={"gen_ai.request.temperature": 0.2},
            )
        ],
    )

    assert trace.extensions["vendor.extra"]["attempt"] == 1

    with pytest.raises(ValidationError, match="containing trace"):
        Trace(
            trace_id="trace-1",
            status="completed",
            spans=[
                TraceSpan(
                    span_id="span-1",
                    trace_id="trace-2",
                    kind=TraceSpanKind.AGENT,
                    name="agent",
                    status="completed",
                    started_at=NOW,
                )
            ],
        )


def test_trace_rejects_missing_or_cyclic_span_parents() -> None:
    with pytest.raises(ValidationError, match="parent must exist"):
        Trace(
            trace_id="trace-1",
            status="completed",
            spans=[
                TraceSpan(
                    span_id="span-1",
                    trace_id="trace-1",
                    parent_span_id="missing",
                    kind=TraceSpanKind.AGENT,
                    name="agent",
                    status="completed",
                    started_at=NOW,
                )
            ],
        )

    with pytest.raises(ValidationError, match="parent cycles"):
        Trace(
            trace_id="trace-1",
            status="completed",
            spans=[
                TraceSpan(
                    span_id="span-1",
                    trace_id="trace-1",
                    parent_span_id="span-2",
                    kind=TraceSpanKind.AGENT,
                    name="agent",
                    status="completed",
                    started_at=NOW,
                ),
                TraceSpan(
                    span_id="span-2",
                    trace_id="trace-1",
                    parent_span_id="span-1",
                    kind=TraceSpanKind.LLM,
                    name="llm",
                    status="completed",
                    started_at=NOW,
                ),
            ],
        )
