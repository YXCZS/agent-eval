from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from agent_eval_api.auth import get_db, issue_dev_session
from agent_eval_api.db import AgentVersionRecord, Base, ProjectRecord
from agent_eval_api.main import create_app
from agent_eval_api.runner import HttpAgentRunResult, PromptRunResult, PromptUsage
from agent_eval_api.settings import Settings


@pytest.fixture
def agent_client() -> Iterator[tuple[TestClient, Settings, Session]]:
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
    session.add(ProjectRecord(id="project-1", name="one"))
    session.add(ProjectRecord(id="project-2", name="two"))
    session.commit()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    from agent_eval_api import auth

    app.dependency_overrides[auth.get_settings] = lambda: settings
    with TestClient(app) as client:
        yield client, settings, session
    session.close()


def headers(settings: Settings, project_id: str = "project-1") -> dict[str, str]:
    return {"X-Workspace-Session": issue_dev_session(project_id, settings)}


def test_register_prompt_agent_and_create_immutable_version(
    agent_client: tuple[TestClient, Settings, Session],
) -> None:
    client, settings, session = agent_client
    payload = {
        "name": "Support prompt",
        "agent_type": "prompt",
        "prompt_config": {
            "provider": "mock",
            "model": "mock-model",
            "endpoint": "https://llm.example.test/v1/chat/completions",
            "user_template": "Answer {question}",
            "variable_names": ["question"],
        },
    }

    created = client.post("/projects/project-1/agents", json=payload, headers=headers(settings))

    assert created.status_code == 201
    agent = created.json()
    assert agent["agent_type"] == "prompt"
    assert agent["current_version_id"]

    versions = client.get(
        f"/projects/project-1/agents/{agent['id']}/versions", headers=headers(settings)
    )
    assert versions.status_code == 200
    assert len(versions.json()) == 1

    changed = {**payload, "prompt_config": {**payload["prompt_config"], "temperature": 0.7}}
    new_version = client.post(
        f"/projects/project-1/agents/{agent['id']}/versions",
        json=changed,
        headers=headers(settings),
    )
    assert new_version.status_code == 201
    assert new_version.json()["version"] == 2

    stored = session.scalars(select(AgentVersionRecord).order_by(AgentVersionRecord.version)).all()
    assert stored[0].prompt_config["temperature"] == 0.0
    assert stored[1].prompt_config["temperature"] == 0.7


def test_agent_type_requires_matching_runner_or_http_configuration(
    agent_client: tuple[TestClient, Settings, Session],
) -> None:
    client, settings, _ = agent_client

    response = client.post(
        "/projects/project-1/agents",
        json={"name": "Broken", "agent_type": "tool", "prompt_config": {}},
        headers=headers(settings),
    )

    assert response.status_code == 422


def test_version_can_be_disabled_but_configuration_cannot_be_mutated(
    agent_client: tuple[TestClient, Settings, Session],
) -> None:
    client, settings, session = agent_client
    payload = {
        "name": "HTTP agent",
        "agent_type": "tool",
        "endpoint_config": {"url": "https://agent.example.test/run"},
    }
    created = client.post("/projects/project-1/agents", json=payload, headers=headers(settings))
    agent_id = created.json()["id"]
    version_id = created.json()["current_version_id"]

    disabled = client.patch(
        f"/projects/project-1/agents/{agent_id}/versions/{version_id}/enabled?enabled=false",
        headers=headers(settings),
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    record = session.get(AgentVersionRecord, version_id)
    assert record is not None
    record.label = "should fail"
    with pytest.raises(ValueError, match="immutable"):
        session.commit()


def test_agent_routes_do_not_cross_project_boundary(
    agent_client: tuple[TestClient, Settings, Session],
) -> None:
    client, settings, _ = agent_client

    response = client.get("/projects/project-2/agents", headers=headers(settings, "project-1"))

    assert response.status_code == 401


def prompt_config_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider": "mock",
        "model": "mock-model",
        "endpoint": "https://llm.example.test/v1/chat/completions",
        "user_template": "Answer {question}",
        "variable_names": ["question"],
    }
    payload.update(overrides)
    return payload


def endpoint_config_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"url": "https://agent.example.test/run"}
    payload.update(overrides)
    return payload


def test_connection_test_runs_prompt_runner_and_returns_rendered_prompt(
    agent_client: tuple[TestClient, Settings, Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, settings, _ = agent_client

    async def fake_run_prompt(*args: Any, **kwargs: Any) -> PromptRunResult:
        assert args[1] == {"question": "Where is order 42?"}
        return PromptRunResult(
            output={"answer": "shipped"},
            rendered_prompt="Answer Where is order 42?",
            variables_snapshot={"question": "Where is order 42?"},
            messages=[{"role": "user", "content": "Answer Where is order 42?"}],
            usage=PromptUsage(input_tokens=12, output_tokens=8, total_tokens=20, cost=0.01),
            raw_response={"choices": []},
        )

    monkeypatch.setattr("agent_eval_api.agents.run_prompt", fake_run_prompt)
    response = client.post(
        "/projects/project-1/agents/connection-test",
        json={
            "agent_type": "prompt",
            "prompt_config": prompt_config_payload(),
            "variables": {"question": "Where is order 42?"},
        },
        headers=headers(settings),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["rendered_prompt"] == "Answer Where is order 42?"
    assert body["output"] == {"answer": "shipped"}
    assert body["usage"]["total_tokens"] == 20


def test_connection_test_runs_http_adapter_and_returns_output(
    agent_client: tuple[TestClient, Settings, Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, settings, _ = agent_client

    async def fake_run_http_agent(*args: Any, **kwargs: Any) -> HttpAgentRunResult:
        assert args[1] == {"question": "Where is order 42?"}
        assert kwargs["run_id"] == "connection-test"
        assert kwargs["case_id"] == "connection-test"
        return HttpAgentRunResult(
            output="shipped",
            tool_calls=[],
            usage={"input_tokens": 4, "output_tokens": 3},
            trace=None,
            raw_response={"output": "shipped"},
            request_metadata={"run_id": "connection-test", "case_id": "connection-test"},
        )

    monkeypatch.setattr("agent_eval_api.agents.run_http_agent", fake_run_http_agent)
    response = client.post(
        "/projects/project-1/agents/connection-test",
        json={
            "agent_type": "tool",
            "endpoint_config": endpoint_config_payload(),
            "input": {"question": "Where is order 42?"},
        },
        headers=headers(settings),
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["output"] == "shipped"


@pytest.mark.parametrize(
    ("agent_type", "error_type", "message"),
    [("prompt", "timeout", "LLM request timed out"), ("tool", "protocol_error", "missing output")],
)
def test_connection_test_returns_classified_runner_errors(
    agent_client: tuple[TestClient, Settings, Session],
    monkeypatch: pytest.MonkeyPatch,
    agent_type: str,
    error_type: str,
    message: str,
) -> None:
    client, settings, _ = agent_client

    if agent_type == "prompt":
        async def fail_prompt(*args: Any, **kwargs: Any) -> PromptRunResult:
            from agent_eval_api.runner import PromptRunnerError

            raise PromptRunnerError(message, error_type=error_type)

        monkeypatch.setattr("agent_eval_api.agents.run_prompt", fail_prompt)
        payload = {"agent_type": agent_type, "prompt_config": prompt_config_payload()}
    else:
        async def fail_http(*args: Any, **kwargs: Any) -> HttpAgentRunResult:
            from agent_eval_api.runner import AgentAdapterError

            raise AgentAdapterError(error_type, message)

        monkeypatch.setattr("agent_eval_api.agents.run_http_agent", fail_http)
        payload = {"agent_type": agent_type, "endpoint_config": endpoint_config_payload()}

    response = client.post(
        "/projects/project-1/agents/connection-test",
        json=payload,
        headers=headers(settings),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["error_type"] == error_type
    assert message in body["message"]


def test_connection_test_requires_project_access(
    agent_client: tuple[TestClient, Settings, Session],
) -> None:
    client, _, _ = agent_client
    response = client.post(
        "/projects/project-1/agents/connection-test",
        json={"agent_type": "prompt", "prompt_config": prompt_config_payload()},
    )

    assert response.status_code == 401
