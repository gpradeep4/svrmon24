"""Environment-driven configuration for SVRMON24."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="SVRMON24", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8200, alias="APP_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    basic_auth_username: str = Field(default="change-me", alias="BASIC_AUTH_USERNAME")
    basic_auth_password: str = Field(default="change-me", alias="BASIC_AUTH_PASSWORD")

    mongodb_uri: str = Field(default="mongodb://localhost:27017", alias="MONGODB_URI")
    mongodb_db: str = Field(default="svrmon24", alias="MONGODB_DB")
    mongodb_connect_timeout_ms: int = Field(default=3000, alias="MONGODB_CONNECT_TIMEOUT_MS")
    mongodb_server_selection_timeout_ms: int = Field(
        default=3000, alias="MONGODB_SERVER_SELECTION_TIMEOUT_MS"
    )

    # Local Ollama (Phase 7 AI analysis). Prefer OLLAMA_URL; OLLAMA_HOST is accepted as alias.
    ollama_url: str = Field(default="http://localhost:11434", alias="OLLAMA_URL")
    ollama_model: str = Field(default="llama3.2:3b", alias="OLLAMA_MODEL")
    ollama_timeout_seconds: float = Field(default=60.0, alias="OLLAMA_TIMEOUT_SECONDS")

    def model_post_init(self, __context: Any) -> None:  # noqa: ANN401
        # Allow OLLAMA_HOST when OLLAMA_URL was left at default / unset in env loading
        import os

        host = os.getenv("OLLAMA_HOST", "").strip()
        url_env = os.getenv("OLLAMA_URL", "").strip()
        if host and not url_env:
            object.__setattr__(self, "ollama_url", host.rstrip("/"))


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
