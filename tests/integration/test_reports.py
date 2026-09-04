import csv
import io
import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from agent_eval_api import auth
from agent_eval_api.auth import get_db, issue_dev_session
from agent_eval_api.db import (
    AgentVersionRecord,
    Base,
    CaseExecutionRecord,
    EvaluationRunRecord,
    ProjectRecord,
    ScoreRecord,
)
from agent_eval_api.main import create_app
from agent_eval_api.runner import AgentAdapterError, HttpAgentRunResult
from agent_eval_api.settings import Settings
from agent_eval_worker.execution import execute_case


@pytest.fixture
def report_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, Settings, Session]]:
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


def create_run(client: TestClient, settings: Settings) -> str:
    agent = client.post(
        "/projects/project-1/agents",
        json={
            "name": "Report target",
            "agent_type": "tool",
            "endpoint_config": {"url": "https://agent.example.test/run"},
        },
        headers=headers(settings),
    )
    dataset = client.post(
        "/projects/project-1/datasets",
        json={
            "name": "Segmented cases",
            "cases": [
                {
                    "id": "retail-ok",
                    "input": "cancel 42",
                    "expected_state": {"status": "cancelled"},
                    "metadata": {
                        "category": "retail",
                        "difficulty": "easy",
                        "tags": ["smoke"],
                    },
                },
                {
                    "id": "enterprise-error",
                    "input": "cancel 43",
                    "expected_state": {"status": "cancelled"},
                    "metadata": {
                        "category": "enterprise",
                        "difficulty": "hard",
                        "tags": ["regression"],
                    },
                },
            ],
        },
        headers=headers(settings),
    )
    evaluator = client.post(
        "/projects/project-1/evaluators",
        json={
            "name": "task_success",
            "version": "1.0.0",
            "evaluator_type": "deterministic",
            "requires": ["expected_state"],
            "supported_agent_types": ["tool"],
            "score_min": 0,
            "score_max": 1,
            "direction": "higher_is_better",
            "default_threshold": 1,
        },
        headers=headers(settings),
    )
    response = client.post(
        "/projects/project-1/runs",
        json={
            "agent_version_id": agent.json()["current_version_id"],
            "dataset_version_id": dataset.json()["current_version_id"],
            "evaluator_version_ids": [evaluator.json()["id"]],
        },
        headers=headers(settings),
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_report_filters_cases_scores_and_recomputes_metrics(
    report_client: tuple[TestClient, Settings, Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, settings, session = report_client
    run_id = create_run(client, settings)
    executions = session.scalars(
        select(CaseExecutionRecord).where(CaseExecutionRecord.run_id == run_id)
    ).all()

    async def fake_agent(
        *_args: object,
        case_id: str,
        **_kwargs: object,
    ) -> HttpAgentRunResult:
        if case_id == "enterprise-error":
            raise AgentAdapterError("service_error", "agent unavailable")
        return HttpAgentRunResult(
            output={"status": "cancelled"},
            tool_calls=[],
            usage={"cost": 0.001},
            trace=None,
            raw_response={"output": {"status": "cancelled"}},
            request_metadata={"run_id": run_id, "case_id": case_id},
        )

    monkeypatch.setattr("agent_eval_worker.execution.run_http_agent", fake_agent)
    for execution in executions:
        execute_case(session, settings, run_id, execution.case_id)

    summaries = client.get(
        "/projects/project-1/reports?status=partial",
        headers=headers(settings),
    )
    assert summaries.status_code == 200
    assert [summary["run_id"] for summary in summaries.json()] == [run_id]
    assert summaries.json()[0]["metrics"][0]["valid_count"] == 1
    assert summaries.json()[0]["metrics"][0]["missing_count"] == 1

    retail = client.get(
        f"/projects/project-1/reports/{run_id}",
        params={
            "metric": "task_success",
            "category": "retail",
            "difficulty": "easy",
            "tag": "smoke",
            "execution_status": "completed",
        },
        headers=headers(settings),
    )
    assert retail.status_code == 200
    assert retail.json()["matched_cases"] == 1
    assert retail.json()["cases"][0]["case_id"] == "retail-ok"
    assert retail.json()["cases"][0]["scores"][0]["status"] == "passed"
    assert retail.json()["metrics"][0]["valid_count"] == 1
    assert retail.json()["metrics"][0]["pass_rate"] == 1

    failed = client.get(
        f"/projects/project-1/reports/{run_id}",
        params={
            "category": "enterprise",
            "difficulty": "hard",
            "tag": "regression",
            "error_type": "service_error",
            "execution_status": "failed",
        },
        headers=headers(settings),
    )
    assert failed.status_code == 200
    assert failed.json()["matched_cases"] == 1
    assert failed.json()["cases"][0]["error_type"] == "service_error"
    assert failed.json()["cases"][0]["scores"][0]["status"] == "not_run"
    assert failed.json()["metrics"][0]["valid_count"] == 0
    assert failed.json()["metrics"][0]["missing_count"] == 1
    assert failed.json()["metrics"][0]["pass_rate"] is None

    exported_json = client.get(
        f"/projects/project-1/reports/{run_id}/export",
        params={"format": "json", "category": "retail", "metric": "task_success"},
        headers=headers(settings),
    )
    assert exported_json.status_code == 200
    assert exported_json.headers["content-type"].startswith("application/json")
    document = json.loads(exported_json.text)
    assert document["schema_version"] == 1
    assert document["run"]["id"] == run_id
    assert document["run"]["configuration_snapshot"]["agent_version"]["version"] == 1
    assert document["run"]["configuration_snapshot"]["dataset_version"]["version"] == 1
    assert document["run"]["configuration_snapshot"]["evaluators"][0]["version"] == "1.0.0"
    assert document["metrics"][0]["threshold"] == 1
    assert document["metrics"][0]["direction"] == "higher_is_better"
    assert document["cases"][0]["case_id"] == "retail-ok"
    assert document["generated_at"]

    exported_csv = client.get(
        f"/projects/project-1/reports/{run_id}/export",
        params={"format": "csv", "category": "enterprise"},
        headers=headers(settings),
    )
    assert exported_csv.status_code == 200
    assert exported_csv.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(exported_csv.text)))
    assert len(rows) == 1
    assert rows[0]["case_id"] == "enterprise-error"
    assert rows[0]["score_status"] == "not_run"
    assert rows[0]["evaluator_version"] == "1.0.0"
    assert rows[0]["threshold"] == "1.0"
    assert rows[0]["direction"] == "higher_is_better"
    assert json.loads(rows[0]["metadata"])["difficulty"] == "hard"
    assert rows[0]["generated_at"]

    isolated = client.get(
        f"/projects/project-2/reports/{run_id}",
        headers=headers(settings, "project-2"),
    )
    assert isolated.status_code == 404


def test_compare_runs_reports_deltas_groups_and_case_changes(
    report_client: tuple[TestClient, Settings, Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, settings, session = report_client
    baseline_id = create_run(client, settings)
    baseline = session.get(EvaluationRunRecord, baseline_id)
    assert baseline is not None
    baseline_agent_version = session.get(AgentVersionRecord, baseline.agent_version_id)
    assert baseline_agent_version is not None
    evaluator_id = baseline.configuration_snapshot["evaluators"][0]["id"]

    candidate_agent = client.post(
        f"/projects/project-1/agents/{baseline_agent_version.agent_id}/versions",
        json={
            "name": "Report target",
            "agent_type": "tool",
            "endpoint_config": {"url": "https://agent.example.test/run-v2"},
            "label": "candidate",
        },
        headers=headers(settings),
    )
    assert candidate_agent.status_code == 201
    candidate_run = client.post(
        "/projects/project-1/runs",
        json={
            "agent_version_id": candidate_agent.json()["id"],
            "dataset_version_id": baseline.dataset_version_id,
            "evaluator_version_ids": [evaluator_id],
        },
        headers=headers(settings),
    )
    assert candidate_run.status_code == 201
    candidate_id = candidate_run.json()["id"]

    async def fake_agent(
        *_args: object,
        case_id: str,
        run_id: str,
        **_kwargs: object,
    ) -> HttpAgentRunResult:
        is_candidate = run_id == candidate_id
        should_fail = (case_id == "retail-ok") == is_candidate
        output = {"status": "active" if should_fail else "cancelled"}
        return HttpAgentRunResult(
            output=output,
            tool_calls=[],
            usage={"cost": 0.001},
            trace=None,
            raw_response={"output": output},
            request_metadata={"run_id": run_id, "case_id": case_id},
        )

    monkeypatch.setattr("agent_eval_worker.execution.run_http_agent", fake_agent)
    for run_id in (baseline_id, candidate_id):
        executions = session.scalars(
            select(CaseExecutionRecord).where(CaseExecutionRecord.run_id == run_id)
        ).all()
        for execution in executions:
            execute_case(session, settings, run_id, execution.case_id)

    comparison = client.post(
        "/projects/project-1/comparisons",
        json={"run_ids": [baseline_id, candidate_id]},
        headers=headers(settings),
    )
    assert comparison.status_code == 200
    document = comparison.json()
    assert document["baseline_run_id"] == baseline_id
    assert document["dataset_version_id"] == baseline.dataset_version_id
    assert [item["run_id"] for item in document["runs"]] == [baseline_id, candidate_id]

    metric = document["metric_comparisons"][0]
    assert metric["metric_name"] == "task_success"
    assert metric["comparable"] is True
    assert metric["points"][0]["pass_rate"] == 0.5
    assert metric["points"][1]["pass_rate"] == 0.5
    assert metric["points"][1]["delta_pass_rate"] == 0
    groups = {
        (item["group_by"], item["group_value"]): item
        for item in document["group_comparisons"]
    }
    assert groups[("category", "retail")]["points"][1]["pass_rate"] == 0
    assert groups[("category", "enterprise")]["points"][1]["pass_rate"] == 1
    assert document["new_failures"][0]["case_id"] == "retail-ok"
    assert document["new_failures"][0]["run_id"] == candidate_id
    assert document["recovered_cases"][0]["case_id"] == "enterprise-error"
    assert document["recovered_cases"][0]["run_id"] == candidate_id
    cases = {item["case_id"]: item for item in document["case_comparisons"]}
    assert cases["retail-ok"]["runs"][0]["failed"] is False
    assert cases["retail-ok"]["runs"][1]["failed"] is True
    assert cases["enterprise-error"]["runs"][0]["failed"] is True
    assert cases["enterprise-error"]["runs"][1]["failed"] is False

    different_dataset = client.post(
        "/projects/project-1/datasets",
        json={
            "name": "Different dataset",
            "cases": [
                {
                    "id": "other",
                    "input": "other",
                    "expected_state": {"status": "cancelled"},
                }
            ],
        },
        headers=headers(settings),
    )
    assert different_dataset.status_code == 201
    different_dataset_run_response = client.post(
        "/projects/project-1/runs",
        json={
            "agent_version_id": baseline.agent_version_id,
            "dataset_version_id": different_dataset.json()["current_version_id"],
            "evaluator_version_ids": [evaluator_id],
        },
        headers=headers(settings),
    )
    assert different_dataset_run_response.status_code == 201
    different_dataset_run = different_dataset_run_response.json()["id"]
    different_dataset = client.post(
        "/projects/project-1/comparisons",
        json={"run_ids": [baseline_id, different_dataset_run]},
        headers=headers(settings),
    )
    assert different_dataset.status_code == 422

    isolated = client.post(
        "/projects/project-2/comparisons",
        json={"run_ids": [baseline_id, candidate_id]},
        headers=headers(settings, "project-2"),
    )
    assert isolated.status_code == 404


def test_compare_runs_marks_metrics_with_different_evaluator_versions_incomparable(
    report_client: tuple[TestClient, Settings, Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, settings, session = report_client
    baseline_id = create_run(client, settings)
    baseline = session.get(EvaluationRunRecord, baseline_id)
    assert baseline is not None

    alternative_evaluator = client.post(
        "/projects/project-1/evaluators",
        json={
            "name": "task_success",
            "version": "2.0.0",
            "evaluator_type": "deterministic",
            "requires": ["expected_state"],
            "supported_agent_types": ["tool"],
            "score_min": 0,
            "score_max": 1,
            "direction": "higher_is_better",
            "default_threshold": 1,
        },
        headers=headers(settings),
    )
    assert alternative_evaluator.status_code == 201
    candidate_run = client.post(
        "/projects/project-1/runs",
        json={
            "agent_version_id": baseline.agent_version_id,
            "dataset_version_id": baseline.dataset_version_id,
            "evaluator_version_ids": [alternative_evaluator.json()["id"]],
        },
        headers=headers(settings),
    )
    assert candidate_run.status_code == 201
    candidate_id = candidate_run.json()["id"]

    async def fake_agent(*_args: object, **_kwargs: object) -> HttpAgentRunResult:
        output = {"status": "cancelled"}
        return HttpAgentRunResult(
            output=output,
            tool_calls=[],
            usage={"cost": 0.001},
            trace=None,
            raw_response={"output": output},
            request_metadata={},
        )

    monkeypatch.setattr("agent_eval_worker.execution.run_http_agent", fake_agent)
    for run_id in (baseline_id, candidate_id):
        executions = session.scalars(
            select(CaseExecutionRecord).where(CaseExecutionRecord.run_id == run_id)
        ).all()
        for execution in executions:
            execute_case(session, settings, run_id, execution.case_id)

    comparison = client.post(
        "/projects/project-1/comparisons",
        json={"run_ids": [baseline_id, candidate_id]},
        headers=headers(settings),
    )
    assert comparison.status_code == 200
    metric = comparison.json()["metric_comparisons"][0]
    assert metric["metric_name"] == "task_success"
    assert metric["comparable"] is False
    assert metric["reason"] == "metric uses different evaluator versions across runs"
    assert metric["points"][1]["delta_average"] is None
    assert metric["points"][1]["delta_pass_rate"] is None


def test_regression_gate_reports_machine_readable_threshold_hard_gate_and_missing_data(
    report_client: tuple[TestClient, Settings, Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, settings, session = report_client
    pending_run_id = create_run(client, settings)
    incomplete = client.post(
        f"/projects/project-1/runs/{pending_run_id}/regression-gate",
        json={"rules": [{"metric_name": "task_success", "minimum": 1}]},
        headers=headers(settings),
    )
    assert incomplete.status_code == 200
    assert incomplete.json()["status"] == "incomplete"
    assert incomplete.json()["rules"][0]["status"] == "indeterminate"

    baseline = session.get(EvaluationRunRecord, pending_run_id)
    assert baseline is not None
    policy_evaluator = client.post(
        "/projects/project-1/evaluators",
        json={
            "name": "policy_compliance",
            "version": "1.0.0",
            "evaluator_type": "deterministic",
            "requires": [],
            "supported_agent_types": ["tool"],
            "score_min": 0,
            "score_max": 1,
            "direction": "higher_is_better",
            "default_threshold": 1,
            "config": {"forbidden_output_patterns": ["restricted"]},
        },
        headers=headers(settings),
    )
    assert policy_evaluator.status_code == 201
    task_evaluator_id = baseline.configuration_snapshot["evaluators"][0]["id"]
    completed_run = client.post(
        "/projects/project-1/runs",
        json={
            "agent_version_id": baseline.agent_version_id,
            "dataset_version_id": baseline.dataset_version_id,
            "evaluator_version_ids": [task_evaluator_id, policy_evaluator.json()["id"]],
        },
        headers=headers(settings),
    )
    assert completed_run.status_code == 201
    completed_run_id = completed_run.json()["id"]

    async def fake_agent(
        *_args: object,
        case_id: str,
        **_kwargs: object,
    ) -> HttpAgentRunResult:
        output = {"status": "cancelled"}
        if case_id == "retail-ok":
            output["note"] = "restricted content"
        return HttpAgentRunResult(
            output=output,
            tool_calls=[],
            usage={"cost": 0.001},
            trace=None,
            raw_response={"output": output},
            request_metadata={"case_id": case_id},
        )

    monkeypatch.setattr("agent_eval_worker.execution.run_http_agent", fake_agent)
    executions = session.scalars(
        select(CaseExecutionRecord).where(CaseExecutionRecord.run_id == completed_run_id)
    ).all()
    for execution in executions:
        execute_case(session, settings, completed_run_id, execution.case_id)

    failed = client.post(
        f"/projects/project-1/runs/{completed_run_id}/regression-gate",
        json={
            "rules": [
                {"metric_name": "task_success", "minimum": 1},
                {"metric_name": "policy_compliance", "require_all_passed": True},
            ]
        },
        headers=headers(settings),
    )
    assert failed.status_code == 200
    result = failed.json()
    assert result["status"] == "failed"
    assert result["rules"][0]["status"] == "passed"
    assert result["rules"][1]["status"] == "failed"
    assert result["rules"][1]["failed_case_ids"] == ["retail-ok"]

    maximum = client.post(
        f"/projects/project-1/runs/{completed_run_id}/regression-gate",
        json={"rules": [{"metric_name": "task_success", "maximum": 0.5}]},
        headers=headers(settings),
    )
    assert maximum.status_code == 200
    assert maximum.json()["status"] == "failed"
    assert maximum.json()["rules"][0]["actual_value"] == 1

    policy_score = session.scalar(
        select(ScoreRecord).where(
            ScoreRecord.run_id == completed_run_id,
            ScoreRecord.metric_name == "policy_compliance",
        )
    )
    assert policy_score is not None
    policy_score.status = "error"
    policy_score.passed = None
    session.commit()
    indeterminate = client.post(
        f"/projects/project-1/runs/{completed_run_id}/regression-gate",
        json={"rules": [{"metric_name": "policy_compliance", "minimum": 1}]},
        headers=headers(settings),
    )
    assert indeterminate.status_code == 200
    assert indeterminate.json()["status"] == "indeterminate"
    assert indeterminate.json()["rules"][0]["error_count"] == 1
