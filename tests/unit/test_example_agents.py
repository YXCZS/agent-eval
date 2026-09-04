from examples.order_agent.app import app as order_app
from examples.prompt_agent.app import app as prompt_app
from examples.rag_agent.app import app as rag_app
from fastapi.testclient import TestClient


def test_prompt_agent_returns_protocol_output() -> None:
    response = TestClient(prompt_app).post(
        "/run", json={"input": {"question": "Where is my order?"}}
    )

    assert response.status_code == 200
    assert response.json()["output"]["answer"] == "Support answer: Where is my order?"


def test_rag_agent_returns_retrieval_evidence() -> None:
    response = TestClient(rag_app).post("/run", json={"input": "What is the refund policy?"})

    assert response.status_code == 200
    assert response.json()["tool_calls"][0]["name"] == "retrieve_policy"
    assert response.json()["output"]["citations"] == ["refund"]


def test_order_agent_covers_policy_and_order_id_paths() -> None:
    client = TestClient(order_app)

    missing = client.post("/run", json={"input": "Cancel my order"}).json()
    prohibited = client.post(
        "/run", json={"input": {"action": "cancel", "order_id": "ORD-1002"}}
    ).json()
    refund = client.post(
        "/run", json={"input": {"action": "refund", "order_id": "ORD-1003"}}
    ).json()
    regression = client.post(
        "/run?variant=regression",
        json={"input": {"action": "cancel", "order_id": "ORD-1002"}},
    ).json()

    assert missing["output"]["status"] == "needs_order_id"
    assert prohibited["output"]["status"] == "blocked"
    assert [item["name"] for item in prohibited["tool_calls"]] == ["lookup_order"]
    assert refund["output"]["status"] == "refund_requested"
    assert [item["name"] for item in refund["tool_calls"]] == ["lookup_order", "request_refund"]
    assert regression["output"]["status"] == "cancelled"
