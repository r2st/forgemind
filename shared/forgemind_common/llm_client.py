"""Thin client for calling the LLM Gateway service.

All agents should use this client instead of calling LLM providers directly.
The gateway handles routing, fallbacks, cost tracking, and observability.
"""

from __future__ import annotations

import os
import time
from typing import Any, AsyncIterator
from dataclasses import dataclass, field

import httpx

from .config import get_settings


@dataclass
class LLMUsage:
    """Token usage from an LLM request."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0


@dataclass
class LLMResponse:
    """Response from an LLM request."""
    content: str
    usage: LLMUsage = field(default_factory=LLMUsage)
    raw: dict[str, Any] = field(default_factory=dict)


class LLMClient:
    """
    Thin client for calling the LLM Gateway service.
    
    All agent inference must route through this client, which:
    1. Sends requests to the centralized LLM Gateway
    2. Includes the X-Agent header for agent identification
    3. Uses OpenAI-compatible request/response format
    4. Never calls LLM providers directly
    
    The gateway resolves agent → model mapping, handles fallbacks,
    tracks costs, and provides observability.
    """
    
    def __init__(self, agent_name: str, timeout_s: float = 90.0):
        """
        Initialize LLM client for a specific agent.
        
        Args:
            agent_name: Name of the calling agent (e.g. "rca-agent", "chatops-agent")
            timeout_s: Request timeout in seconds
        """
        self.agent_name = agent_name
        self.gateway_url = os.getenv("LLM_GATEWAY_URL", "http://llm-gateway:8000")
        self.timeout_s = timeout_s
        self._client = httpx.AsyncClient(timeout=timeout_s)
    
    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str = "auto",  # Gateway resolves model from agent config
        temperature: float | None = None,  # Gateway uses agent default if None
        max_tokens: int | None = None,  # Gateway uses agent default if None
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """
        Send a chat completion request through the gateway.
        
        Args:
            messages: List of chat messages in OpenAI format
            model: Model identifier (gateway resolves from agent config if "auto")
            temperature: Sampling temperature (gateway default if None)
            max_tokens: Max completion tokens (gateway default if None)
            tools: Function calling tools (optional)
        
        Returns:
            LLMResponse with content and usage information
        """
        url = f"{self.gateway_url.rstrip('/')}/v1/chat/completions"
        
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
        
        headers = {
            "Content-Type": "application/json",
            "X-Agent": self.agent_name,
        }
        
        # Add JWT if available
        settings = get_settings()
        if hasattr(settings, "jwt_token") and settings.jwt_token:
            headers["Authorization"] = f"Bearer {settings.jwt_token}"
        
        start = time.time()
        response = await self._client.post(url, json=payload, headers=headers)
        latency_ms = (time.time() - start) * 1000
        
        if response.status_code >= 400:
            raise RuntimeError(
                f"LLM Gateway error {response.status_code}: {response.text[:500]}"
            )
        
        data = response.json()
        
        # Extract content and usage
        content = ""
        if data.get("choices"):
            choice = data["choices"][0]
            content = choice.get("message", {}).get("content", "")
        
        usage_data = data.get("usage", {})
        usage = LLMUsage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
            latency_ms=latency_ms,
        )
        
        return LLMResponse(content=content, usage=usage, raw=data)
    
    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str = "auto",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """
        Stream chat completion tokens as they arrive.
        
        Args:
            messages: List of chat messages in OpenAI format
            model: Model identifier (gateway resolves from agent config if "auto")
            temperature: Sampling temperature (gateway default if None)
            max_tokens: Max completion tokens (gateway default if None)
        
        Yields:
            Content tokens as they arrive
        """
        url = f"{self.gateway_url.rstrip('/')}/v1/chat/completions"
        
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        
        headers = {
            "Content-Type": "application/json",
            "X-Agent": self.agent_name,
        }
        
        # Add JWT if available
        settings = get_settings()
        if hasattr(settings, "jwt_token") and settings.jwt_token:
            headers["Authorization"] = f"Bearer {settings.jwt_token}"
        
        async with self._client.stream("POST", url, json=payload, headers=headers) as response:
            if response.status_code >= 400:
                body = await response.aread()
                raise RuntimeError(
                    f"LLM Gateway error {response.status_code}: {body.decode()[:500]}"
                )
            
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                
                try:
                    import json
                    chunk = json.loads(data_str)
                    delta = chunk["choices"][0].get("delta", {})
                    if "content" in delta and delta["content"]:
                        yield delta["content"]
                except (KeyError, IndexError, json.JSONDecodeError):
                    continue
    
    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()


def get_llm_client(agent_name: str) -> LLMClient:
    """
    Get an LLM client for the specified agent.
    
    Args:
        agent_name: Name of the calling agent
    
    Returns:
        Configured LLMClient instance
    """
    return LLMClient(agent_name=agent_name)
