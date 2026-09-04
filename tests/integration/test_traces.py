from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from agent_eval_api import auth
from agent_eval_api.auth import get_db, issue_dev_session
from agent_eval_api.db import Base, ProjectRecord
from agent_eval_api.main import create_app
from agent_eval_api.settings import Settings


@pytest.fixture
def trace_client() -> Iterator[tuple[TestClient, Settings, Session]]:
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
    with TestClient(app) as client:
        yield client, settings, session
    session.close()


def headers(settings: Settings, project_id: str = "project-1") -> dict[str, str]:
    return {"X-Workspace-Session": issue_dev_session(project_id, settings)}


def trace_payload() -> dict[str, object]:
    started_at = datetime.now(UTC)
    return {
        "trace_id": "trace-1",
        "case_id": "order-42",
        "status": "completed",
        "source": "http-agent",
        "extensions": {"vendor.trace_id": "external-42"},
        "spans": [
            {
                "span_id": "tool-result",
                "trace_id": "trace-1",
                "parent_span_id": "tool-call",
                "kind": "tool_result",
                "name": "search_order result",
                "status": "completed",
                "started_at": (started_at + timedelta(seconds=2)).isoformat(),
                "output": {"status": "shipped"},
            },
            {
                "span_id": "agent",
                "trace_id": "trace-1",
                "kind": "agent",
                "name": "order-agent",
                "status": "completed",
                "started_at": started_at.isoformat(),
            },
            {
                "span_id": "tool-call",
                "trace_id": "trace-1",
                "parent_span_id": "agent",
                "kind": "tool",
                "name": "search_order",
                "status": "completed",
                "started_at": (started_at + timedelta(seconds=1)).isoformat(),
                "input": {"order_id": "42"},
                "attributes": {"tool.name": "search_order"},
            },
        ],
    }


def test_canonical_trace_persists_hierarchy_and_is_project_scoped(
    trace_client: tuple[TestClient, Settings, Session],
) -> None:
    client, settings, _ = trace_client
    created = client.post(
        "/projects/project-1/traces", json=trace_payload(), headers=headers(settings)
    )

    assert created.status_code == 201
    assert [span["span_id"] for span in created.json()["spans"]] == [
        "agent",
        "tool-call",
        "tool-result",
    ]
    assert created.json()["spans"][2]["parent_span_id"] == "tool-call"

    detail = client.get("/projects/project-1/traces/trace-1", headers=headers(settings))
    assert detail.status_code == 200
    assert detail.json()["extensions"]["vendor.trace_id"] == "external-42"

    forbidden = client.get("/projects/project-2/traces/trace-1", headers=headers(settings))
    assert forbidden.status_code == 401


def test_external_trace_ingestion_normalizes_openinference_fields(
    trace_client: tuple[TestClient, Settings, Session],
) -> None:
    client, settings, _ = trace_client
    response = client.post(
        "/projects/project-1/traces/ingest",
        json={
            "source": "openinference",
            "payload": {
                "trace_id": "external-trace-1",
                "spans": [
                    {
                        "span_id": "span-1",
                        "name": "chat.completions",
                        "startTimeUnixNano": "1720000000000000000",
                        "attributes": {
                            "openinference.span.kind": "LLM",
                            "input.value": '{"question":"Where is order 42?"}',
                            "gen_ai.request.model": "gpt-test",
                        },
                    }
                ],
            },
        },
        headers=headers(settings),
    )

    assert response.status_code == 201
    span = response.json()["spans"][0]
    assert span["kind"] == "llm"
    assert span["input"] == {"question": "Where is order 42?"}
    assert span["attributes"]["gen_ai.request.model"] == "gpt-test"


def test_trace_credentials_are_redacted_and_large_fields_are_referenced(
    trace_client: tuple[TestClient, Settings, Session],
) -> None:
    client, settings, _ = trace_client
    settings.trace_max_field_bytes = 96
    payload = trace_payload()
    span = payload["spans"][0]
    assert isinstance(span, dict)
    span["input"] = {"api_key": "secret-key", "request": "Where is order 42?"}
    span["output"] = "x" * 100
    span["error"] = {"message": "Bearer very-secret-token"}
    span["attributes"] = {"authorization": "Bearer another-secret-token"}
    span["extensions"] = {"credentials": {"password": "not-for-storage"}}

    response = client.post(
        "/projects/project-1/traces", json=payload, headers=headers(settings)
    )

    assert response.status_code == 201
    response_text = response.text
    assert "secret-key" not in response_text
    assert "very-secret-token" not in response_text
    assert "another-secret-token" not in response_text
    persisted = response.json()["spans"][2]
    assert persisted["input"]["api_key"] == {"__agent_eval_redacted": True}
    assert persisted["output"]["__agent_eval_content_ref"]["kind"] == "truncated"
    assert persisted["error"]["message"] == {"__agent_eval_redacted": True}
    assert persisted["attributes"]["authorization"] == {"__agent_eval_redacted": True}
    assert persisted["extensions"]["credentials"] == {"__agent_eval_redacted": True}
    assert response.json()["extensions"]["agent_eval.privacy"] == {
        "redacted_fields": 4,
        "truncated_fields": 1,
    }


def test_trace_list_filters_and_timeline_are_project_scoped(
    trace_client: tuple[TestClient, Settings, Session],
) -> None:
    client, settings, _ = trace_client
    first = client.post(
        "/projects/project-1/traces", json=trace_payload(), headers=headers(settings)
    )
    assert first.status_code == 201
    second_payload = trace_payload()
    second_payload["trace_id"] = "trace-2"
    second_payload["case_id"] = "order-43"
    second_payload["status"] = "failed"
    for span in second_payload["spans"]:
        assert isinstance(span, dict)
        span["trace_id"] = "trace-2"
        span["status"] = "failed"
    second = client.post(
        "/projects/project-1/traces", json=second_payload, headers=headers(settings)
    )
    assert second.status_code == 201

    filtered = client.get(
        "/projects/project-1/traces?case_id=order-43&status=failed",
        headers=headers(settings),
    )
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1
    summary = filtered.json()[0]
    assert summary["trace_id"] == "trace-2"
    assert summary["case_id"] == "order-43"
    assert summary["status"] == "failed"
    assert summary["span_count"] == 3
    assert summary["started_at"] is not None
    assert summary["ended_at"] is not None

    timeline = client.get(
        "/projects/project-1/traces/trace-1/timeline", headers=headers(settings)
    )
    assert timeline.status_code == 200
    assert [span["span_id"] for span in timeline.json()["spans"]] == [
        "agent",
        "tool-call",
        "tool-result",
    ]
    assert timeline.json()["spans"][1]["depth"] == 1
    assert timeline.json()["spans"][2]["depth"] == 2

    forbidden = client.get(
        "/projects/project-2/traces?case_id=order-43", headers=headers(settings)
    )
    assert forbidden.status_code == 401
