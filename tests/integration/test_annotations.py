from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from agent_eval_api import auth
from agent_eval_api.auth import get_db, issue_dev_session, issue_project_key
from agent_eval_api.db import (
    Base,
    CaseExecutionRecord,
    HumanScoreAuditRecord,
    ProjectRecord,
    ScoreRecord,
)
from agent_eval_api.main import create_app
from agent_eval_api.runner import HttpAgentRunResult
from agent_eval_api.settings import Settings
from agent_eval_worker.execution import execute_case


@pytest.fixture
def annotation_client(
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


def create_review_run(client: TestClient, settings: Settings) -> tuple[str, str]:
    agent = client.post(
        "/projects/project-1/agents",
        json={
            "name": "Review target",
            "agent_type": "tool",
            "endpoint_config": {"url": "https://agent.example.test/run"},
        },
        headers=headers(settings),
    )
    assert agent.status_code == 201
    dataset = client.post(
        "/projects/project-1/datasets",
        json={"name": "Review cases", "cases": [{"id": "case-1", "input": "hello"}]},
        headers=headers(settings),
    )
    assert dataset.status_code == 201
    evaluator = client.post(
        "/projects/project-1/evaluators",
        json={
            "name": "human_quality",
            "version": "1.0.0",
            "evaluator_type": "human",
            "requires": [],
            "supported_agent_types": ["tool"],
            "score_min": 0,
            "score_max": 1,
            "direction": "higher_is_better",
            "default_threshold": 0.8,
            "rubric": "Judge whether the answer is useful.",
        },
        headers=headers(settings),
    )
    assert evaluator.status_code == 201
    run = client.post(
        "/projects/project-1/runs",
        json={
            "agent_version_id": agent.json()["current_version_id"],
            "dataset_version_id": dataset.json()["current_version_id"],
            "evaluator_version_ids": [evaluator.json()["id"]],
        },
        headers=headers(settings),
    )
    assert run.status_code == 201
    return run.json()["id"], evaluator.json()["id"]


def test_human_review_queue_updates_not_run_score_and_keeps_audit_history(
    annotation_client: tuple[TestClient, Settings, Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, settings, session = annotation_client
    run_id, evaluator_id = create_review_run(client, settings)
    execution = session.scalar(
        select(CaseExecutionRecord).where(CaseExecutionRecord.run_id == run_id)
    )
    assert execution is not None

    async def fake_agent(*_args: object, **_kwargs: object) -> HttpAgentRunResult:
        return HttpAgentRunResult(
            output="Hello from the agent",
            tool_calls=[],
            usage={},
            trace=None,
            raw_response={"output": "Hello from the agent"},
            request_metadata={"run_id": run_id, "case_id": "case-1"},
        )

    monkeypatch.setattr("agent_eval_worker.execution.run_http_agent", fake_agent)
    assert execute_case(session, settings, run_id, execution.case_id)["status"] == "completed"
    placeholder = session.scalar(
        select(ScoreRecord).where(
            ScoreRecord.run_id == run_id,
            ScoreRecord.evaluator_version_id == evaluator_id,
        )
    )
    assert placeholder is not None
    assert placeholder.status == "not_run"

    queue = client.post(
        "/projects/project-1/annotation-queues",
        json={
            "name": "Quality review",
            "description": "Manual review for release",
            "evaluator_version_id": evaluator_id,
        },
        headers=headers(settings),
    )
    assert queue.status_code == 201
    queue_id = queue.json()["id"]
    item = client.post(
        f"/projects/project-1/annotation-queues/{queue_id}/items",
        json={"run_id": run_id, "case_id": "case-1"},
        headers=headers(settings),
    )
    assert item.status_code == 201
    item_id = item.json()["id"]
    assert item.json()["trace_id"] == execution.trace_id
    duplicate = client.post(
        f"/projects/project-1/annotation-queues/{queue_id}/items",
        json={"run_id": run_id, "case_id": "case-1"},
        headers=headers(settings),
    )
    assert duplicate.status_code == 409

    raw_key, key_record = issue_project_key("project-1", settings)
    session.add(key_record)
    session.commit()
    forbidden = client.put(
        f"/projects/project-1/annotation-queues/{queue_id}/items/{item_id}/score",
        json={"value": 0.9, "passed": True},
        headers={"X-Project-Key": raw_key},
    )
    assert forbidden.status_code == 403

    first = client.put(
        f"/projects/project-1/annotation-queues/{queue_id}/items/{item_id}/score",
        json={
            "value": 0.9,
            "label": "good",
            "passed": True,
            "explanation": "Useful answer",
            "evidence": [{"api_key": "must-not-persist", "note": "clear"}],
        },
        headers=headers(settings),
    )
    assert first.status_code == 200
    score_id = first.json()["id"]
    assert score_id == placeholder.id
    assert first.json()["status"] == "passed"
    assert first.json()["trace_id"] == execution.trace_id
    assert first.json()["evidence"] == [
        {"api_key": {"__agent_eval_redacted": True}, "note": "clear"}
    ]

    second = client.put(
        f"/projects/project-1/annotation-queues/{queue_id}/items/{item_id}/score",
        json={
            "value": 0.4,
            "label": "needs_work",
            "passed": False,
            "explanation": "Missing detail",
        },
        headers=headers(settings),
    )
    assert second.status_code == 200
    assert second.json()["id"] == score_id
    assert second.json()["status"] == "failed"

    audit = client.get(
        f"/projects/project-1/annotation-queues/{queue_id}/scores/{score_id}/audit",
        headers=headers(settings),
    )
    assert audit.status_code == 200
    assert [entry["action"] for entry in audit.json()] == ["created", "updated"]
    assert audit.json()[0]["previous_value"] is None
    assert audit.json()[1]["previous_value"]["value"] == 0.9
    assert audit.json()[1]["new_value"]["value"] == 0.4
    assert all(entry["reviewer"] == "browser:workspace" for entry in audit.json())
    assert session.query(HumanScoreAuditRecord).count() == 2

    completed_items = client.get(
        f"/projects/project-1/annotation-queues/{queue_id}/items?status=completed",
        headers=headers(settings),
    )
    assert completed_items.status_code == 200
    assert [entry["id"] for entry in completed_items.json()] == [item_id]

    isolated = client.get(
        f"/projects/project-2/annotation-queues/{queue_id}/items",
        headers=headers(settings, "project-2"),
    )
    assert isolated.status_code == 404


def test_annotation_queue_requires_human_evaluator(
    annotation_client: tuple[TestClient, Settings, Session],
) -> None:
    client, settings, _ = annotation_client
    evaluator = client.post(
        "/projects/project-1/evaluators",
        json={
            "name": "exact_match",
            "version": "1.0.0",
            "evaluator_type": "deterministic",
            "requires": ["expected_output"],
            "supported_agent_types": ["prompt"],
            "score_min": 0,
            "score_max": 1,
            "direction": "higher_is_better",
            "default_threshold": 1,
        },
        headers=headers(settings),
    )
    assert evaluator.status_code == 201

    response = client.post(
        "/projects/project-1/annotation-queues",
        json={"name": "invalid", "evaluator_version_id": evaluator.json()["id"]},
        headers=headers(settings),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "annotation queue requires a human evaluator"
