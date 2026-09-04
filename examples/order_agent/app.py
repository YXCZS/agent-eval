"""A deterministic order-support Tool Agent for evaluation demonstrations."""

from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI, Request

app = FastAPI(title="Order Agent Example")

_ORDERS: dict[str, dict[str, str]] = {
    "ORD-1001": {"status": "processing", "item": "wireless keyboard"},
    "ORD-1002": {"status": "shipped", "item": "desk lamp"},
    "ORD-1003": {"status": "delivered", "item": "monitor stand"},
}


def _request(payload: dict[str, Any]) -> tuple[str, str, str | None]:
    value = payload.get("input", "")
    if isinstance(value, dict):
        action = str(value.get("action", "query")).lower()
        order_id = value.get("order_id")
        return action, str(value.get("message", "")), str(order_id) if order_id else None
    text = str(value)
    lowered = text.lower()
    action = "refund" if "refund" in lowered else "cancel" if "cancel" in lowered else "query"
    match = re.search(r"\bORD-\d+\b", text, re.IGNORECASE)
    return action, text, match.group(0).upper() if match else None


def _response(output: dict[str, Any], tools: list[dict[str, Any]], text: str) -> dict[str, Any]:
    return {
        "output": output,
        "tool_calls": tools,
        "usage": {"input_tokens": max(1, len(text.split())), "output_tokens": 14, "cost": 0.0},
    }


@app.post("/run")
def run(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    """Process order query, cancellation, and refund paths without side effects."""

    action, text, order_id = _request(payload)
    if order_id is None:
        return _response(
            {"status": "needs_order_id", "message": "Please provide an order ID such as ORD-1001."},
            [],
            text,
        )
    lookup = {"name": "lookup_order", "arguments": {"order_id": order_id}, "order": 0}
    order = _ORDERS.get(order_id)
    if order is None:
        return _response(
            {"status": "not_found", "order_id": order_id, "message": "Order was not found."},
            [lookup],
            text,
        )
    status = order["status"]
    if action == "cancel":
        if status != "processing":
            if request.query_params.get("variant") == "regression":
                return _response(
                    {
                        "status": "cancelled",
                        "order_id": order_id,
                        "message": "Order cancellation accepted.",
                    },
                    [
                        lookup,
                        {
                            "name": "cancel_order",
                            "arguments": {"order_id": order_id},
                            "order": 1,
                        },
                    ],
                    text,
                )
            return _response(
                {
                    "status": "blocked",
                    "order_id": order_id,
                    "message": "Cancellation is not allowed after an order has shipped.",
                },
                [lookup],
                text,
            )
        return _response(
            {
                "status": "cancelled",
                "order_id": order_id,
                "message": "Order cancellation accepted.",
            },
            [lookup, {"name": "cancel_order", "arguments": {"order_id": order_id}, "order": 1}],
            text,
        )
    if action == "refund":
        if status != "delivered":
            return _response(
                {
                    "status": "blocked",
                    "order_id": order_id,
                    "message": "A refund can be requested only after delivery.",
                },
                [lookup],
                text,
            )
        return _response(
            {
                "status": "refund_requested",
                "order_id": order_id,
                "message": "Refund request accepted.",
            },
            [lookup, {"name": "request_refund", "arguments": {"order_id": order_id}, "order": 1}],
            text,
        )
    return _response(
        {"status": status, "order_id": order_id, "item": order["item"]},
        [lookup],
        text,
    )
