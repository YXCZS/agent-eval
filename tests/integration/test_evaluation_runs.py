from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from agent_eval_api import auth
from agent_eval_api.auth import get_db, issue_dev_session
from agent_eval_api.contracts import ExpectedToolCall, RunStatus, ScoreStatus
from agent_eval_api.db import (
    AggregateMetricRecord,
    Base,
    CaseExecutionRecord,
    EvaluationRunRecord,
    ProjectRecord,
    ScoreRecord,
    TraceRecord,
)
from agent_eval_api.evaluation import EvaluatorOutcome
from agent_eval_api.main import create_app
from agent_eval_api.runner import (
    AgentAdapterError,
    HttpAgentRunResult,
    PromptRunResult,
    PromptUsage,
)
from agent_eval_api.settings import Settings
from agent_eval_worker.execution import execute_case


@pytest.fixture
def run_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Settings, Session]]:
    settings = Settings(
        database_url="sqlite:///:memory:",
        api_key_salt="test-salt",
        workspace_session_secret="test-session",
    )
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add_all(
        [ProjectRecord(id="project-1", name="one"), ProjectRecord(id="project-2", name="two")]
    )
    session.commit()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[auth.get_settings] = lambda: settings
    monkeypatch.setattr(
        "agent_eval_api.evaluation_runs.enqueue_case_jobs",
        lambda run_id, case_ids: None,
    )
    with TestClient(app) as client:
        yield client, settings, session
    session.close()


def headers(settings: Settings, project_id: str = "project-1") -> dict[str, str]:
    return {"X-Workspace-Session": issue_dev_session(project_id, settings)}


def create_tool_agent(
    client: TestClient,
    settings: Settings,
    project_id: str = "project-1",
    *,
    endpoint_overrides: dict[str, object] | None = None,
) -> str:
    endpoint_config: dict[str, object] = {"url": "https://agent.example.test/run"}
    endpoint_config.update(endpoint_overrides or {})
    response = client.post(
        f"/projects/{project_id}/agents",
        json={
            "name": "Order agent",
            "agent_type": "tool",
            "endpoint_config": endpoint_config,
        },
        headers=headers(settings, project_id),
    )
    assert response.status_code == 201
    return response.json()["current_version_id"]


def create_prompt_agent(client: TestClient, settings: Settings) -> str:
    response = client.post(
        "/projects/project-1/agents",
        json={
            "name": "Support prompt",
            "agent_type": "prompt",
            "prompt_config": {
                "provider": "mock",
                "model": "mock-model",
                "endpoint": "https://llm.example.test/v1/chat/completions",
                "user_template": "Answer {{question}}",
                "variable_names": ["question"],
            },
        },
        headers=headers(settings),
    )
    assert response.status_code == 201
    return response.json()["current_version_id"]


def create_dataset(client: TestClient, settings: Settings) -> str:
    response = client.post(
        "/projects/project-1/datasets",
        json={
            "name": "Order checks",
            "metadata": {"source": "regression"},
            "cases": [
                {
                    "id": "cancel-42",
                    "input": "Cancel order 42",
                    "expected_state": {"status": "cancelled"},
                    "metadata": {"category": "orders"},
                },
                {
                    "id": "cancel-43",
                    "input": "Cancel order 43",
                    "expected_state": {"status": "cancelled"},
                    "metadata": {"category": "orders"},
                },
            ],
        },
        headers=headers(settings),
    )
    assert response.status_code == 201
    return response.json()["current_version_id"]


def create_evaluator(
    client: TestClient,
    settings: Settings,
    *,
    name: str = "task_success",
    requires: list[str] | None = None,
    supported_agent_types: list[str] | None = None,
    evaluator_type: str = "deterministic",
    rubric: str | None = None,
    judge_model: str | None = None,
    config: dict[str, object] | None = None,
    threshold: float = 1,
) -> str:
    response = client.post(
        "/projects/project-1/evaluators",
        json={
            "name": name,
            "version": "1.0.0",
            "evaluator_type": evaluator_type,
            "requires": requires if requires is not None else ["expected_state"],
            "supported_agent_types": (
                supported_agent_types if supported_agent_types is not None else ["tool"]
            ),
            "score_min": 0,
            "score_max": 1,
            "direction": "higher_is_better",
            "default_threshold": threshold,
            "rubric": rubric,
            "judge_model": judge_model,
            "config": config if config is not None else {"comparison": "subset"},
        },
        headers=headers(settings),
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_create_run_freezes_configuration_and_queues_each_case(
    run_client: tuple[TestClient, Settings, Session],
) -> None:
    client, settings, session = run_client
    agent_version_id = create_tool_agent(client, settings)
    dataset_version_id = create_dataset(client, settings)
    evaluator_id = create_evaluator(client, settings)

    created = client.post(
        "/projects/project-1/runs",
        json={
            "agent_version_id": agent_version_id,
            "dataset_version_id": dataset_version_id,
            "evaluator_version_ids": [evaluator_id],
        },
        headers=headers(settings),
    )

    assert created.status_code == 201
    run = created.json()
    assert run["status"] == "queued"
    assert run["total_cases"] == 2
    assert run["configuration_snapshot"]["agent_version"]["agent_type"] == "tool"
    assert run["configuration_snapshot"]["evaluators"][0]["id"] == evaluator_id

    stored = session.get(EvaluationRunRecord, run["id"])
    assert stored is not None
    assert stored.configuration_snapshot["dataset_version"]["metadata"] == {"source": "regression"}
    executions = session.scalars(
        select(CaseExecutionRecord).where(CaseExecutionRecord.run_id == run["id"])
    ).all()
    assert len(executions) == 2
    assert {execution.status for execution in executions} == {"queued"}

    detail = client.get(f"/projects/project-1/runs/{run['id']}", headers=headers(settings))
    assert detail.status_code == 200
    assert [item["case_id"] for item in detail.json()["case_executions"]] == [
        "cancel-42",
        "cancel-43",
    ]


def test_run_creation_rejects_invalid_versions_and_incompatible_requirements(
    run_client: tuple[TestClient, Settings, Session],
) -> None:
    client, settings, _ = run_client
    agent_version_id = create_tool_agent(client, settings)
    dataset_version_id = create_dataset(client, settings)
    evaluator_id = create_evaluator(client, settings, requires=["expected_tools"])

    missing_data = client.post(
        "/projects/project-1/runs",
        json={
            "agent_version_id": agent_version_id,
            "dataset_version_id": dataset_version_id,
            "evaluator_version_ids": [evaluator_id],
        },
        headers=headers(settings),
    )
    assert missing_data.status_code == 422
    assert missing_data.json()["detail"]["missing"][0]["fields"] == ["expected_tools"]

    incompatible_id = create_evaluator(
        client,
        settings,
        name="prompt_only",
        requires=[],
        supported_agent_types=["prompt"],
    )
    incompatible = client.post(
        "/projects/project-1/runs",
        json={
            "agent_version_id": agent_version_id,
            "dataset_version_id": dataset_version_id,
            "evaluator_version_ids": [incompatible_id],
        },
        headers=headers(settings),
    )
    assert incompatible.status_code == 422
    assert (
        incompatible.json()["detail"]["message"]
        == "evaluator does not support the selected agent type"
    )

    foreign_agent_version_id = create_tool_agent(client, settings, "project-2")
    isolated = client.post(
        "/projects/project-1/runs",
        json={
            "agent_version_id": foreign_agent_version_id,
            "dataset_version_id": dataset_version_id,
            "evaluator_version_ids": [evaluator_id],
        },
        headers=headers(settings),
    )
    assert isolated.status_code == 404


def test_case_execution_persists_trace_isolates_failures_and_is_idempotent(
    run_client: tuple[TestClient, Settings, Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, settings, session = run_client
    agent_version_id = create_tool_agent(client, settings)
    dataset_version_id = create_dataset(client, settings)
    evaluator_id = create_evaluator(client, settings)
    created = client.post(
        "/projects/project-1/runs",
        json={
            "agent_version_id": agent_version_id,
            "dataset_version_id": dataset_version_id,
            "evaluator_version_ids": [evaluator_id],
        },
        headers=headers(settings),
    )
    assert created.status_code == 201
    run_id = created.json()["id"]
    executions = session.scalars(
        select(CaseExecutionRecord)
        .where(CaseExecutionRecord.run_id == run_id)
        .order_by(CaseExecutionRecord.case_id)
    ).all()

    calls: list[str] = []

    async def fake_http_agent(
        _config: object,
        _input_value: object,
        *,
        case_id: str,
        **_kwargs: object,
    ) -> HttpAgentRunResult:
        calls.append(case_id)
        if case_id == "cancel-42":
            raise AgentAdapterError("service_error", "agent backend unavailable")
        return HttpAgentRunResult(
            output={"status": "cancelled", "order_id": "43"},
            tool_calls=[ExpectedToolCall(name="cancel_order", arguments={"order_id": "43"})],
            usage={"input_tokens": 12, "output_tokens": 5, "cost": 0.001},
            trace={"source": "agent"},
            raw_response={"output": {"status": "cancelled", "order_id": "43"}},
            request_metadata={"run_id": run_id, "case_id": case_id},
        )

    monkeypatch.setattr("agent_eval_worker.execution.run_http_agent", fake_http_agent)

    executions_by_key = {execution.dataset_case.case_key: execution for execution in executions}
    first = execute_case(session, settings, run_id, executions_by_key["cancel-42"].case_id)
    second = execute_case(session, settings, run_id, executions_by_key["cancel-43"].case_id)
    duplicate = execute_case(session, settings, run_id, executions_by_key["cancel-43"].case_id)

    assert first["status"] == "failed"
    assert second["status"] == "completed"
    assert duplicate == {"status": "already_finished"}
    assert calls == ["cancel-42", "cancel-43"]

    failed = executions_by_key["cancel-42"]
    succeeded = executions_by_key["cancel-43"]
    session.refresh(failed)
    session.refresh(succeeded)
    assert failed.status == "failed"
    assert failed.error_type == "service_error"
    assert failed.trace_id is not None
    assert succeeded.status == "completed"
    assert succeeded.output == {"status": "cancelled", "order_id": "43"}
    assert succeeded.tool_calls == [
        {"name": "cancel_order", "arguments": {"order_id": "43"}, "order": None}
    ]
    assert succeeded.usage == {"input_tokens": 12, "output_tokens": 5, "cost": 0.001}
    assert succeeded.trace_id is not None
    assert succeeded.attempt == 1

    failed_trace = session.get(TraceRecord, failed.trace_id)
    completed_trace = session.get(TraceRecord, succeeded.trace_id)
    assert failed_trace is not None
    assert failed_trace.status == "failed"
    assert completed_trace is not None
    assert completed_trace.status == "completed"
    assert completed_trace.case_id == "cancel-43"

    run = session.get(EvaluationRunRecord, run_id)
    assert run is not None
    assert run.status == RunStatus.PARTIAL.value
    assert run.completed_cases == 1
    assert run.failed_cases == 1
    failed_scores = session.scalars(
        select(ScoreRecord).where(ScoreRecord.run_id == run_id, ScoreRecord.case_id == "cancel-42")
    ).all()
    completed_scores = session.scalars(
        select(ScoreRecord).where(ScoreRecord.run_id == run_id, ScoreRecord.case_id == "cancel-43")
    ).all()
    assert len(failed_scores) == 1
    assert failed_scores[0].status == "not_run"
    assert failed_scores[0].trace_id == failed.trace_id
    assert len(completed_scores) == 1
    assert completed_scores[0].status == "passed"
    assert completed_scores[0].value == 1
    assert completed_scores[0].evidence[0]["expected_state"] == {"status": "cancelled"}
    aggregate = session.scalar(
        select(AggregateMetricRecord).where(AggregateMetricRecord.run_id == run_id)
    )
    assert aggregate is not None
    assert aggregate.valid_count == 1
    assert aggregate.missing_count == 1
    assert aggregate.error_count == 0
    assert aggregate.passed_count == 1
    assert aggregate.average == 1
    assert aggregate.pass_rate == 1
    assert aggregate.aggregation == "pass_rate"


def test_case_execution_persists_prompt_and_llm_trace_spans(
    run_client: tuple[TestClient, Settings, Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, settings, session = run_client
    agent_version_id = create_prompt_agent(client, settings)
    dataset_version_id = create_dataset(client, settings)
    evaluator_id = create_evaluator(
        client,
        settings,
        name="prompt_latency",
        requires=[],
        supported_agent_types=["prompt"],
    )
    created = client.post(
        "/projects/project-1/runs",
        json={
            "agent_version_id": agent_version_id,
            "dataset_version_id": dataset_version_id,
            "evaluator_version_ids": [evaluator_id],
        },
        headers=headers(settings),
    )
    assert created.status_code == 201
    run_id = created.json()["id"]
    execution = session.scalar(
        select(CaseExecutionRecord).where(CaseExecutionRecord.run_id == run_id)
    )
    assert execution is not None

    async def fake_prompt_runner(*_args: object, **_kwargs: object) -> PromptRunResult:
        return PromptRunResult(
            output={"answer": "Order cancellation is ready."},
            rendered_prompt="Answer cancel order",
            variables_snapshot={"question": "cancel order"},
            messages=[{"role": "user", "content": "Answer cancel order"}],
            usage=PromptUsage(input_tokens=8, output_tokens=4, total_tokens=12, cost=0.002),
            raw_response={"choices": [{"message": {"content": "answer"}}]},
        )

    monkeypatch.setattr("agent_eval_worker.execution.run_prompt", fake_prompt_runner)

    result = execute_case(session, settings, run_id, execution.case_id)

    assert result["status"] == "completed"
    session.refresh(execution)
    assert execution.output == {"answer": "Order cancellation is ready."}
    assert execution.usage == {
        "input_tokens": 8,
        "output_tokens": 4,
        "total_tokens": 12,
        "cost": 0.002,
    }
    trace = session.get(TraceRecord, execution.trace_id)
    assert trace is not None
    spans_by_kind = {span.kind: span for span in trace.spans}
    assert set(spans_by_kind) == {"agent", "prompt", "llm", "evaluator"}
    assert spans_by_kind["prompt"].parent_span_id == spans_by_kind["agent"].span_id
    assert spans_by_kind["llm"].parent_span_id == spans_by_kind["prompt"].span_id


def test_cancel_run_marks_pending_cases_and_is_idempotent(
    run_client: tuple[TestClient, Settings, Session],
) -> None:
    client, settings, _ = run_client
    agent_version_id = create_tool_agent(client, settings)
    dataset_version_id = create_dataset(client, settings)
    evaluator_id = create_evaluator(client, settings)
    created = client.post(
        "/projects/project-1/runs",
        json={
            "agent_version_id": agent_version_id,
            "dataset_version_id": dataset_version_id,
            "evaluator_version_ids": [evaluator_id],
        },
        headers=headers(settings),
    )
    run_id = created.json()["id"]

    cancelled = client.post(f"/projects/project-1/runs/{run_id}/cancel", headers=headers(settings))
    repeated = client.post(f"/projects/project-1/runs/{run_id}/cancel", headers=headers(settings))
    foreign = client.post(
        f"/projects/project-2/runs/{run_id}/cancel",
        headers=headers(settings, "project-2"),
    )

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert {item["status"] for item in cancelled.json()["case_executions"]} == {"cancelled"}
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "cancelled"
    assert foreign.status_code == 404


def test_worker_discards_result_when_run_is_cancelled_during_invocation(
    run_client: tuple[TestClient, Settings, Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, settings, session = run_client
    agent_version_id = create_tool_agent(client, settings)
    dataset_version_id = create_dataset(client, settings)
    evaluator_id = create_evaluator(client, settings)
    created = client.post(
        "/projects/project-1/runs",
        json={
            "agent_version_id": agent_version_id,
            "dataset_version_id": dataset_version_id,
            "evaluator_version_ids": [evaluator_id],
        },
        headers=headers(settings),
    )
    run_id = created.json()["id"]
    execution = session.scalar(
        select(CaseExecutionRecord).where(CaseExecutionRecord.run_id == run_id)
    )
    assert execution is not None

    async def cancel_before_return(*_args: object, **_kwargs: object) -> HttpAgentRunResult:
        response = client.post(
            f"/projects/project-1/runs/{run_id}/cancel",
            headers=headers(settings),
        )
        assert response.status_code == 200
        return HttpAgentRunResult(
            output="late result",
            tool_calls=[],
            usage={},
            trace=None,
            raw_response={"output": "late result"},
            request_metadata={"run_id": run_id, "case_id": execution.dataset_case.case_key},
        )

    monkeypatch.setattr("agent_eval_worker.execution.run_http_agent", cancel_before_return)

    result = execute_case(session, settings, run_id, execution.case_id)

    assert result == {"status": "cancelled"}
    session.refresh(execution)
    assert execution.status == "cancelled"
    assert execution.output is None
    assert execution.trace_id is None


def test_worker_defers_when_agent_concurrency_limit_is_reached(
    run_client: tuple[TestClient, Settings, Session],
) -> None:
    client, settings, session = run_client
    agent_version_id = create_tool_agent(
        client,
        settings,
        endpoint_overrides={"concurrency_limit": 1},
    )
    dataset_version_id = create_dataset(client, settings)
    evaluator_id = create_evaluator(client, settings)
    created = client.post(
        "/projects/project-1/runs",
        json={
            "agent_version_id": agent_version_id,
            "dataset_version_id": dataset_version_id,
            "evaluator_version_ids": [evaluator_id],
        },
        headers=headers(settings),
    )
    run_id = created.json()["id"]
    executions = session.scalars(
        select(CaseExecutionRecord).where(CaseExecutionRecord.run_id == run_id)
    ).all()
    run = session.get(EvaluationRunRecord, run_id)
    assert run is not None and len(executions) == 2
    run.status = "running"
    run.started_at = datetime.now(UTC)
    executions[0].status = "running"
    executions[0].started_at = datetime.now(UTC)
    session.commit()

    result = execute_case(session, settings, run_id, executions[1].case_id)

    assert result["status"] == "deferred"
    assert float(result["countdown"]) == settings.worker_admission_retry_seconds
    session.refresh(executions[1])
    assert executions[1].status == "queued"
    assert executions[1].attempt == 0


def test_worker_enforces_agent_start_rate_across_completed_cases(
    run_client: tuple[TestClient, Settings, Session],
) -> None:
    client, settings, session = run_client
    agent_version_id = create_tool_agent(
        client,
        settings,
        endpoint_overrides={"concurrency_limit": 4, "rate_limit_per_minute": 1},
    )
    dataset_version_id = create_dataset(client, settings)
    evaluator_id = create_evaluator(client, settings)
    created = client.post(
        "/projects/project-1/runs",
        json={
            "agent_version_id": agent_version_id,
            "dataset_version_id": dataset_version_id,
            "evaluator_version_ids": [evaluator_id],
        },
        headers=headers(settings),
    )
    run_id = created.json()["id"]
    executions = session.scalars(
        select(CaseExecutionRecord).where(CaseExecutionRecord.run_id == run_id)
    ).all()
    run = session.get(EvaluationRunRecord, run_id)
    assert run is not None and len(executions) == 2
    run.status = "running"
    run.started_at = datetime.now(UTC)
    run.completed_cases = 1
    executions[0].status = "completed"
    executions[0].started_at = datetime.now(UTC)
    executions[0].finished_at = datetime.now(UTC)
    session.commit()

    result = execute_case(session, settings, run_id, executions[1].case_id)

    assert result["status"] == "deferred"
    assert float(result["countdown"]) > 59
    session.refresh(executions[1])
    assert executions[1].status == "queued"


def test_worker_persists_llm_judge_metadata_evidence_and_sanitized_raw_result(
    run_client: tuple[TestClient, Settings, Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, settings, session = run_client
    agent_version_id = create_tool_agent(client, settings)
    dataset_version_id = create_dataset(client, settings)
    evaluator_id = create_evaluator(
        client,
        settings,
        name="answer_quality",
        requires=[],
        supported_agent_types=["tool"],
        evaluator_type="llm_judge",
        rubric="Judge correctness against the reference.",
        judge_model="judge-model-v1",
        config={"endpoint": "https://judge.example.test/v1/chat/completions"},
        threshold=0.8,
    )
    created = client.post(
        "/projects/project-1/runs",
        json={
            "agent_version_id": agent_version_id,
            "dataset_version_id": dataset_version_id,
            "evaluator_version_ids": [evaluator_id],
        },
        headers=headers(settings),
    )
    run_id = created.json()["id"]
    execution = session.scalar(
        select(CaseExecutionRecord).where(CaseExecutionRecord.run_id == run_id)
    )
    assert execution is not None

    async def fake_http_agent(*_args: object, **_kwargs: object) -> HttpAgentRunResult:
        return HttpAgentRunResult(
            output="Order cancellation is ready.",
            tool_calls=[],
            usage={"cost": 0.001},
            trace=None,
            raw_response={"output": "Order cancellation is ready."},
            request_metadata={"run_id": run_id, "case_id": execution.dataset_case.case_key},
        )

    async def fake_judge(*_args: object, **_kwargs: object) -> list[EvaluatorOutcome]:
        return [
            EvaluatorOutcome(
                metric_name="answer_quality",
                status=ScoreStatus.PASSED,
                value=0.9,
                label="good",
                passed=True,
                explanation="The response is correct.",
                evidence=[{"claim": "Cancellation is ready."}],
                raw_result={"api_key": "must-not-persist", "decision": {"score": 0.9}},
            )
        ]

    monkeypatch.setattr("agent_eval_worker.execution.run_http_agent", fake_http_agent)
    monkeypatch.setattr("agent_eval_api.evaluation.scoring.evaluate_llm_judge", fake_judge)

    result = execute_case(session, settings, run_id, execution.case_id)

    assert result["status"] == "completed"
    score = session.scalar(
        select(ScoreRecord).where(
            ScoreRecord.run_id == run_id,
            ScoreRecord.evaluator_version_id == evaluator_id,
        )
    )
    assert score is not None
    assert score.status == "passed"
    assert score.value == 0.9
    assert score.label == "good"
    assert score.passed is True
    assert score.rubric == "Judge correctness against the reference."
    assert score.judge_model == "judge-model-v1"
    assert score.threshold == 0.8
    assert score.direction == "higher_is_better"
    assert score.trace_id == execution.trace_id
    assert score.evidence == [{"claim": "Cancellation is ready."}]
    assert score.raw_result["api_key"] == {"__agent_eval_redacted": True}
    assert score.raw_result["decision"] == {"score": 0.9}

    trace = session.get(TraceRecord, execution.trace_id)
    assert trace is not None
    agent_span = next(span for span in trace.spans if span.kind == "agent")
    evaluator_span = next(span for span in trace.spans if span.kind == "evaluator")
    assert evaluator_span.parent_span_id == agent_span.span_id
    assert evaluator_span.output["score_id"] == score.id
