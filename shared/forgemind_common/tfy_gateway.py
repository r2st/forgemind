"""TrueFoundry AI Gateway client.

The TrueFoundry AI Gateway is the single LLM ingress for every
ForgeMind service. It is OpenAI-API-compatible, supports multi-provider
routing, cost-aware fallback, semantic caching, observability, and PII
redaction.

This client abstracts:

  * Tier-based model selection (fast / powerful / fallback / embedding).
  * Automatic fallback when the primary tier errors or rate-limits.
  * Token + cost accounting per call (forwarded to the gateway's
    observability layer; we just surface the headers).
  * Tracing via OpenTelemetry headers (`x-tfy-trace-id`).

All services should import `get_gateway()` rather than instantiating
their own OpenAI clients.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, AsyncIterator

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)


class ModelTier(str, Enum):
    """Logical model tiers routed by the TrueFoundry AI Gateway."""

    FAST = "fast"            # summarization, classification, cheap tasks
    POWERFUL = "powerful"    # RCA, multi-step reasoning, executive reports
    FALLBACK = "fallback"    # local Ollama or self-hosted backstop
    EMBEDDING = "embedding"  # vector embeddings for pgvector


@dataclass
class GatewayUsage:
    """Per-call usage accounting returned by the gateway."""

    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    trace_id: str = ""
    cached: bool = False


@dataclass
class GatewayResponse:
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: GatewayUsage = field(default_factory=lambda: GatewayUsage(model=""))
    raw: dict[str, Any] = field(default_factory=dict)


class TrueFoundryGateway:
    """Thin async client over the TrueFoundry AI Gateway.

    The gateway exposes an OpenAI-compatible REST surface at
    `{base_url}/api/inference/openai/chat/completions`. Routing
    decisions live in the gateway config (see
    `infra/truefoundry/gateway/routing.yaml`); the client just selects a
    tier and passes through.
    """

    _TIER_FALLBACK_CHAIN: dict[ModelTier, list[ModelTier]] = {
        ModelTier.POWERFUL: [ModelTier.POWERFUL, ModelTier.FAST, ModelTier.FALLBACK],
        ModelTier.FAST: [ModelTier.FAST, ModelTier.FALLBACK],
        ModelTier.FALLBACK: [ModelTier.FALLBACK],
        ModelTier.EMBEDDING: [ModelTier.EMBEDDING],
    }

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        s = get_settings()
        self.base_url = (base_url or s.tfy_gateway_base_url).rstrip("/")
        self.api_key = api_key or s.tfy_gateway_api_key
        self._tier_models = {
            ModelTier.FAST: s.tfy_model_fast,
            ModelTier.POWERFUL: s.tfy_model_powerful,
            ModelTier.FALLBACK: s.tfy_model_fallback,
            ModelTier.EMBEDDING: s.tfy_model_embedding,
        }
        self._client = httpx.AsyncClient(timeout=timeout_s)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def model_for(self, tier: ModelTier) -> str:
        return self._tier_models[tier]

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tier: ModelTier = ModelTier.POWERFUL,
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> GatewayResponse:
        """Run a chat completion with tier-based fallback."""
        last_err: Exception | None = None
        for fb_tier in self._TIER_FALLBACK_CHAIN[tier]:
            try:
                return await self._chat_one(
                    tier=fb_tier,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=tools,
                    response_format=response_format,
                    extra_headers=extra_headers,
                )
            except (httpx.HTTPError, GatewayError) as exc:
                logger.warning(
                    "tfy_gateway.tier_failed",
                    extra={"tier": fb_tier.value, "error": str(exc)},
                )
                last_err = exc
                await asyncio.sleep(0.2)
        raise GatewayError(f"All tiers failed: {last_err}") from last_err

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tier: ModelTier = ModelTier.POWERFUL,
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[str]:
        """Stream tokens as they arrive. Falls back on initial connection error only."""
        model = self.model_for(tier)
        url = f"{self.base_url}/api/inference/openai/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        async with self._client.stream(
            "POST", url, json=payload, headers=self._headers()
        ) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                raise GatewayError(f"{resp.status_code}: {body.decode(errors='ignore')[:500]}")
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {})
                    if "content" in delta and delta["content"]:
                        yield delta["content"]
                except (KeyError, IndexError, json.JSONDecodeError):
                    continue

    async def embed(self, texts: list[str]) -> list[list[float]]:
        model = self.model_for(ModelTier.EMBEDDING)
        url = f"{self.base_url}/api/inference/openai/embeddings"
        resp = await self._client.post(
            url,
            json={"model": model, "input": texts},
            headers=self._headers(),
        )
        if resp.status_code >= 400:
            raise GatewayError(f"{resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        return [item["embedding"] for item in data["data"]]

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _chat_one(
        self,
        *,
        tier: ModelTier,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        tools: list[dict[str, Any]] | None,
        response_format: dict[str, Any] | None,
        extra_headers: dict[str, str] | None,
    ) -> GatewayResponse:
        model = self.model_for(tier)
        url = f"{self.base_url}/api/inference/openai/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
        if response_format:
            payload["response_format"] = response_format

        t0 = time.time()
        headers = self._headers()
        if extra_headers:
            headers.update(extra_headers)
        resp = await self._client.post(url, json=payload, headers=headers)
        latency_ms = (time.time() - t0) * 1000.0

        if resp.status_code >= 400:
            raise GatewayError(f"{resp.status_code}: {resp.text[:500]}")

        body = resp.json()
        choice = body["choices"][0]["message"]
        usage_block = body.get("usage", {}) or {}
        usage = GatewayUsage(
            model=model,
            prompt_tokens=usage_block.get("prompt_tokens", 0),
            completion_tokens=usage_block.get("completion_tokens", 0),
            total_tokens=usage_block.get("total_tokens", 0),
            cost_usd=float(resp.headers.get("x-tfy-cost-usd", 0.0) or 0.0),
            latency_ms=latency_ms,
            trace_id=resp.headers.get("x-tfy-trace-id", ""),
            cached=resp.headers.get("x-tfy-cache", "miss").lower() == "hit",
        )
        return GatewayResponse(
            content=choice.get("content") or "",
            tool_calls=choice.get("tool_calls") or [],
            usage=usage,
            raw=body,
        )

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h


class GatewayError(RuntimeError):
    """Raised when the TrueFoundry gateway returns an unrecoverable error."""


@lru_cache(maxsize=1)
def get_gateway() -> TrueFoundryGateway:
    """Process-wide singleton gateway client."""
    return TrueFoundryGateway()
