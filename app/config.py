"""Environment-driven configuration for SVRMON24."""

from __future__ import annotations

from functools import lru_cache

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


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
