"""LLM Gateway main FastAPI application."""

import time
from datetime import datetime, timedelta
from typing import Any, Optional
from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
import structlog
from jose import JWTError, jwt
import httpx

from .config import get_settings
from .database import get_db, init_db
from .models import Provider, Model, AgentRouting, AuditLog, FallbackEvent, GlobalRoutingConfig
from .schemas import (
    ProviderCreate, ProviderUpdate, ProviderResponse,
    ModelCreate, ModelUpdate, ModelResponse, ModelCapabilities,
    AgentRoutingConfig, AgentRoutingUpdate, AgentRoutingResponse,
    ChatCompletionRequest, ChatCompletionResponse, ModelInfo,
    UsageAnalytics, ProviderHealth, AuditLogEntry,
    validate_base_url, ProviderKind,
)
from .routing import RoutingEngine
from .crypto import encrypt_api_key, decrypt_api_key, mask_api_key

# Import admin authentication dependency
from forgemind_common.auth import require_admin

logger = structlog.get_logger()


def extract_user_from_jwt(authorization: Optional[str]) -> Optional[str]:
    """Extract and validate user ID from JWT token."""
    if not authorization:
        return None
    
    try:
        # Remove 'Bearer ' prefix if present
        token = authorization.replace("Bearer ", "").replace("bearer ", "")
        settings = get_settings()
        
        # Decode and validate JWT
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm]
        )
        return payload.get("sub")
    except JWTError as e:
        logger.warning("jwt_validation_failed", error=str(e))
        return None

app = FastAPI(
    title="ForgeMind LLM Gateway",
    description="Generic Enterprise LLM Gateway for ForgeMind AI",
    version="1.0.0",
)


@app.on_event("startup")
async def startup():
    """Initialize database on startup."""
    await init_db()
    logger.info("llm_gateway_started")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "llm-gateway"}


@app.get("/healthz")
async def healthz():
    """Health check endpoint (alternate path for compatibility)."""
    return {"status": "healthy", "service": "llm-gateway"}


# ============================================================================
# OpenAI-Compatible Inference Endpoints
# ============================================================================

async def check_quota(db: AsyncSession, agent_name: str) -> None:
    """Check if agent has exceeded quota limits."""
    # Get agent routing config
    result = await db.execute(
        select(AgentRouting).where(AgentRouting.agent_name == agent_name)
    )
    routing = result.scalar_one_or_none()
    
    if not routing or not routing.quota:
        return  # No quota configured
    
    quota_config = routing.quota
    max_requests = quota_config.get("max_requests_per_hour")
    max_tokens = quota_config.get("max_tokens_per_hour")
    
    if not max_requests and not max_tokens:
        return  # No limits configured
    
    # Get current hour's usage
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    usage_result = await db.execute(
        select(AuditLog)
        .where(
            AuditLog.agent_name == agent_name,
            AuditLog.timestamp >= one_hour_ago
        )
    )
    usage_entries = usage_result.scalars().all()
    
    # Check request count
    if max_requests:
        request_count = len(usage_entries)
        if request_count >= max_requests:
            raise HTTPException(
                status_code=429,
                detail=f"Agent '{agent_name}' has exceeded max requests per hour ({max_requests})"
            )
    
    # Check token count
    if max_tokens:
        total_tokens = sum(entry.total_tokens or 0 for entry in usage_entries)
        if total_tokens >= max_tokens:
            raise HTTPException(
                status_code=429,
                detail=f"Agent '{agent_name}' has exceeded max tokens per hour ({max_tokens})"
            )


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse, response_model_by_alias=True)
async def chat_completions(
    request: ChatCompletionRequest,
    x_agent: str = Header(None, alias="X-Agent"),
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """OpenAI-compatible chat completions endpoint."""
    
    if not x_agent:
        raise HTTPException(status_code=400, detail="X-Agent header is required")
    
    # Validate JWT and extract user_id
    user_id = extract_user_from_jwt(authorization)
    if not user_id:
        logger.warning("llm_gateway_request_no_auth", agent=x_agent)
        # Allow unauthenticated requests in dev, but log them
        user_id = "anonymous"
    
    # Check quota before processing request
    await check_quota(db, x_agent)
    
    engine = RoutingEngine(db)
    try:
        response = await engine.route_request(request, x_agent, user_id)
        return response
    except Exception as e:
        logger.error("chat_completion_error", agent=x_agent, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await engine.close()


@app.get("/v1/models")
async def list_models(db: AsyncSession = Depends(get_db)):
    """List all enabled models."""
    
    result = await db.execute(
        select(Model, Provider)
        .join(Provider)
        .where(Model.enabled == True, Provider.enabled == True)
    )
    
    models = []
    for model, provider in result:
        models.append(
            ModelInfo(
                id=model.model_name,
                object="model",
                created=int(model.created_at.timestamp()),
                owned_by=provider.name,
            )
        )
    
    return {"object": "list", "data": models}


# ============================================================================
# Admin Endpoints - Providers
# ============================================================================

@app.get("/api/v1/admin/llm/providers", response_model=list[ProviderResponse])
async def list_providers(user=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """List all providers."""
    
    result = await db.execute(select(Provider))
    providers = result.scalars().all()
    
    return [
        ProviderResponse(
            id=p.id,
            name=p.name,
            kind=p.kind,
            provider_type=p.provider_type,
            base_url=p.base_url,
            api_key_set=bool(p.encrypted_api_key),
            api_key_preview=mask_api_key(decrypt_api_key(p.encrypted_api_key)),
            auth_header=p.auth_header,
            enabled=p.enabled,
            provider_metadata=p.provider_metadata,
            last_health_check=p.last_health_check,
            health_status=p.health_status,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in providers
    ]


@app.get("/api/v1/admin/llm/providers/{provider_id}", response_model=ProviderResponse)
async def get_provider(provider_id: int, user=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Get a specific provider by ID."""
    
    result = await db.execute(
        select(Provider).where(Provider.id == provider_id)
    )
    provider = result.scalar_one_or_none()
    
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    return ProviderResponse(
        id=provider.id,
        name=provider.name,
        kind=provider.kind,
        provider_type=provider.provider_type,
        base_url=provider.base_url,
        api_key_set=bool(provider.encrypted_api_key),
        api_key_preview=mask_api_key(decrypt_api_key(provider.encrypted_api_key)),
        auth_header=provider.auth_header,
        enabled=provider.enabled,
        provider_metadata=provider.provider_metadata,
        last_health_check=provider.last_health_check,
        health_status=provider.health_status,
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )


@app.post("/api/v1/admin/llm/providers", response_model=ProviderResponse)
async def create_provider(
    provider: ProviderCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new provider."""
    
    # Check if provider with same name exists
    result = await db.execute(
        select(Provider).where(Provider.name == provider.name)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Provider with this name already exists")
    
    encrypted_key = encrypt_api_key(provider.api_key) if provider.api_key else ""
    
    db_provider = Provider(
        name=provider.name,
        kind=provider.kind.value,
        provider_type=provider.provider_type.value,
        base_url=provider.base_url,
        encrypted_api_key=encrypted_key,
        auth_header=provider.auth_header,
        enabled=provider.enabled,
        provider_metadata=provider.provider_metadata,
    )
    
    db.add(db_provider)
    await db.commit()
    await db.refresh(db_provider)
    
    logger.info("provider_created", provider_id=db_provider.id, name=db_provider.name)
    
    return ProviderResponse(
        id=db_provider.id,
        name=db_provider.name,
        kind=db_provider.kind,
        provider_type=db_provider.provider_type,
        base_url=db_provider.base_url,
        api_key_set=bool(db_provider.encrypted_api_key),
        api_key_preview=mask_api_key(provider.api_key),
        auth_header=db_provider.auth_header,
        enabled=db_provider.enabled,
        provider_metadata=db_provider.provider_metadata,
        last_health_check=db_provider.last_health_check,
        health_status=db_provider.health_status,
        created_at=db_provider.created_at,
        updated_at=db_provider.updated_at,
    )


@app.put("/api/v1/admin/llm/providers/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: int,
    update: ProviderUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a provider."""
    
    result = await db.execute(
        select(Provider).where(Provider.id == provider_id)
    )
    db_provider = result.scalar_one_or_none()
    
    if not db_provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    if update.name is not None:
        db_provider.name = update.name
    if update.kind is not None:
        db_provider.kind = update.kind.value
    if update.provider_type is not None:
        db_provider.provider_type = update.provider_type.value
    if update.base_url is not None:
        # Validate base_url with current or updated provider kind
        current_kind = update.kind.value if update.kind else db_provider.kind
        allow_private = current_kind == ProviderKind.SELF_HOSTED.value
        try:
            validate_base_url(update.base_url, allow_private=allow_private)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        db_provider.base_url = update.base_url
    if update.clear_api_key:
        db_provider.encrypted_api_key = ""
    elif update.api_key is not None:
        db_provider.encrypted_api_key = encrypt_api_key(update.api_key)
    if update.auth_header is not None:
        db_provider.auth_header = update.auth_header
    if update.enabled is not None:
        db_provider.enabled = update.enabled
    if update.provider_metadata is not None:
        db_provider.provider_metadata = update.provider_metadata
    
    await db.commit()
    await db.refresh(db_provider)
    
    logger.info("provider_updated", provider_id=provider_id)
    
    return ProviderResponse(
        id=db_provider.id,
        name=db_provider.name,
        kind=db_provider.kind,
        provider_type=db_provider.provider_type,
        base_url=db_provider.base_url,
        api_key_set=bool(db_provider.encrypted_api_key),
        api_key_preview=mask_api_key(decrypt_api_key(db_provider.encrypted_api_key)),
        auth_header=db_provider.auth_header,
        enabled=db_provider.enabled,
        provider_metadata=db_provider.provider_metadata,
        last_health_check=db_provider.last_health_check,
        health_status=db_provider.health_status,
        created_at=db_provider.created_at,
        updated_at=db_provider.updated_at,
    )


@app.delete("/api/v1/admin/llm/providers/{provider_id}")
async def delete_provider(
    provider_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a provider."""
    
    result = await db.execute(
        select(Provider).where(Provider.id == provider_id)
    )
    db_provider = result.scalar_one_or_none()
    
    if not db_provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    await db.delete(db_provider)
    await db.commit()
    
    logger.info("provider_deleted", provider_id=provider_id)
    
    return {"status": "deleted", "provider_id": provider_id}


# ============================================================================
# Admin Endpoints - Models
# ============================================================================

@app.get("/api/v1/admin/llm/models", response_model=list[ModelResponse])
async def list_admin_models(user=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """List all models with provider details."""
    
    result = await db.execute(
        select(Model, Provider).join(Provider)
    )
    
    models = []
    for model, provider in result:
        models.append(
            ModelResponse(
                id=model.id,
                provider_id=model.provider_id,
                provider_name=provider.name,
                model_name=model.model_name,
                display_name=model.display_name,
                context_window=model.context_window,
                max_output_tokens=model.max_output_tokens,
                cost_per_input_token=model.cost_per_input_token,
                cost_per_output_token=model.cost_per_output_token,
                capabilities=ModelCapabilities(**model.capabilities),
                enabled=model.enabled,
                created_at=model.created_at,
                updated_at=model.updated_at,
            )
        )
    
    return models


@app.get("/api/v1/admin/llm/models/{model_id}", response_model=ModelResponse)
async def get_model(model_id: int, db: AsyncSession = Depends(get_db)):
    """Get a specific model by ID."""
    
    result = await db.execute(
        select(Model, Provider).join(Provider).where(Model.id == model_id)
    )
    row = result.one_or_none()
    
    if not row:
        raise HTTPException(status_code=404, detail="Model not found")
    
    model, provider = row
    
    return ModelResponse(
        id=model.id,
        provider_id=model.provider_id,
        provider_name=provider.name,
        model_name=model.model_name,
        display_name=model.display_name,
        context_window=model.context_window,
        max_output_tokens=model.max_output_tokens,
        cost_per_input_token=model.cost_per_input_token,
        cost_per_output_token=model.cost_per_output_token,
        capabilities=ModelCapabilities(**model.capabilities),
        enabled=model.enabled,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


@app.post("/api/v1/admin/llm/models", response_model=ModelResponse)
async def create_model(
    model: ModelCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new model."""
    
    # Verify provider exists
    result = await db.execute(
        select(Provider).where(Provider.id == model.provider_id)
    )
    provider = result.scalar_one_or_none()
    if not provider:
        raise HTTPException(status_code=400, detail="Provider not found")
    
    db_model = Model(
        provider_id=model.provider_id,
        model_name=model.model_name,
        display_name=model.display_name,
        context_window=model.context_window,
        max_output_tokens=model.max_output_tokens,
        cost_per_input_token=model.cost_per_input_token,
        cost_per_output_token=model.cost_per_output_token,
        capabilities=model.capabilities.model_dump(),
        enabled=model.enabled,
    )
    
    db.add(db_model)
    await db.commit()
    await db.refresh(db_model)
    
    logger.info("model_created", model_id=db_model.id, name=db_model.model_name)
    
    return ModelResponse(
        id=db_model.id,
        provider_id=db_model.provider_id,
        provider_name=provider.name,
        model_name=db_model.model_name,
        display_name=db_model.display_name,
        context_window=db_model.context_window,
        max_output_tokens=db_model.max_output_tokens,
        cost_per_input_token=db_model.cost_per_input_token,
        cost_per_output_token=db_model.cost_per_output_token,
        capabilities=ModelCapabilities(**db_model.capabilities),
        enabled=db_model.enabled,
        created_at=db_model.created_at,
        updated_at=db_model.updated_at,
    )


@app.put("/api/v1/admin/llm/models/{model_id}", response_model=ModelResponse)
async def update_model(
    model_id: int,
    update: ModelUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a model."""
    
    result = await db.execute(
        select(Model).where(Model.id == model_id)
    )
    db_model = result.scalar_one_or_none()
    
    if not db_model:
        raise HTTPException(status_code=404, detail="Model not found")
    
    if update.provider_id is not None:
        db_model.provider_id = update.provider_id
    if update.model_name is not None:
        db_model.model_name = update.model_name
    if update.display_name is not None:
        db_model.display_name = update.display_name
    if update.context_window is not None:
        db_model.context_window = update.context_window
    if update.max_output_tokens is not None:
        db_model.max_output_tokens = update.max_output_tokens
    if update.cost_per_input_token is not None:
        db_model.cost_per_input_token = update.cost_per_input_token
    if update.cost_per_output_token is not None:
        db_model.cost_per_output_token = update.cost_per_output_token
    if update.capabilities is not None:
        db_model.capabilities = update.capabilities.model_dump()
    if update.enabled is not None:
        db_model.enabled = update.enabled
    
    await db.commit()
    await db.refresh(db_model)
    
    # Get provider
    result = await db.execute(
        select(Provider).where(Provider.id == db_model.provider_id)
    )
    provider = result.scalar_one()
    
    logger.info("model_updated", model_id=model_id)
    
    return ModelResponse(
        id=db_model.id,
        provider_id=db_model.provider_id,
        provider_name=provider.name,
        model_name=db_model.model_name,
        display_name=db_model.display_name,
        context_window=db_model.context_window,
        max_output_tokens=db_model.max_output_tokens,
        cost_per_input_token=db_model.cost_per_input_token,
        cost_per_output_token=db_model.cost_per_output_token,
        capabilities=ModelCapabilities(**db_model.capabilities),
        enabled=db_model.enabled,
        created_at=db_model.created_at,
        updated_at=db_model.updated_at,
    )


@app.delete("/api/v1/admin/llm/models/{model_id}")
async def delete_model(
    model_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a model."""
    
    result = await db.execute(
        select(Model).where(Model.id == model_id)
    )
    db_model = result.scalar_one_or_none()
    
    if not db_model:
        raise HTTPException(status_code=404, detail="Model not found")
    
    await db.delete(db_model)
    await db.commit()
    
    logger.info("model_deleted", model_id=model_id)
    
    return {"status": "deleted", "model_id": model_id}


# ============================================================================
# Admin Endpoints - Agent Routing
# ============================================================================

@app.get("/api/v1/admin/llm/agents/{agent_name}/routing", response_model=AgentRoutingResponse)
async def get_agent_routing(
    agent_name: str,
    db: AsyncSession = Depends(get_db),
):
    """Get agent routing configuration."""
    
    result = await db.execute(
        select(AgentRouting).where(AgentRouting.agent_name == agent_name)
    )
    routing = result.scalar_one_or_none()
    
    if not routing:
        # Return default configuration
        return AgentRoutingResponse(
            agent_name=agent_name,
        )
    
    # Get model names
    primary_model = await db.execute(
        select(Model).where(Model.id == routing.primary_model_id)
    )
    primary = primary_model.scalar_one()
    
    fallback_names = []
    for model_id in routing.fallback_model_ids:
        result = await db.execute(select(Model).where(Model.id == model_id))
        model = result.scalar_one_or_none()
        if model:
            fallback_names.append(model.model_name)
    
    return AgentRoutingResponse(
        id=routing.id,
        agent_name=routing.agent_name,
        primary_model_id=routing.primary_model_id,
        primary_model_name=primary.model_name,
        fallback_model_ids=routing.fallback_model_ids,
        fallback_model_names=fallback_names,
        temperature=routing.temperature,
        max_tokens=routing.max_tokens,
        reasoning_mode=routing.reasoning_mode,
        timeout_s=routing.timeout_s,
        retry_policy=routing.retry_policy,
        routing_strategy=routing.routing_strategy,
        quota=routing.quota,
        created_at=routing.created_at,
        updated_at=routing.updated_at,
    )


@app.put("/api/v1/admin/llm/agents/{agent_name}/routing", response_model=AgentRoutingResponse)
async def update_agent_routing(
    agent_name: str,
    update: AgentRoutingUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update agent routing configuration (creates if not exists)."""
    
    result = await db.execute(
        select(AgentRouting).where(AgentRouting.agent_name == agent_name)
    )
    routing = result.scalar_one_or_none()
    
    if not routing:
        # Create new routing config if it doesn't exist
        if update.primary_model_id is None:
            raise HTTPException(
                status_code=400,
                detail="primary_model_id is required when creating new routing config"
            )
        
        routing = AgentRouting(
            agent_name=agent_name,
            primary_model_id=update.primary_model_id,
            fallback_model_ids=update.fallback_model_ids or [],
            temperature=update.temperature if update.temperature is not None else 0.2,
            max_tokens=update.max_tokens if update.max_tokens is not None else 1024,
            reasoning_mode=update.reasoning_mode if update.reasoning_mode is not None else False,
            timeout_s=update.timeout_s if update.timeout_s is not None else 90.0,
            retry_policy=update.retry_policy or "exponential_backoff",
            routing_strategy=update.routing_strategy.value if update.routing_strategy else None,
            quota=update.quota,
        )
        db.add(routing)
    else:
        # Update existing routing config
        if update.primary_model_id is not None:
            routing.primary_model_id = update.primary_model_id
        if update.fallback_model_ids is not None:
            routing.fallback_model_ids = update.fallback_model_ids
        if update.temperature is not None:
            routing.temperature = update.temperature
        if update.max_tokens is not None:
            routing.max_tokens = update.max_tokens
        if update.reasoning_mode is not None:
            routing.reasoning_mode = update.reasoning_mode
        if update.timeout_s is not None:
            routing.timeout_s = update.timeout_s
        if update.retry_policy is not None:
            routing.retry_policy = update.retry_policy
        if update.routing_strategy is not None:
            routing.routing_strategy = update.routing_strategy.value if update.routing_strategy else None
        if update.quota is not None:
            routing.quota = update.quota
    
    await db.commit()
    await db.refresh(routing)
    
    # Get model names
    primary_model = await db.execute(
        select(Model).where(Model.id == routing.primary_model_id)
    )
    primary = primary_model.scalar_one()
    
    fallback_names = []
    for model_id in routing.fallback_model_ids:
        result = await db.execute(select(Model).where(Model.id == model_id))
        model = result.scalar_one_or_none()
        if model:
            fallback_names.append(model.model_name)
    
    logger.info("agent_routing_updated", agent_name=agent_name)
    
    return AgentRoutingResponse(
        id=routing.id,
        agent_name=routing.agent_name,
        primary_model_id=routing.primary_model_id,
        primary_model_name=primary.model_name,
        fallback_model_ids=routing.fallback_model_ids,
        fallback_model_names=fallback_names,
        temperature=routing.temperature,
        max_tokens=routing.max_tokens,
        reasoning_mode=routing.reasoning_mode,
        timeout_s=routing.timeout_s,
        retry_policy=routing.retry_policy,
        routing_strategy=routing.routing_strategy,
        quota=routing.quota,
        created_at=routing.created_at,
        updated_at=routing.updated_at,
    )


# ============================================================================
# Admin Endpoints - Fallback Chain
# ============================================================================

@app.get("/api/v1/admin/llm/agents/{agent_name}/fallback")
async def get_fallback_chain(
    agent_name: str,
    db: AsyncSession = Depends(get_db),
):
    """Get fallback chain for an agent."""
    
    result = await db.execute(
        select(AgentRouting).where(AgentRouting.agent_name == agent_name)
    )
    routing = result.scalar_one_or_none()
    
    if not routing:
        # Return empty fallback chain if no routing config exists
        return {
            "agent_name": agent_name,
            "fallback_model_ids": [],
            "fallback_model_names": []
        }
    
    # Get fallback model names
    fallback_names = []
    for model_id in routing.fallback_model_ids:
        result = await db.execute(select(Model).where(Model.id == model_id))
        model = result.scalar_one_or_none()
        if model:
            fallback_names.append(model.model_name)
    
    return {
        "agent_name": agent_name,
        "fallback_model_ids": routing.fallback_model_ids,
        "fallback_model_names": fallback_names
    }


@app.put("/api/v1/admin/llm/agents/{agent_name}/fallback")
async def update_fallback_chain(
    agent_name: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
):
    """Update fallback chain for an agent."""
    
    fallback_model_ids = data.get("fallback_model_ids", [])
    
    result = await db.execute(
        select(AgentRouting).where(AgentRouting.agent_name == agent_name)
    )
    routing = result.scalar_one_or_none()
    
    if not routing:
        # Create new routing config with first model as primary
        # and all models in fallback list (for create-via-fallback endpoint)
        if not fallback_model_ids:
            raise HTTPException(
                status_code=400,
                detail="Cannot create routing config without models"
            )
        
        # Use first model as primary, keep all in fallback list
        routing = AgentRouting(
            agent_name=agent_name,
            primary_model_id=fallback_model_ids[0],
            fallback_model_ids=fallback_model_ids,
        )
        db.add(routing)
    else:
        # Update existing fallback chain
        routing.fallback_model_ids = fallback_model_ids
    
    await db.commit()
    await db.refresh(routing)
    
    # Get fallback model names
    fallback_names = []
    for model_id in routing.fallback_model_ids:
        result = await db.execute(select(Model).where(Model.id == model_id))
        model = result.scalar_one_or_none()
        if model:
            fallback_names.append(model.model_name)
    
    logger.info("fallback_chain_updated", agent_name=agent_name, 
                fallback_count=len(routing.fallback_model_ids))
    
    return {
        "agent_name": agent_name,
        "fallback_model_ids": routing.fallback_model_ids,
        "fallback_model_names": fallback_names
    }


# ============================================================================
# Admin Endpoints - Usage & Analytics
# ============================================================================

@app.get("/api/v1/admin/llm/usage")
async def get_usage(
    start_date: str | None = None,
    end_date: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Get usage analytics."""
    
    # Build query
    query = select(AuditLog)
    if start_date:
        start = datetime.fromisoformat(start_date)
        query = query.where(AuditLog.timestamp >= start)
    if end_date:
        end = datetime.fromisoformat(end_date)
        query = query.where(AuditLog.timestamp <= end)
    
    result = await db.execute(query)
    logs = result.scalars().all()
    
    # Aggregate statistics
    total_requests = len(logs)
    total_tokens = sum(log.total_tokens for log in logs)
    total_cost = sum(log.cost_usd for log in logs)
    
    # By agent
    by_agent: dict[str, dict[str, Any]] = {}
    for log in logs:
        if log.agent_name not in by_agent:
            by_agent[log.agent_name] = {"requests": 0, "tokens": 0, "cost_usd": 0.0}
        by_agent[log.agent_name]["requests"] += 1
        by_agent[log.agent_name]["tokens"] += log.total_tokens
        by_agent[log.agent_name]["cost_usd"] += log.cost_usd
    
    # By model (simplified - would need join for model names)
    by_model: dict[str, dict[str, Any]] = {}
    for log in logs:
        model_key = str(log.model_id)
        if model_key not in by_model:
            by_model[model_key] = {"requests": 0, "tokens": 0, "cost_usd": 0.0}
        by_model[model_key]["requests"] += 1
        by_model[model_key]["tokens"] += log.total_tokens
        by_model[model_key]["cost_usd"] += log.cost_usd
    
    # By provider
    by_provider: dict[str, dict[str, Any]] = {}
    for log in logs:
        provider_key = str(log.provider_id)
        if provider_key not in by_provider:
            by_provider[provider_key] = {"requests": 0, "tokens": 0, "cost_usd": 0.0}
        by_provider[provider_key]["requests"] += 1
        by_provider[provider_key]["tokens"] += log.total_tokens
        by_provider[provider_key]["cost_usd"] += log.cost_usd
    
    return {
        "total_requests": total_requests,
        "total_tokens": total_tokens,
        "total_cost_usd": total_cost,
        "by_agent": by_agent,
        "by_model": by_model,
        "by_provider": by_provider,
    }


@app.get("/api/v1/admin/llm/health")
async def get_provider_health(user=Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Get provider health status."""
    
    result = await db.execute(select(Provider))
    providers = result.scalars().all()
    
    health_statuses = []
    for provider in providers:
        # Perform live health probe
        status = "unknown"
        latency_ms = None
        
        try:
            # Probe the provider's base URL
            probe_url = f"{provider.base_url}/models" if provider.base_url else None
            if probe_url:
                # Decrypt API key for health probe
                decrypted_key = decrypt_api_key(provider.encrypted_api_key) if provider.encrypted_api_key else ""
                client = httpx.AsyncClient(timeout=5.0)
                response = await client.get(probe_url, headers={"Authorization": f"Bearer {decrypted_key}"})
                await client.aclose()
                
                latency_ms = response.elapsed.total_seconds() * 1000
                if response.status_code == 200:
                    # Check latency to determine if degraded
                    if latency_ms > 1000:  # > 1 second is degraded
                        status = "degraded"
                    else:
                        status = "healthy"
                else:
                    status = "degraded"
            else:
                # No base URL, mark as unknown
                status = "unknown"
        except Exception as e:
            status = "unhealthy"
            logger.warning("provider_health_check_failed", provider_id=provider.id, error=str(e))
        
        # Calculate error rate from recent audit logs
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        logs_result = await db.execute(
            select(AuditLog)
            .where(
                and_(
                    AuditLog.provider_id == provider.id,
                    AuditLog.timestamp >= one_hour_ago
                )
            )
        )
        logs = logs_result.scalars().all()
        
        total = len(logs)
        errors = sum(1 for log in logs if log.status == "error")
        error_rate = errors / total if total > 0 else 0.0
        
        # Adjust status based on error rate if live probe showed healthy
        if status == "healthy" and error_rate > 0.5:
            status = "down"
        elif status == "healthy" and error_rate > 0.2:
            status = "degraded"
        
        health_statuses.append({
            "provider_id": provider.id,
            "provider_name": provider.name,
            "status": status,
            "last_check": datetime.utcnow(),
            "latency_ms": latency_ms,
            "error_rate": error_rate,
        })
    
    return {"providers": health_statuses}


@app.get("/api/v1/admin/llm/cost")
async def get_cost_monitoring(db: AsyncSession = Depends(get_db)):
    """Get cost monitoring data."""
    
    # Current month
    now = datetime.utcnow()
    month_start = datetime(now.year, now.month, 1)
    
    result = await db.execute(
        select(AuditLog).where(AuditLog.timestamp >= month_start)
    )
    logs = result.scalars().all()
    
    # By provider
    by_provider: dict[str, float] = {}
    for log in logs:
        key = str(log.provider_id)
        by_provider[key] = by_provider.get(key, 0.0) + log.cost_usd
    
    # By agent
    by_agent: dict[str, float] = {}
    for log in logs:
        by_agent[log.agent_name] = by_agent.get(log.agent_name, 0.0) + log.cost_usd
    
    # By model
    by_model: dict[str, float] = {}
    for log in logs:
        key = str(log.model_id)
        by_model[key] = by_model.get(key, 0.0) + log.cost_usd
    
    # Projected month-end cost (linear extrapolation)
    days_in_month = (datetime(now.year, now.month + 1 if now.month < 12 else 1, 1) - timedelta(days=1)).day
    days_elapsed = now.day
    total_cost = sum(log.cost_usd for log in logs)
    projected = total_cost * days_in_month / days_elapsed if days_elapsed > 0 else 0.0
    
    return {
        "current_month_total": total_cost,
        "by_provider": by_provider,
        "by_agent": by_agent,
        "by_model": by_model,
        "projected_month_end": projected,
    }


@app.get("/api/v1/admin/llm/audit")
async def get_audit_log(
    start_date: str | None = None,
    end_date: str | None = None,
    agent_name: str | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    """Get audit log entries."""
    
    query = select(AuditLog, Model, Provider).select_from(AuditLog).join(Model, AuditLog.model_id == Model.id).join(Provider, Model.provider_id == Provider.id)
    
    if start_date:
        start = datetime.fromisoformat(start_date)
        query = query.where(AuditLog.timestamp >= start)
    if end_date:
        end = datetime.fromisoformat(end_date)
        query = query.where(AuditLog.timestamp <= end)
    if agent_name:
        query = query.where(AuditLog.agent_name == agent_name)
    
    query = query.order_by(AuditLog.timestamp.desc()).limit(limit)
    
    result = await db.execute(query)
    
    entries = []
    for audit, model, provider in result:
        entries.append({
            "id": audit.id,
            "timestamp": audit.timestamp.isoformat(),
            "agent_name": audit.agent_name,
            "agent": audit.agent_name,  # Alias for tests
            "user_id": audit.user_id,
            "model_id": audit.model_id,
            "model_name": model.model_name,
            "model": model.model_name,  # Alias for tests
            "provider_id": audit.provider_id,
            "provider_name": provider.name,
            "provider": provider.name,  # Alias for tests
            "prompt_tokens": audit.prompt_tokens,
            "input_tokens": audit.prompt_tokens,  # Alias for tests
            "completion_tokens": audit.completion_tokens,
            "output_tokens": audit.completion_tokens,  # Alias for tests
            "total_tokens": audit.total_tokens,
            "cost_usd": audit.cost_usd,
            "latency_ms": audit.latency_ms,
            "request_hash": audit.request_hash,
            "response_hash": audit.response_hash,
            "truncated_request": audit.truncated_request,
            "status": audit.status,
            "fallback_used": False,  # TODO: Track fallback usage in audit log
        })
    
    return {"entries": entries}
