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

    # HTTP Basic — coexistence / migration only. Production-oriented default: off.
    # Must never bypass future tenant-scoped authorization once isolation lands.
    basic_auth_enabled: bool = Field(default=False, alias="BASIC_AUTH_ENABLED")
    basic_auth_username: str = Field(default="change-me", alias="BASIC_AUTH_USERNAME")
    basic_auth_password: str = Field(default="change-me", alias="BASIC_AUTH_PASSWORD")

    # Provider-neutral OIDC (Authorization Code + PKCE). Entra ID / Keycloak compatible.
    oidc_enabled: bool = Field(default=False, alias="OIDC_ENABLED")
    oidc_issuer: str = Field(default="", alias="OIDC_ISSUER")
    oidc_client_id: str = Field(default="", alias="OIDC_CLIENT_ID")
    oidc_client_secret: str = Field(default="", alias="OIDC_CLIENT_SECRET")
    oidc_redirect_uri: str = Field(
        default="http://localhost:8200/auth/callback",
        alias="OIDC_REDIRECT_URI",
    )
    oidc_scopes: str = Field(default="openid profile email", alias="OIDC_SCOPES")

    # Signed server session cookie (Starlette SessionMiddleware).
    session_secret: str = Field(default="change-me-session-secret", alias="SESSION_SECRET")
    session_cookie_name: str = Field(default="svrmon24_session", alias="SESSION_COOKIE_NAME")
    session_max_age_seconds: int = Field(default=28800, alias="SESSION_MAX_AGE_SECONDS")
    session_https_only: bool = Field(default=False, alias="SESSION_HTTPS_ONLY")
    session_same_site: str = Field(default="lax", alias="SESSION_SAME_SITE")

    # Monolith: serve frontend from Uvicorn (default). Split deploy: SERVE_STATIC=false.
    serve_static: bool = Field(default=True, alias="SERVE_STATIC")
    # Comma-separated browser origins for split FE (cross-origin). Same-origin nginx proxy preferred.
    cors_origins: str = Field(default="", alias="CORS_ORIGINS")

    mongodb_uri: str = Field(default="mongodb://localhost:27017", alias="MONGODB_URI")
    # CMDB database name (slice 2K cutover). Default ``svrmon-cmdb``.
    # Existing deploys still on the pre-cutover name should set ``MONGODB_DB=svrmon24``
    # (or copy/rename data into ``svrmon-cmdb``) until they finish ops migration.
    mongodb_db: str = Field(default="svrmon-cmdb", alias="MONGODB_DB")
    # Optional explicit CMDB database override. When unset/blank, uses ``mongodb_db``.
    mongodb_cmdb_db: str = Field(default="", alias="MONGODB_CMDB_DB")
    # Dedicated ITSM database (separate from CMDB). Default ``svrmon-itsm``.
    mongodb_itsm_db: str = Field(default="svrmon-itsm", alias="MONGODB_ITSM_DB")
    mongodb_connect_timeout_ms: int = Field(default=3000, alias="MONGODB_CONNECT_TIMEOUT_MS")
    mongodb_server_selection_timeout_ms: int = Field(
        default=3000, alias="MONGODB_SERVER_SELECTION_TIMEOUT_MS"
    )

    @property
    def cmdb_database_name(self) -> str:
        """Resolved CMDB DB: ``MONGODB_CMDB_DB`` or ``MONGODB_DB`` (default ``svrmon-cmdb``)."""
        explicit = (self.mongodb_cmdb_db or "").strip()
        if explicit:
            return explicit
        return (self.mongodb_db or "").strip() or "svrmon-cmdb"

    @property
    def itsm_database_name(self) -> str:
        """Resolved ITSM DB name (default ``svrmon-itsm``)."""
        return (self.mongodb_itsm_db or "").strip() or "svrmon-itsm"

    # Local Ollama (Phase 7 + Master Phase 12 entitlements). Prefer OLLAMA_URL;
    # OLLAMA_HOST is accepted as alias. Disabled unless explicitly enabled —
    # default local AI path; rule-based fallback always remains available.
    ollama_enabled: bool = Field(default=False, alias="OLLAMA_ENABLED")
    ollama_url: str = Field(default="http://localhost:11434", alias="OLLAMA_URL")
    ollama_model: str = Field(default="llama3.2:3b", alias="OLLAMA_MODEL")
    ollama_timeout_seconds: float = Field(default=60.0, alias="OLLAMA_TIMEOUT_SECONDS")

    # Optional OpenAI-compatible cloud suggestion provider (assist only).
    # Disabled by default. Requires platform flag + tenant opt-in + API key via
    # env/secret ref (never store the key in Mongo). Failures fall back to
    # Ollama (if enabled) then rule-based fallback. Never auto-transitions.
    ai_cloud_suggestions_enabled: bool = Field(
        default=False, alias="AI_CLOUD_SUGGESTIONS_ENABLED"
    )
    ai_cloud_base_url: str = Field(
        default="https://api.openai.com/v1", alias="AI_CLOUD_BASE_URL"
    )
    ai_cloud_model: str = Field(default="gpt-4o-mini", alias="AI_CLOUD_MODEL")
    ai_cloud_api_key_env_ref: str = Field(
        default="AI_CLOUD_API_KEY", alias="AI_CLOUD_API_KEY_ENV_REF"
    )
    ai_cloud_timeout_seconds: float = Field(
        default=60.0, alias="AI_CLOUD_TIMEOUT_SECONDS"
    )

    # ITSM in-process job runner (N2). Off by default — enable for SLA sweeper /
    # delivery retries / report-schedule hook without opening the UI.
    itsm_job_runner_enabled: bool = Field(
        default=False, alias="ITSM_JOB_RUNNER_ENABLED"
    )
    itsm_job_runner_interval_seconds: int = Field(
        default=60, alias="ITSM_JOB_RUNNER_INTERVAL_SECONDS"
    )
    itsm_job_runner_lease_seconds: int = Field(
        default=55, alias="ITSM_JOB_RUNNER_LEASE_SECONDS"
    )
    itsm_delivery_max_attempts: int = Field(
        default=5, alias="ITSM_DELIVERY_MAX_ATTEMPTS"
    )

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
