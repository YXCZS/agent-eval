from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from agent_eval_api.auth import get_db, issue_dev_session, issue_project_key
from agent_eval_api.db import Base, ProjectRecord
from agent_eval_api.main import create_app
from agent_eval_api.settings import Settings


@pytest.fixture
def auth_client() -> Iterator[tuple[TestClient, Settings, Session]]:
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
        [
            ProjectRecord(id="project-1", name="one"),
            ProjectRecord(id="project-2", name="two"),
        ]
    )
    session.commit()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    from agent_eval_api import auth

    app.dependency_overrides[auth.get_settings] = lambda: settings
    with TestClient(app) as client:
        yield client, settings, session
    session.close()


def test_project_key_is_scoped_and_plaintext_is_not_persisted(
    auth_client: tuple[TestClient, Settings, Session],
) -> None:
    client, settings, session = auth_client
    raw_key, record = issue_project_key("project-1", settings)
    session.add(record)
    session.commit()

    response = client.get("/projects/project-1/access-check", headers={"X-Project-Key": raw_key})
    assert response.status_code == 200
    assert response.json() == {"project_id": "project-1", "principal_type": "agent"}
    assert raw_key not in record.key_hash

    cross_project = client.get(
        "/projects/project-2/access-check", headers={"X-Project-Key": raw_key}
    )
    assert cross_project.status_code == 401


def test_browser_session_is_bound_to_project(
    auth_client: tuple[TestClient, Settings, Session],
) -> None:
    client, settings, _ = auth_client
    session_token = issue_dev_session("project-1", settings)

    response = client.get(
        "/projects/project-1/access-check", headers={"X-Workspace-Session": session_token}
    )
    assert response.status_code == 200
    assert response.json()["principal_type"] == "browser"

    cross_project = client.get(
        "/projects/project-2/access-check", headers={"X-Workspace-Session": session_token}
    )
    assert cross_project.status_code == 401


def test_missing_credentials_are_rejected(
    auth_client: tuple[TestClient, Settings, Session],
) -> None:
    client, _, _ = auth_client

    response = client.get("/projects/project-1/access-check")

    assert response.status_code == 401
