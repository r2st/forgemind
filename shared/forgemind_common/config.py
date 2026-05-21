"""Centralized configuration for ForgeMind services.

All services read from environment variables. Provides a single Settings
object that wraps Pydantic for validation. Use `get_settings()` for a
cached singleton.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings for every ForgeMind service.

    Values are populated from environment variables. Service-specific
    overrides go into env files (`.env.<service>`).
    """

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Service identity
    # ------------------------------------------------------------------
    service_name: str = "forgemind-service"
    environment: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    postgres_dsn: str = Field(
        default="postgresql+asyncpg://postgres:postgres@postgres:5432/forgemind",
        description="PostgreSQL connection string. Override with POSTGRES_DSN env var in production."
    )
    redis_url: str = "redis://redis:6379/0"

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------
    nats_url: str = "nats://nats:4222"
    telemetry_subject: str = "forgemind.telemetry"
    incidents_subject: str = "forgemind.incidents"

    # ------------------------------------------------------------------
    # LLM gateway
    # ------------------------------------------------------------------
    llm_provider: str = Field(
        default="openai-compatible",
        description="Default LLM provider. Individual agents can override this from the admin panel.",
    )
    agent_config_path: str = Field(
        default=".runtime/agent_config.json",
        description="Shared JSON file used by the admin panel for per-agent LLM settings.",
    )

    # OpenAI-compatible defaults. The admin panel can override these
    # globally or per agent at runtime.
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        description="Default OpenAI-compatible base URL.",
    )
    openai_api_key: str = Field(
        default="",
        description="Default API key for direct OpenAI-compatible inference.",
    )
    openai_model_fast: str = "gpt-4o-mini"
    openai_model_powerful: str = "gpt-4o"
    openai_model_embedding: str = "text-embedding-3-small"
    openai_model_fallback: str = "gpt-4o-mini"

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------
    jwt_secret: str = Field(
        default="",
        description="JWT signing secret. MUST be set via JWT_SECRET env var."
    )
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------
    otel_exporter_endpoint: str = "http://otel-collector:4317"
    prometheus_metrics_path: str = "/metrics"

    # ------------------------------------------------------------------
    # Service URLs (used by API gateway / orchestrator)
    # ------------------------------------------------------------------
    anomaly_service_url: str = "http://anomaly-detection:8000"
    rca_service_url: str = "http://rca-service:8000"
    pdm_service_url: str = "http://predictive-maintenance:8000"
    chat_service_url: str = "http://chatops-service:8000"
    reporting_service_url: str = "http://reporting-service:8000"
    orchestrator_url: str = "http://ai-orchestrator:8000"
    notification_service_url: str = "http://notification-service:8000"
    workflow_engine_url: str = "http://workflow-engine:8000"

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, v: str, info) -> str:
        """Ensure JWT secret is set in production."""
        environment = info.data.get("environment", "dev")
        if environment == "prod" and not v:
            raise ValueError("JWT_SECRET must be set in production environment")
        if environment != "prod" and not v:
            import secrets
            # Generate a random secret for dev/staging if not provided
            return secrets.token_urlsafe(32)
        if len(v) < 16:
            raise ValueError("JWT_SECRET must be at least 16 characters")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings singleton."""
    return Settings()
