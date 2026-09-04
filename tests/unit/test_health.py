from fastapi.testclient import TestClient

from agent_eval_api.main import create_app


def test_health_reports_status_without_secrets(monkeypatch: object) -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "development"}
    assert "api_key" not in response.text.lower()

