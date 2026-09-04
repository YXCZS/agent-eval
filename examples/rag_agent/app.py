"""A minimal RAG-shaped HTTP Agent with retrieval evidence."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

app = FastAPI(title="RAG Agent Example")

_DOCUMENTS = {
    "refund": "Refunds are available for delivered orders within 30 days.",
    "cancel": "Orders can be cancelled only while they are still processing.",
    "shipping": "Orders move from processing to shipped and then delivered.",
}


def _query(payload: dict[str, Any]) -> str:
    value = payload.get("input", "")
    if isinstance(value, dict):
        value = value.get("query", value.get("question", ""))
    return str(value).strip()


def _retrieve(query: str) -> tuple[str, str]:
    lowered = query.lower()
    for keyword, document in _DOCUMENTS.items():
        if keyword in lowered:
            return keyword, document
    return "shipping", _DOCUMENTS["shipping"]


@app.post("/run")
def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Return an answer, one retrieval tool call, and source-grounded context."""

    query = _query(payload)
    document_id, context = _retrieve(query)
    return {
        "output": {"answer": context, "citations": [document_id]},
        "tool_calls": [{"name": "retrieve_policy", "arguments": {"query": query}, "order": 0}],
        "usage": {"input_tokens": max(1, len(query.split())), "output_tokens": 12, "cost": 0.0},
        "trace": {
            "source": "rag-agent-example",
            "status": "completed",
            "retrieval_context": [{"document_id": document_id, "content": context}],
        },
    }
