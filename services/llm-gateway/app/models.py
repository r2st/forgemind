"""Database models for LLM Gateway."""

from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Provider(Base):
    """LLM Provider model."""
    __tablename__ = "llm_providers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    kind = Column(String(50), nullable=False)  # cloud | self_hosted
    provider_type = Column(String(100), nullable=False)  # openai | anthropic | etc.
    base_url = Column(String(512), nullable=False)
    encrypted_api_key = Column(Text, nullable=False, default="")
    auth_header = Column(String(512), nullable=False, default="")
    enabled = Column(Boolean, nullable=False, default=True)
    provider_metadata = Column(JSON, nullable=False, default=dict)
    last_health_check = Column(DateTime, nullable=True)
    health_status = Column(String(50), nullable=True)  # healthy | degraded | down
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    models = relationship("Model", back_populates="provider", cascade="all, delete-orphan")


class Model(Base):
    """LLM Model model."""
    __tablename__ = "llm_models"

    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, ForeignKey("llm_providers.id", ondelete="CASCADE"), nullable=False)
    model_name = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=False)
    context_window = Column(Integer, nullable=False, default=4096)
    max_output_tokens = Column(Integer, nullable=False, default=2048)
    cost_per_input_token = Column(Float, nullable=False, default=0.0)
    cost_per_output_token = Column(Float, nullable=False, default=0.0)
    capabilities = Column(JSON, nullable=False, default=dict)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    provider = relationship("Provider", back_populates="models")


class AgentRouting(Base):
    """Agent routing configuration."""
    __tablename__ = "llm_agent_routing"

    id = Column(Integer, primary_key=True, index=True)
    agent_name = Column(String(255), unique=True, nullable=False, index=True)
    primary_model_id = Column(Integer, ForeignKey("llm_models.id"), nullable=False)
    fallback_model_ids = Column(JSON, nullable=False, default=list)  # list[int]
    temperature = Column(Float, nullable=False, default=0.2)
    max_tokens = Column(Integer, nullable=False, default=1024)
    reasoning_mode = Column(Boolean, nullable=False, default=False)
    timeout_s = Column(Float, nullable=False, default=90.0)
    retry_policy = Column(String(100), nullable=False, default="exponential_backoff")
    routing_strategy = Column(String(50), nullable=True)
    quota = Column(JSON, nullable=True)  # {"max_requests_per_hour": int, "max_tokens_per_hour": int}
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class AuditLog(Base):
    """Audit log for LLM requests."""
    __tablename__ = "llm_audit_log"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    agent_name = Column(String(255), nullable=False, index=True)
    user_id = Column(String(255), nullable=True, index=True)
    model_id = Column(Integer, ForeignKey("llm_models.id"), nullable=False)
    provider_id = Column(Integer, ForeignKey("llm_providers.id"), nullable=False)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Float, nullable=False, default=0.0)
    latency_ms = Column(Float, nullable=False, default=0.0)
    request_hash = Column(String(64), nullable=False)
    response_hash = Column(String(64), nullable=False)
    truncated_request = Column(Text, nullable=False, default="")
    status = Column(String(50), nullable=False, default="success")  # success | error | fallback


class FallbackEvent(Base):
    """Fallback events log."""
    __tablename__ = "llm_fallback_events"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    agent_name = Column(String(255), nullable=False, index=True)
    from_model_id = Column(Integer, ForeignKey("llm_models.id"), nullable=False)
    to_model_id = Column(Integer, ForeignKey("llm_models.id"), nullable=False)
    reason = Column(String(512), nullable=False)
    error_message = Column(Text, nullable=True)


class GlobalRoutingConfig(Base):
    """Global routing configuration."""
    __tablename__ = "llm_global_routing"

    id = Column(Integer, primary_key=True)
    routing_strategy = Column(String(50), nullable=False, default="highest_quality")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
