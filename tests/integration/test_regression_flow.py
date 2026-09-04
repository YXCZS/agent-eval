"""Regression coverage for the import -> run -> report -> gate workflow."""

from __future__ import annotations

import base64
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from agent_eval_api import auth
from agent_eval_api.auth import get_db, issue_dev_session
from agent_eval_api.db import Base, CaseExecutionRecord, ProjectRecord
from agent_eval_api.main import create_app
from agent_eval_api.runner import HttpAgentRunResult
from agent_eval_api.settings import Settings
from agent_eval_worker.execution import execute_case


@pytest.fixture
def regression_client(
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
    session.add(ProjectRecord(id="project-1", name="Regression project"))
    session.commit()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[auth.get_settings] = lambda: settings
    monkeypatch.setattr(
        "agent_eval_api.evaluation_runs.enqueue_case_jobs", lambda _run_id, _case_ids: None
    )
    with TestClient(app) as client:
        yield client, settings, session
    session.close()


def _headers(settings: Settings) -> dict[str, str]:
    return {"X-Workspace-Session": issue_dev_session("project-1", settings)}


def test_imported_dataset_runs_to_a_machine_readable_regression_gate(
    regression_client: tuple[TestClient, Settings, Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A CSV import remains usable as a versioned input for a failed quality gate."""

    client, settings, session = regression_client
    headers = _headers(settings)
    dataset = client.post(
        "/projects/project-1/datasets",
        json={"name": "Imported order regression", "cases": []},
        headers=headers,
    ).json()
    csv_content = (
        "case_key,prompt,state\n"
        'cancel-ok,"Cancel order 42","{""status"": ""cancelled""}"\n'
        'cancel-regression,"Cancel order 43","{""status"": ""cancelled""}"\n'
    )
    import_payload = {
        "format": "csv",
        "content_base64": base64.b64encode(csv_content.encode()).decode(),
        "field_mapping": {
            "id": "case_key",
            "input": "prompt",
            "expected_state": "state",
        },
    }
    preview = client.post(
        f"/projects/project-1/datasets/{dataset['id']}/imports/preview",
        json=import_payload,
        headers=headers,
    )
    assert preview.status_code == 200
    assert [case["id"] for case in preview.json()["cases"]] == [
        "cancel-ok",
        "cancel-regression",
    ]
    assert preview.json()["issues"] == []

    imported = client.post(
        f"/projects/project-1/datasets/{dataset['id']}/imports/commit",
        json=import_payload,
        headers=headers,
    )
    assert imported.status_code == 201
    dataset_version_id = imported.json()["dataset_version"]["id"]
    assert imported.json()["dataset_version"]["version"] == 2

    agent = client.post(
        "/projects/project-1/agents",
        json={
            "name": "Order tool agent",
            "agent_type": "tool",
            "endpoint_config": {"url": "https://agent.example.test/run"},
        },
        headers=headers,
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
        headers=headers,
    )
    run = client.post(
        "/projects/project-1/runs",
        json={
            "agent_version_id": agent.json()["current_version_id"],
            "dataset_version_id": dataset_version_id,
            "evaluator_version_ids": [evaluator.json()["id"]],
        },
        headers=headers,
    )
    assert run.status_code == 201
    run_id = run.json()["id"]

    async def fake_agent(*_args: object, case_id: str, **_kwargs: object) -> HttpAgentRunResult:
        output = {"status": "cancelled" if case_id == "cancel-ok" else "active"}
        return HttpAgentRunResult(
            output=output,
            tool_calls=[],
            usage={"cost": 0.001},
            trace=None,
            raw_response={"output": output},
            request_metadata={"run_id": run_id, "case_id": case_id},
        )

    monkeypatch.setattr("agent_eval_worker.execution.run_http_agent", fake_agent)
    executions = session.scalars(
        select(CaseExecutionRecord).where(CaseExecutionRecord.run_id == run_id)
    ).all()
    for execution in executions:
        assert execute_case(session, settings, run_id, execution.case_id)["status"] == "completed"

    report = client.get(f"/projects/project-1/reports/{run_id}", headers=headers)
    assert report.status_code == 200
    metric = report.json()["metrics"][0]
    assert metric["metric_name"] == "task_success"
    assert metric["valid_count"] == 2
    assert metric["pass_rate"] == 0.5

    gate = client.post(
        f"/projects/project-1/runs/{run_id}/regression-gate",
        json={
            "rules": [
                {
                    "metric_name": "task_success",
                    "minimum": 1,
                    "require_all_passed": True,
                }
            ]
        },
        headers=headers,
    )
    assert gate.status_code == 200
    result = gate.json()
    assert result["status"] == "failed"
    assert result["rules"][0]["actual_value"] == 0.5
    assert result["rules"][0]["failed_case_ids"] == ["cancel-regression"]
