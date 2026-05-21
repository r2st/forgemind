"""Configuration for the LLM Gateway service."""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """LLM Gateway service settings."""

    service_name: str = "llm-gateway"
    environment: str = "dev"
    log_level: str = "INFO"
    
    # Database
    postgres_dsn: str = Field(
        default="postgresql+asyncpg://postgres:postgres@postgres:5432/forgemind",
        description="PostgreSQL connection string. Override with POSTGRES_DSN env var."
    )
    
    # Encryption - MUST be set via GATEWAY_SECRET_KEY env var (Fernet key)
    gateway_secret_key: str = Field(
        default="",
        description="Fernet key for encrypting API keys. MUST be set in production."
    )
    
    # JWT
    jwt_secret: str = Field(
        default="",
        description="JWT signing secret. MUST be set via JWT_SECRET env var."
    )
    jwt_algorithm: str = "HS256"
    
    @field_validator("gateway_secret_key")
    @classmethod
    def validate_gateway_secret(cls, v: str, info) -> str:
        """Ensure gateway secret key is set."""
        if not v:
            from cryptography.fernet import Fernet
            # Auto-generate for dev/staging
            return Fernet.generate_key().decode()
        return v
    
    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, v: str, info) -> str:
        """Ensure JWT secret is set."""
        environment = info.data.get("environment", "dev")
        if environment == "prod" and not v:
            raise ValueError("JWT_SECRET must be set in production")
        if not v:
            import secrets
            return secrets.token_urlsafe(32)
        if len(v) < 16:
            raise ValueError("JWT_SECRET must be at least 16 characters")
        return v
    
    # Quotas
    default_max_requests_per_minute: int = 100
    default_max_tokens_per_day: int = 1000000
    
    # Health check
    health_check_interval_seconds: int = 300  # 5 minutes
    
    # Request timeout
    default_provider_timeout_seconds: float = 90.0
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # Ignore unknown env vars


_settings: Settings | None = None


def get_settings() -> Settings:
    """Get cached settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
