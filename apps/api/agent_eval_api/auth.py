"""Small, project-scoped authentication layer for the first self-hosted release."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_eval_api.db import ApiKeyRecord, get_session_factory
from agent_eval_api.settings import Settings, get_settings


@dataclass(frozen=True)
class AuthContext:
    project_id: str
    principal_type: Literal["browser", "agent", "ci"]
    credential_id: str | None = None


def hash_project_key(raw_key: str, salt: str) -> str:
    """Hash a project key with a deployment-specific salt."""

    return hmac.new(salt.encode(), raw_key.encode(), hashlib.sha256).hexdigest()


def issue_project_key(project_id: str, settings: Settings) -> tuple[str, ApiKeyRecord]:
    """Create a key record and return the plaintext only to the caller once."""

    raw_secret = secrets.token_urlsafe(32)
    raw_key = f"aek_{project_id}_{raw_secret}"
    record = ApiKeyRecord(
        project_id=project_id,
        name="generated",
        key_hash=hash_project_key(raw_key, settings.api_key_salt.get_secret_value()),
        key_prefix=raw_key[:16],
    )
    return raw_key, record


def issue_dev_session(project_id: str, settings: Settings) -> str:
    """Issue the project-bound browser token used by the single-workspace dev login."""

    secret = settings.workspace_session_secret.get_secret_value()
    return f"dev:{project_id}:{secret}"


def get_db() -> Iterator[Session]:
    """Yield one request-scoped database session and always return it to the pool."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def require_project_access(
    project_id: str,
    x_project_key: str | None = Header(default=None),
    x_workspace_session: str | None = Header(default=None),
    db: Session = Depends(get_db),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AuthContext:
    if x_project_key:
        key_hash = hash_project_key(x_project_key, settings.api_key_salt.get_secret_value())
        record = db.scalar(
            select(ApiKeyRecord).where(
                ApiKeyRecord.project_id == project_id,
                ApiKeyRecord.key_hash == key_hash,
                ApiKeyRecord.active.is_(True),
            )
        )
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid project key"
            )
        return AuthContext(project_id=project_id, principal_type="agent", credential_id=record.id)

    if x_workspace_session and hmac.compare_digest(
        x_workspace_session, issue_dev_session(project_id, settings)
    ):
        return AuthContext(project_id=project_id, principal_type="browser")

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
