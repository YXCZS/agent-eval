"""A tiny HTTP Prompt Agent compatible with the workbench /run protocol."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

app = FastAPI(title="Prompt Agent Example")


def _question(payload: dict[str, Any]) -> str:
    value = payload.get("input", "")
    if isinstance(value, dict):
        value = value.get("question", value.get("text", ""))
    return str(value).strip()


@app.post("/run")
def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a predictable answer so Prompt metrics can be demonstrated offline."""

    question = _question(payload)
    answer = "Please provide a question." if not question else f"Support answer: {question}"
    return {
        "output": {"answer": answer},
        "tool_calls": [],
        "usage": {"input_tokens": max(1, len(question.split())), "output_tokens": 5, "cost": 0.0},
    }
