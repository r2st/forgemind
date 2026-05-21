"""Centralized configuration for ForgeMind services.

All services read from environment variables. Provides a single Settings
object that wraps Pydantic for validation. Use `get_settings()` for a
cached singleton.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
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
    postgres_dsn: str = (
        "postgresql+asyncpg://forgemind:forgemind@postgres:5432/forgemind"
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
    llm_provider: Literal["truefoundry", "openai", "openai-compatible", "disabled"] = Field(
        default="truefoundry",
        description="Default LLM provider. Individual agents can override this at runtime.",
    )
    agent_config_path: str = Field(
        default=".runtime/agent_config.json",
        description="Shared JSON file used by the admin panel for per-agent LLM settings.",
    )

    # TrueFoundry AI Gateway. Optional: select `openai` or
    # `openai-compatible` through LLM_PROVIDER or the admin panel to run
    # without TrueFoundry.
    tfy_gateway_base_url: str = Field(
        default="https://gateway.truefoundry.ai",
        description="TrueFoundry AI Gateway base URL (OpenAI-compatible).",
    )
    tfy_gateway_api_key: str = Field(
        default="",
        description="API key for the TrueFoundry AI Gateway.",
    )
    tfy_workspace: str = Field(
        default="forgemind",
        description="TrueFoundry workspace name used for deploys.",
    )
    tfy_control_plane_url: str = Field(
        default="https://app.truefoundry.com",
        description="TrueFoundry control-plane URL (used for MCP server discovery).",
    )
    tfy_mcp_namespace: str = Field(
        default="truefoundry",
        description="Tenant/namespace under which MCP servers are registered.",
    )
    tfy_mcp_enabled_servers: list[str] = Field(
        default_factory=lambda: ["common-tools", "deepwiki0"],
        description="Which MCP servers to bind into Hermes tool registries.",
    )
    tfy_mcp_enabled: bool = Field(
        default=False,
        description="Enable TrueFoundry MCP tools. Disabled by default so TrueFoundry is optional.",
    )

    # Logical model tiers — the gateway maps these to concrete providers.
    tfy_model_fast: str = "openai-main/gpt-4o-mini"
    tfy_model_powerful: str = "openai-main/gpt-4o"
    tfy_model_embedding: str = "openai-main/text-embedding-3-small"
    tfy_model_fallback: str = "ollama-local/llama3.1:8b"

    # Direct OpenAI / OpenAI-compatible defaults.
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        description="OpenAI-compatible base URL used when LLM_PROVIDER=openai or openai-compatible.",
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
    jwt_secret: str = "change-me-in-prod"
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings singleton."""
    return Settings()
