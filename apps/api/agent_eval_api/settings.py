from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Secrets are never serialized into API payloads."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite:///./agent_eval.db"
    redis_url: str = "redis://localhost:6379/0"
    api_key_salt: SecretStr = SecretStr("development-only-change-me")
    workspace_session_secret: SecretStr = SecretStr("development-session-secret")
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    embedding_api_key: SecretStr | None = None
    embedding_base_url: str | None = None
    worker_max_concurrency: int = Field(default=8, ge=1, le=256)
    worker_admission_retry_seconds: float = Field(default=0.5, gt=0.0, le=30.0)
    trace_max_field_bytes: int = Field(default=16_384, ge=64, le=10_485_760)
    trace_redaction_field_names: list[str] = Field(
        default_factory=lambda: [
            "api_key",
            "authorization",
            "token",
            "secret",
            "password",
            "credential",
            "cookie",
            "access_key",
        ]
    )

    @field_validator("database_url", "redis_url")
    @classmethod
    def must_have_scheme(cls, value: str) -> str:
        if "://" not in value:
            raise ValueError("must be a URL")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
