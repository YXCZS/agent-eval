from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from agent_eval_api import auth
from agent_eval_api.auth import get_db, issue_dev_session
from agent_eval_api.db import Base, EvaluatorVersionRecord, ProjectRecord
from agent_eval_api.main import create_app
from agent_eval_api.settings import Settings


@pytest.fixture
def evaluator_client() -> Iterator[tuple[TestClient, Settings, Session]]:
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


def evaluator_payload() -> dict[str, object]:
    return {
        "name": "task_success",
        "version": "1.0.0",
        "evaluator_type": "deterministic",
        "requires": ["expected_state"],
        "supported_agent_types": ["tool"],
        "score_min": 0,
        "score_max": 1,
        "direction": "higher_is_better",
        "default_threshold": 1,
        "config": {"comparison": "subset"},
    }


def test_register_and_disable_project_scoped_evaluator_version(
    evaluator_client: tuple[TestClient, Settings, Session],
) -> None:
    client, settings, session = evaluator_client
    created = client.post(
        "/projects/project-1/evaluators",
        json=evaluator_payload(),
        headers=headers(settings),
    )

    assert created.status_code == 201
    evaluator = created.json()
    assert evaluator["name"] == "task_success"
    assert evaluator["requires"] == ["expected_state"]
    assert evaluator["enabled"] is True
    record = session.get(EvaluatorVersionRecord, evaluator["id"])
    assert record is not None
    assert record.project_id == "project-1"

    disabled = client.patch(
        f"/projects/project-1/evaluators/{evaluator['id']}/enabled?enabled=false",
        headers=headers(settings),
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert client.get(
        "/projects/project-1/evaluators?enabled=true", headers=headers(settings)
    ).json() == []


def test_evaluator_registration_validates_contract_and_project_boundaries(
    evaluator_client: tuple[TestClient, Settings, Session],
) -> None:
    client, settings, _ = evaluator_client
    invalid = client.post(
        "/projects/project-1/evaluators",
        json={**evaluator_payload(), "score_min": 1, "score_max": 1},
        headers=headers(settings),
    )
    assert invalid.status_code == 422

    created = client.post(
        "/projects/project-1/evaluators",
        json=evaluator_payload(),
        headers=headers(settings),
    )
    assert created.status_code == 201
    duplicate = client.post(
        "/projects/project-1/evaluators",
        json=evaluator_payload(),
        headers=headers(settings),
    )
    assert duplicate.status_code == 409

    isolated = client.get(
        f"/projects/project-2/evaluators/{created.json()['id']}",
        headers=headers(settings, "project-2"),
    )
    assert isolated.status_code == 404


def test_future_adapter_capabilities_are_read_only_and_explicit(
    evaluator_client: tuple[TestClient, Settings, Session],
) -> None:
    client, _, _ = evaluator_client
    response = client.get("/adapter-capabilities")

    assert response.status_code == 200
    capabilities = {item["adapter_id"]: item for item in response.json()}
    assert capabilities["giskard-safety"]["lifecycle"] == "planned"
    assert capabilities["webarena"]["execution_mode"] == "external_environment"
    assert capabilities["webarena"]["requires_external_environment"] is True
