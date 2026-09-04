"""Celery entry points for independently runnable evaluation cases."""

from __future__ import annotations

from typing import Any

from agent_eval_api.db import get_session_factory
from agent_eval_api.settings import get_settings

from .celery_app import celery_app
from .execution import execute_case


@celery_app.task(bind=True, name="agent_eval.execute_case", max_retries=None)  # type: ignore[misc]
def execute_case_task(task: Any, run_id: str, case_id: str) -> dict[str, str]:
    session = get_session_factory()()
    try:
        result = execute_case(session, get_settings(), run_id, case_id)
    finally:
        session.close()
    if result["status"] == "deferred":
        raise task.retry(countdown=float(result["countdown"]), max_retries=None)
    return result
