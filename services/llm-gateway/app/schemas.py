"""Pydantic schemas for LLM Gateway API."""

from datetime import datetime
from enum import Enum
from typing import Any
from urllib.parse import urlparse
import ipaddress
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProviderKind(str, Enum):
    """Type of LLM provider."""
    CLOUD = "cloud"
    SELF_HOSTED = "self_hosted"


class ProviderType(str, Enum):
    """Specific provider implementation."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    AZURE_OPENAI = "azure_openai"
    BEDROCK = "bedrock"
    OPENROUTER = "openrouter"
    GROQ = "groq"
    TOGETHER = "together"
    FIREWORKS = "fireworks"
    DEEPINFRA = "deepinfra"
    REPLICATE = "replicate"
    OLLAMA = "ollama"
    VLLM = "vllm"
    TGI = "tgi"
    LLAMACPP = "llamacpp"
    SGLANG = "sglang"
    LOCALAI = "localai"
    CUSTOM_OPENAI_COMPATIBLE = "custom_openai_compatible"


class RoutingStrategy(str, Enum):
    """Routing strategy for model selection."""
    CHEAPEST = "cheapest"
    LOWEST_LATENCY = "lowest_latency"
    HIGHEST_QUALITY = "highest_quality"
    LOCAL_ONLY = "local_only"
    GPU_AWARE = "gpu_aware"
    COMPLIANCE_AWARE = "compliance_aware"
    ROUND_ROBIN = "round_robin"


def validate_base_url(url: str, allow_private: bool = False) -> str:
    """Validate base_url to prevent SSRF attacks.
    
    Args:
        url: The base URL to validate
        allow_private: If True, allow private/internal IPs (for self-hosted providers)
    """
    if not url:
        raise ValueError("base_url cannot be empty")
    
    parsed = urlparse(url)
    
    # Only allow http and https protocols
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid protocol '{parsed.scheme}'. Only http and https are allowed.")
    
    # Ensure hostname is present
    if not parsed.hostname:
        raise ValueError("base_url must contain a valid hostname")
    
    # For cloud providers, block requests to private/internal IP addresses
    if not allow_private:
        try:
            ip = ipaddress.ip_address(parsed.hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise ValueError(
                    f"base_url points to private/internal IP address ({parsed.hostname}). "
                    "This is blocked to prevent SSRF attacks. Use kind='self_hosted' for internal services."
                )
        except ValueError as e:
            # If hostname is not an IP address, check if it resolves to blocked names
            if str(e).startswith("base_url points to"):
                raise
            blocked_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254"}
            if parsed.hostname.lower() in blocked_hosts:
                raise ValueError(
                    f"base_url hostname '{parsed.hostname}' is blocked to prevent SSRF attacks. "
                    "Use kind='self_hosted' for internal services."
                )
    
    return url


class ProviderCreate(BaseModel):
    """Schema for creating a new provider."""
    name: str = Field(..., min_length=1, max_length=255)
    kind: ProviderKind
    provider_type: ProviderType
    base_url: str = Field(..., min_length=1)
    api_key: str = ""
    auth_header: str = ""
    enabled: bool = True
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    
    @field_validator("base_url")
    @classmethod
    def validate_url(cls, v: str, info) -> str:
        # Allow private IPs for self-hosted providers
        allow_private = info.data.get("kind") == ProviderKind.SELF_HOSTED
        return validate_base_url(v, allow_private=allow_private)


class ProviderUpdate(BaseModel):
    """Schema for updating a provider."""
    name: str | None = None
    kind: ProviderKind | None = None
    provider_type: ProviderType | None = None
    base_url: str | None = None
    api_key: str | None = None
    clear_api_key: bool = False
    auth_header: str | None = None
    enabled: bool | None = None
    provider_metadata: dict[str, Any] | None = None
    
    @field_validator("base_url")
    @classmethod
    def validate_url(cls, v: str | None, info) -> str | None:
        if v is not None:
            # Allow private IPs only if kind is explicitly set to SELF_HOSTED in this update
            # Note: For updates where kind is not changed, validation happens at the endpoint level
            allow_private = info.data.get("kind") == ProviderKind.SELF_HOSTED
            return validate_base_url(v, allow_private=allow_private)
        return v


class ProviderResponse(BaseModel):
    """Schema for provider response."""
    id: int
    name: str
    kind: ProviderKind
    provider_type: ProviderType
    base_url: str
    api_key_set: bool
    api_key_preview: str
    auth_header: str
    enabled: bool
    provider_metadata: dict[str, Any]
    last_health_check: datetime | None = None
    health_status: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ModelCapabilities(BaseModel):
    """Model capabilities."""
    reasoning: bool = False
    vision: bool = False
    tools: bool = False
    streaming: bool = True


class ModelCreate(BaseModel):
    """Schema for creating a new model."""
    model_config = ConfigDict(populate_by_name=True)

    provider_id: int
    model_name: str = Field(..., min_length=1, max_length=255)
    display_name: str = Field(..., min_length=1, max_length=255)
    context_window: int = Field(default=4096, ge=1)
    max_output_tokens: int = Field(default=2048, ge=1, alias="max_output")
    cost_per_input_token: float = Field(default=0.0, ge=0.0, alias="cost_per_input_tok")
    cost_per_output_token: float = Field(default=0.0, ge=0.0, alias="cost_per_output_tok")
    capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)
    enabled: bool = True

    @field_validator("capabilities", mode="before")
    @classmethod
    def _coerce_capabilities(cls, v):
        # Accept a list like ["reasoning", "tools"] and turn it into the
        # ModelCapabilities dict shape used internally.
        if isinstance(v, list):
            return {cap: True for cap in v if isinstance(cap, str)}
        return v


class ModelUpdate(BaseModel):
    """Schema for updating a model."""
    provider_id: int | None = None
    model_name: str | None = None
    display_name: str | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None
    cost_per_input_token: float | None = None
    cost_per_output_token: float | None = None
    capabilities: ModelCapabilities | None = None
    enabled: bool | None = None


class ModelResponse(BaseModel):
    """Schema for model response."""
    id: int
    provider_id: int
    provider_name: str
    model_name: str
    display_name: str
    context_window: int
    max_output_tokens: int
    cost_per_input_token: float
    cost_per_output_token: float
    capabilities: ModelCapabilities
    enabled: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AgentRoutingConfig(BaseModel):
    """Agent routing configuration."""
    agent_name: str
    primary_model_id: int
    fallback_model_ids: list[int] = Field(default_factory=list)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1)
    reasoning_mode: bool = False
    timeout_s: float = Field(default=90.0, gt=0.0)
    retry_policy: str = "exponential_backoff"
    routing_strategy: RoutingStrategy | None = None


class AgentRoutingUpdate(BaseModel):
    """Update agent routing configuration."""
    primary_model_id: int | None = None
    fallback_model_ids: list[int] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    reasoning_mode: bool | None = None
    timeout_s: float | None = None
    retry_policy: str | None = None
    routing_strategy: RoutingStrategy | None = None
    quota: dict[str, int] | None = None  # {"max_requests_per_hour": int, "max_tokens_per_hour": int}


class AgentRoutingResponse(BaseModel):
    """Agent routing configuration response."""
    id: int | None = None
    agent_name: str
    primary_model_id: int | None = None
    primary_model_name: str | None = None
    fallback_model_ids: list[int] = Field(default_factory=list)
    fallback_model_names: list[str] = Field(default_factory=list)
    temperature: float = 0.2
    max_tokens: int = 1024
    reasoning_mode: bool = False
    timeout_s: float = 90.0
    retry_policy: str = "exponential_backoff"
    routing_strategy: RoutingStrategy | None = None
    quota: dict[str, int] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


# OpenAI-compatible schemas
class ChatMessage(BaseModel):
    """Chat message."""
    role: str
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request."""
    model: str | None = None  # Optional: gateway routes by X-Agent header
    messages: list[ChatMessage]
    temperature: float = 0.7
    max_tokens: int | None = None
    tools: list[dict[str, Any]] | None = None
    stream: bool = False
    response_format: dict[str, Any] | None = None


class ChatCompletionUsage(BaseModel):
    """Token usage."""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionChoice(BaseModel):
    """Chat completion choice."""
    index: int
    message: ChatMessage
    finish_reason: str


class ChatCompletionResponse(BaseModel):
    """OpenAI-compatible chat completion response."""
    model_config = {"populate_by_name": True}
    
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: ChatCompletionUsage
    forgemind_metadata: dict[str, Any] | None = Field(default=None, serialization_alias="_forgemind_metadata")


class ModelInfo(BaseModel):
    """Model information."""
    id: str
    object: str = "model"
    created: int
    owned_by: str


class UsageAnalytics(BaseModel):
    """Usage analytics."""
    total_requests: int
    total_tokens: int
    total_cost_usd: float
    by_agent: dict[str, dict[str, Any]]
    by_model: dict[str, dict[str, Any]]
    by_provider: dict[str, dict[str, Any]]


class ProviderHealth(BaseModel):
    """Provider health status."""
    provider_id: int
    provider_name: str
    status: str  # healthy | degraded | down
    last_check: datetime | None
    avg_latency_ms: float | None
    error_rate: float | None


class AuditLogEntry(BaseModel):
    """Audit log entry."""
    id: int
    timestamp: datetime
    agent_name: str
    user_id: str | None
    model_id: int
    model_name: str
    provider_id: int
    provider_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    latency_ms: float
    request_hash: str
    response_hash: str
    truncated_request: str
    status: str

    class Config:
        from_attributes = True
