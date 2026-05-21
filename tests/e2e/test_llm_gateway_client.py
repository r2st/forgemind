"""Tests for shared/forgemind_common/llm_gateway.py real HTTP path.

The main e2e conftest replaces LLMGateway.chat/embed with mocks for
agent tests. Here we restore the original methods and feed responses
through a stub httpx client to exercise the real translation logic.
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from forgemind_common import llm_gateway as gw
from .conftest import REAL_LLM_GATEWAY_METHODS

_STUBBED_CHAT = gw.LLMGateway.chat
_STUBBED_EMBED = gw.LLMGateway.embed


@pytest.fixture(autouse=True)
def real_llm_gateway_methods():
    """Install the real chat/embed for one test, restore the e2e mock
    afterward so the rest of the suite keeps working."""
    gw.LLMGateway.chat = REAL_LLM_GATEWAY_METHODS["chat"]
    gw.LLMGateway.embed = REAL_LLM_GATEWAY_METHODS["embed"]
    gw.LLMGateway._chat_one = REAL_LLM_GATEWAY_METHODS["_chat_one"]
    gw.LLMGateway.chat_stream = REAL_LLM_GATEWAY_METHODS["chat_stream"]
    try:
        yield
    finally:
        gw.LLMGateway.chat = _STUBBED_CHAT
        gw.LLMGateway.embed = _STUBBED_EMBED


class _R:
    def __init__(self, status_code=200, json_body=None, headers=None, text=""):
        self.status_code = status_code
        self._json = json_body or {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._json


@pytest.mark.asyncio
async def test_chat_disabled_raises():
    g = gw.LLMGateway(agent_name="rca-agent")
    g.enabled = False
    with pytest.raises(gw.GatewayError, match="disabled"):
        await g.chat([{"role": "user", "content": "x"}])


@pytest.mark.asyncio
async def test_chat_success_path():
    g = gw.LLMGateway(agent_name="rca-agent")
    g.enabled = True
    body = {
        "choices": [{"message": {"content": "hello", "tool_calls": []}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
    }
    fake_resp = _R(
        200,
        body,
        headers={
            "x-llm-cost-usd": "0.01",
            "x-llm-trace-id": "trc",
            "x-llm-cache": "hit",
        },
    )
    with patch.object(g._client, "post", AsyncMock(return_value=fake_resp)):
        out = await g.chat([{"role": "user", "content": "x"}])
    assert out.content == "hello"
    assert out.usage.total_tokens == 12
    assert out.usage.cost_usd == 0.01
    assert out.usage.cached is True
    assert out.usage.trace_id == "trc"


@pytest.mark.asyncio
async def test_chat_fallback_chain():
    """All tiers should be tried; final failure raises GatewayError."""
    g = gw.LLMGateway(agent_name="rca-agent")
    g.enabled = True
    fail_resp = _R(500, text="boom")
    with patch.object(g._client, "post", AsyncMock(return_value=fail_resp)):
        with pytest.raises(gw.GatewayError):
            await g.chat([{"role": "user", "content": "x"}])


@pytest.mark.asyncio
async def test_chat_with_tools_and_response_format():
    g = gw.LLMGateway(agent_name="rca-agent")
    g.enabled = True
    body = {
        "choices": [{"message": {"content": "ok", "tool_calls": []}}],
        "usage": {},
    }
    with patch.object(
        g._client, "post", AsyncMock(return_value=_R(200, body))
    ) as p:
        await g.chat(
            [{"role": "user", "content": "x"}],
            tools=[{"type": "function", "function": {"name": "x"}}],
            response_format={"type": "json_object"},
            extra_headers={"X-Custom": "1"},
        )
    payload = p.await_args.kwargs["json"]
    headers = p.await_args.kwargs["headers"]
    assert payload["tools"]
    assert payload["response_format"]["type"] == "json_object"
    assert headers.get("X-Custom") == "1"


@pytest.mark.asyncio
async def test_embed_success():
    g = gw.LLMGateway(agent_name="rca-agent")
    g.enabled = True
    body = {"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]}
    with patch.object(g._client, "post", AsyncMock(return_value=_R(200, body))):
        vecs = await g.embed(["a", "b"])
    assert vecs == [[0.1, 0.2], [0.3, 0.4]]


@pytest.mark.asyncio
async def test_embed_disabled():
    g = gw.LLMGateway(agent_name="rca-agent")
    g.enabled = False
    with pytest.raises(gw.GatewayError):
        await g.embed(["x"])


@pytest.mark.asyncio
async def test_embed_error():
    g = gw.LLMGateway(agent_name="rca-agent")
    g.enabled = True
    with patch.object(g._client, "post", AsyncMock(return_value=_R(500, text="x"))):
        with pytest.raises(gw.GatewayError):
            await g.embed(["a"])


def test_headers_with_and_without_key():
    g = gw.LLMGateway(agent_name="rca-agent")
    g.api_key = "k"
    h = g._headers()
    assert h["Authorization"] == "Bearer k"
    g.api_key = ""
    h2 = g._headers()
    assert "Authorization" not in h2


def test_model_for_override():
    g = gw.LLMGateway(agent_name="rca-agent")
    g._model_override = "custom-model"
    assert g.model_for(gw.ModelTier.POWERFUL) == "custom-model"
    g._model_override = ""
    assert g.model_for(gw.ModelTier.POWERFUL) in g._tier_models.values()


def test_aclose():
    import asyncio

    g = gw.LLMGateway(agent_name="rca-agent")
    asyncio.get_event_loop().run_until_complete(g.aclose())


def test_get_gateway_factory():
    g = gw.get_gateway("rca-agent")
    assert g.agent_name == "rca-agent"


def test_backend_signature_changes_with_key():
    g = gw.LLMGateway(agent_name="rca-agent")
    g.api_key = "a"
    sig1 = g.backend_signature(gw.ModelTier.POWERFUL)
    g.api_key = "b"
    sig2 = g.backend_signature(gw.ModelTier.POWERFUL)
    assert sig1 != sig2
    g.api_key = ""
    sig3 = g.backend_signature(gw.ModelTier.POWERFUL)
    assert sig3[3] == ""  # empty fingerprint when no key


@pytest.mark.asyncio
async def test_chat_stream_yields():
    g = gw.LLMGateway(agent_name="rca-agent")
    g.enabled = True

    async def fake_lines():
        import json as _json

        yield "data: " + _json.dumps({"choices": [{"delta": {"content": "hi "}}]})
        yield "data: " + _json.dumps({"choices": [{"delta": {"content": "there"}}]})
        yield "data: [DONE]"

    class _Stream:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        def aiter_lines(self):
            return fake_lines()

        async def aread(self):
            return b""

    def stream(*a, **k):
        return _Stream()

    with patch.object(g._client, "stream", stream):
        out = []
        async for tok in g.chat_stream([{"role": "user", "content": "x"}]):
            out.append(tok)
    assert out == ["hi ", "there"]


@pytest.mark.asyncio
async def test_chat_stream_error():
    g = gw.LLMGateway(agent_name="rca-agent")
    g.enabled = True

    class _Err:
        status_code = 500

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        def aiter_lines(self):
            async def gen():
                if False:
                    yield

            return gen()

        async def aread(self):
            return b"oops"

    def stream(*a, **k):
        return _Err()

    with patch.object(g._client, "stream", stream):
        with pytest.raises(gw.GatewayError):
            async for _ in g.chat_stream([{"role": "user", "content": "x"}]):
                pass


@pytest.mark.asyncio
async def test_chat_stream_disabled():
    g = gw.LLMGateway(agent_name="rca-agent")
    g.enabled = False
    with pytest.raises(gw.GatewayError):
        async for _ in g.chat_stream([{"role": "user", "content": "x"}]):
            pass
