"""Idempotent bootstrap for the single-workspace local Compose environment."""

from agent_eval_api.db import ProjectRecord, get_session_factory
from agent_eval_api.settings import get_settings


def ensure_local_project() -> None:
    session = get_session_factory()()
    try:
        if session.get(ProjectRecord, "project-1") is None:
            session.add(ProjectRecord(id="project-1", name="Local project"))
            session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    get_settings()
    ensure_local_project()
