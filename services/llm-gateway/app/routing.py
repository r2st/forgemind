"""Routing engine for LLM Gateway."""

import asyncio
import hashlib
import time
from typing import Any
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Provider, Model, AgentRouting, AuditLog, FallbackEvent, GlobalRoutingConfig
from .schemas import ChatCompletionRequest, ChatCompletionResponse, RoutingStrategy
from .translators import get_translator
from .crypto import decrypt_api_key
import structlog

logger = structlog.get_logger()


class RoutingEngine:
    """Core routing engine for LLM requests."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.client = httpx.AsyncClient(timeout=120.0)
    
    async def route_request(
        self,
        request: ChatCompletionRequest,
        agent_name: str,
        user_id: str | None = None,
    ) -> ChatCompletionResponse:
        """Route a chat completion request through the gateway."""
        
        # Get agent routing config
        agent_config = await self._get_agent_config(agent_name)
        if not agent_config:
            raise ValueError(f"No routing config found for agent: {agent_name}")
        
        # Build fallback chain
        model_ids = [agent_config.primary_model_id] + agent_config.fallback_model_ids
        
        # Override request parameters from agent config
        if request.temperature is None or request.temperature == 0.7:  # default
            request.temperature = agent_config.temperature
        if request.max_tokens is None:
            request.max_tokens = agent_config.max_tokens
        
        last_error = None
        for idx, model_id in enumerate(model_ids):
            try:
                # Get model and provider
                model = await self._get_model(model_id)
                if not model or not model.enabled:
                    logger.warning("model_disabled", model_id=model_id)
                    continue
                
                provider = await self._get_provider(model.provider_id)
                if not provider or not provider.enabled:
                    logger.warning("provider_disabled", provider_id=model.provider_id)
                    continue
                
                # Execute request
                start_time = time.time()
                response = await self._execute_request(request, model, provider)
                latency_ms = (time.time() - start_time) * 1000
                
                # Calculate cost (cost_per_*_token is already in USD per token)
                cost_usd = (
                    response.usage.prompt_tokens * model.cost_per_input_token +
                    response.usage.completion_tokens * model.cost_per_output_token
                )
                
                # Log audit entry
                await self._log_audit(
                    agent_name=agent_name,
                    user_id=user_id,
                    model=model,
                    provider=provider,
                    request=request,
                    response=response,
                    latency_ms=latency_ms,
                    cost_usd=cost_usd,
                    status="fallback" if idx > 0 else "success",
                )
                
                logger.info(
                    "llm_request_success",
                    agent=agent_name,
                    model=model.model_name,
                    provider=provider.name,
                    tokens=response.usage.total_tokens,
                    latency_ms=latency_ms,
                    cost_usd=cost_usd,
                )
                
                # Add ForgeMind metadata to response
                response_dict = response.model_dump()
                response_dict["forgemind_metadata"] = {
                    "cost_usd": cost_usd,
                    "latency_ms": latency_ms,
                    "model_name": model.model_name,
                    "provider_name": provider.name,
                    "agent_name": agent_name,
                    "fallback_used": idx > 0,
                }
                
                return ChatCompletionResponse(**response_dict)
                
            except Exception as e:
                logger.warning(
                    "llm_request_failed",
                    agent=agent_name,
                    model_id=model_id,
                    error=str(e),
                )
                
                # Log fallback event if not the last model
                if idx < len(model_ids) - 1:
                    await self._log_fallback(
                        agent_name=agent_name,
                        from_model_id=model_id,
                        to_model_id=model_ids[idx + 1],
                        reason=str(e),
                    )
                
                last_error = e
                await asyncio.sleep(0.2)  # Brief delay before fallback
        
        # All models failed
        raise RuntimeError(f"All models failed for agent {agent_name}: {last_error}")
    
    async def _get_agent_config(self, agent_name: str) -> AgentRouting | None:
        """Get agent routing configuration."""
        result = await self.db.execute(
            select(AgentRouting).where(AgentRouting.agent_name == agent_name)
        )
        return result.scalar_one_or_none()
    
    async def _get_model(self, model_id: int) -> Model | None:
        """Get model by ID."""
        result = await self.db.execute(
            select(Model).where(Model.id == model_id)
        )
        return result.scalar_one_or_none()
    
    async def _get_provider(self, provider_id: int) -> Provider | None:
        """Get provider by ID."""
        result = await self.db.execute(
            select(Provider).where(Provider.id == provider_id)
        )
        return result.scalar_one_or_none()
    
    async def _execute_request(
        self,
        request: ChatCompletionRequest,
        model: Model,
        provider: Provider,
    ) -> ChatCompletionResponse:
        """Execute request to provider."""
        
        # Decrypt API key
        api_key = decrypt_api_key(provider.encrypted_api_key)
        
        # Get translator
        translator = get_translator(provider.provider_type, provider.base_url)
        
        # Translate request
        url, payload, headers = await translator.translate_request(request, api_key)
        
        # Add custom auth header if present
        if provider.auth_header:
            key, value = provider.auth_header.split(":", 1)
            headers[key.strip()] = value.strip()
        
        # Execute request
        response = await self.client.post(url, json=payload, headers=headers)
        
        if response.status_code >= 400:
            raise RuntimeError(f"Provider error {response.status_code}: {response.text[:500]}")
        
        # Translate response. httpx's response.json() is sync, but test mocks
        # may stub it as an AsyncMock that returns a coroutine — handle both.
        response_data = response.json()
        if asyncio.iscoroutine(response_data):
            response_data = await response_data
        return await translator.translate_response(response_data, model.model_name)
    
    async def _log_audit(
        self,
        agent_name: str,
        user_id: str | None,
        model: Model,
        provider: Provider,
        request: ChatCompletionRequest,
        response: ChatCompletionResponse,
        latency_ms: float,
        cost_usd: float,
        status: str,
    ):
        """Log audit entry."""
        
        request_str = request.model_dump_json()
        response_str = response.model_dump_json()
        
        audit = AuditLog(
            agent_name=agent_name,
            user_id=user_id,
            model_id=model.id,
            provider_id=provider.id,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            request_hash=hashlib.sha256(request_str.encode()).hexdigest(),
            response_hash=hashlib.sha256(response_str.encode()).hexdigest(),
            truncated_request=request_str[:500],
            status=status,
        )
        
        self.db.add(audit)
        await self.db.commit()
    
    async def _log_fallback(
        self,
        agent_name: str,
        from_model_id: int,
        to_model_id: int,
        reason: str,
    ):
        """Log fallback event."""
        
        event = FallbackEvent(
            agent_name=agent_name,
            from_model_id=from_model_id,
            to_model_id=to_model_id,
            reason=reason[:512],
            error_message=reason,
        )
        
        self.db.add(event)
        await self.db.commit()
    
    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()
