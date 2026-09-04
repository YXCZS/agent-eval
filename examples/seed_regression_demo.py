"""Seed a complete version-comparison demo through the public HTTP API."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, cast

import httpx

EXAMPLES_DIR = Path(__file__).parent
TERMINAL_RUN_STATUSES = {"completed", "partial", "failed", "cancelled"}


def load_cases(name: str) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], json.loads((EXAMPLES_DIR / name).read_text(encoding="utf-8")))


def post(client: httpx.Client, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(path, json=payload)
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


def wait_for_run(client: httpx.Client, path: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = client.get(path)
        response.raise_for_status()
        run = cast(dict[str, Any], response.json())
        if run["status"] in TERMINAL_RUN_STATUSES:
            return run
        time.sleep(1)
    raise TimeoutError(f"run did not complete within {timeout_seconds} seconds")


def seed_demo(
    api_url: str,
    workspace_session: str,
    project_id: str,
    agent_url: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Create dataset v1/v2, evaluator versions, and baseline/candidate runs."""

    headers = {"X-Workspace-Session": workspace_session}
    base_path = f"/projects/{project_id}"
    with httpx.Client(base_url=api_url.rstrip("/"), headers=headers, timeout=20) as client:
        dataset = post(
            client,
            f"{base_path}/datasets",
            {
                "name": "Order policy regression demo",
                "description": "Immutable fixture for the baseline and intentional v2 regression.",
                "tags": ["example", "regression"],
                "cases": load_cases("regression_dataset_v1.json"),
                "metadata": {"fixture": "order-policy", "fixture_version": 1},
            },
        )
        dataset_v2 = post(
            client,
            f"{base_path}/datasets/{dataset['id']}/versions",
            {
                "cases": load_cases("regression_dataset_v2.json"),
                "metadata": {"fixture": "order-policy", "fixture_version": 2},
            },
        )
        baseline = post(
            client,
            f"{base_path}/agents",
            {
                "name": "Order support demo",
                "agent_type": "tool",
                "description": "Baseline version for the order-policy regression demo.",
                "endpoint_config": {"url": f"{agent_url}?variant=baseline"},
            },
        )
        candidate = post(
            client,
            f"{base_path}/agents/{baseline['id']}/versions",
            {
                "name": "Order support demo",
                "agent_type": "tool",
                "label": "Order support demo v2 (intentional regression)",
                "endpoint_config": {"url": f"{agent_url}?variant=regression"},
            },
        )
        task_success = post(
            client,
            f"{base_path}/evaluators",
            {
                "name": "task_success",
                "version": "1.0.0",
                "evaluator_type": "deterministic",
                "requires": ["expected_state"],
                "supported_agent_types": ["tool"],
                "score_min": 0,
                "score_max": 1,
                "direction": "higher_is_better",
                "default_threshold": 1,
            },
        )
        tool_correctness = post(
            client,
            f"{base_path}/evaluators",
            {
                "name": "tool_correctness",
                "version": "1.0.0",
                "evaluator_type": "deterministic",
                "requires": ["expected_tools"],
                "supported_agent_types": ["tool"],
                "score_min": 0,
                "score_max": 1,
                "direction": "higher_is_better",
                "default_threshold": 1,
            },
        )
        evaluator_ids = [task_success["id"], tool_correctness["id"]]
        run_payload = {
            "dataset_version_id": dataset_v2["id"],
            "evaluator_version_ids": evaluator_ids,
        }
        baseline_run = post(
            client,
            f"{base_path}/runs",
            {**run_payload, "agent_version_id": baseline["current_version_id"]},
        )
        candidate_run = post(
            client,
            f"{base_path}/runs",
            {**run_payload, "agent_version_id": candidate["id"]},
        )
        baseline_result = wait_for_run(
            client, f"{base_path}/runs/{baseline_run['id']}", timeout_seconds
        )
        candidate_result = wait_for_run(
            client, f"{base_path}/runs/{candidate_run['id']}", timeout_seconds
        )
        comparison = post(
            client,
            f"{base_path}/comparisons",
            {"run_ids": [baseline_run["id"], candidate_run["id"]]},
        )
        gate = post(
            client,
            f"{base_path}/runs/{candidate_run['id']}/regression-gate",
            {
                "rules": [
                    {"metric_name": "task_success", "minimum": 1},
                    {"metric_name": "tool_correctness", "require_all_passed": True},
                ]
            },
        )
    return {
        "dataset_id": dataset["id"],
        "dataset_version_id": dataset_v2["id"],
        "baseline_run": baseline_result,
        "candidate_run": candidate_result,
        "comparison": comparison,
        "gate": gate,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--workspace-session", required=True)
    parser.add_argument("--project-id", default="project-1")
    parser.add_argument("--agent-url", default="http://order-agent:8103/run")
    parser.add_argument("--timeout-seconds", type=int, default=90)
    args = parser.parse_args()
    result = seed_demo(
        args.api_url,
        args.workspace_session,
        args.project_id,
        args.agent_url,
        args.timeout_seconds,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
