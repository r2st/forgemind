"""Exercises the /v1/chat/completions inference path (routing engine + translators)."""

from __future__ import annotations

import importlib
import os
import sys
from unittest.mock import AsyncMock, patch

import httpx
import pytest


def _create_provider(client, name="inf-prov"):
    return client.post(
        "/api/v1/admin/llm/providers",
        json={
            "name": name,
            "kind": "cloud",
            "provider_type": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "enabled": True,
            "provider_metadata": {},
        },
    ).json()


def _create_model(client, provider_id, name="m-inf"):
    return client.post(
        "/api/v1/admin/llm/models",
        json={
            "provider_id": provider_id,
            "model_name": name,
            "display_name": name,
            "context_window": 4096,
            "max_output_tokens": 1024,
            "cost_per_input_token": 1e-6,
            "cost_per_output_token": 2e-6,
            "capabilities": {"reasoning": False, "vision": False, "tools": True, "streaming": True},
            "enabled": True,
        },
    ).json()


def _create_routing(client, agent, primary_id, fallback_ids=(), quota=None):
    return client.put(
        f"/api/v1/admin/llm/agents/{agent}/routing",
        json={
            "primary_model_id": primary_id,
            "fallback_model_ids": list(fallback_ids),
            "temperature": 0.2,
            "max_tokens": 256,
            "quota": quota,
        },
    ).json()


def _provider_response_body(model_name="m-inf"):
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hi from upstream."},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    }


@pytest.fixture
def routing_setup(llm_gateway_client):
    import uuid as _uuid

    suffix = _uuid.uuid4().hex[:8]
    p = _create_provider(llm_gateway_client, name=f"inf-prov-rt-{suffix}")
    m = _create_model(llm_gateway_client, p["id"], name=f"m-inf-rt-{suffix}")
    agent_name = f"inf-agent-{suffix}"
    _create_routing(llm_gateway_client, agent_name, m["id"], quota={"max_requests_per_hour": 100})
    return p, m, agent_name


def _stub_provider_call(monkeypatch, status_code=200, body=None, side_effect=None):
    """Stub the RoutingEngine httpx client so it doesn't reach the network."""
    # The routing engine creates its own httpx.AsyncClient. We patch the
    # AsyncClient.post to return our fake response.
    real_post = httpx.AsyncClient.post

    async def fake_post(self, url, *args, **kwargs):
        if "api.openai.com" in url or "anthropic.com" in url or "googleapis.com" in url:
            if side_effect is not None:
                raise side_effect
            return httpx.Response(
                status_code=status_code,
                json=body or _provider_response_body(),
            )
        return await real_post(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)


def test_chat_completion_happy_path(llm_gateway_client, routing_setup, monkeypatch):
    _, _, agent = routing_setup
    _stub_provider_call(monkeypatch)
    r = llm_gateway_client.post(
        "/v1/chat/completions",
        headers={"X-Agent": agent},
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["choices"][0]["message"]["content"] == "Hi from upstream."
    assert "_forgemind_metadata" in body
    assert body["_forgemind_metadata"]["agent_name"] == agent


def test_chat_completion_falls_back(
    llm_gateway_client, monkeypatch, api_gateway_client
):
    import uuid as _uuid

    suffix = _uuid.uuid4().hex[:6]
    p = _create_provider(llm_gateway_client, name=f"fb-inf-prov-{suffix}")
    primary = _create_model(llm_gateway_client, p["id"], name=f"m-fb-pri-{suffix}")
    fallback = _create_model(llm_gateway_client, p["id"], name=f"m-fb-sec-{suffix}")
    agent_name = f"fb-agent-{suffix}"
    _create_routing(
        llm_gateway_client, agent_name, primary["id"], fallback_ids=(fallback["id"],)
    )

    call_count = {"n": 0}

    async def fake_post(self, url, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(200, json=_provider_response_body("m-fb-secondary"))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    r = llm_gateway_client.post(
        "/v1/chat/completions",
        headers={"X-Agent": agent_name},
        json={"model": "auto", "messages": [{"role": "user", "content": "x"}]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["_forgemind_metadata"]["fallback_used"] is True


def test_chat_completion_unknown_agent_500(llm_gateway_client, monkeypatch):
    r = llm_gateway_client.post(
        "/v1/chat/completions",
        headers={"X-Agent": "ghost-agent"},
        json={"model": "auto", "messages": [{"role": "user", "content": "x"}]},
    )
    assert r.status_code == 500


def test_chat_completion_quota_enforced(llm_gateway_client, monkeypatch):
    import uuid as _uuid

    s = _uuid.uuid4().hex[:6]
    p = _create_provider(llm_gateway_client, name=f"q-prov-{s}")
    m = _create_model(llm_gateway_client, p["id"], name=f"m-quota-{s}")
    agent = f"q-agent-{s}"
    _create_routing(llm_gateway_client, agent, m["id"], quota={"max_requests_per_hour": 1})

    _stub_provider_call(monkeypatch)
    r1 = llm_gateway_client.post(
        "/v1/chat/completions",
        headers={"X-Agent": agent},
        json={"model": "auto", "messages": [{"role": "user", "content": "x"}]},
    )
    assert r1.status_code == 200, r1.text
    r2 = llm_gateway_client.post(
        "/v1/chat/completions",
        headers={"X-Agent": agent},
        json={"model": "auto", "messages": [{"role": "user", "content": "x"}]},
    )
    assert r2.status_code == 429


def test_audit_log_written(llm_gateway_client, routing_setup, monkeypatch):
    _, _, agent = routing_setup
    _stub_provider_call(monkeypatch)
    llm_gateway_client.post(
        "/v1/chat/completions",
        headers={"X-Agent": agent},
        json={"model": "auto", "messages": [{"role": "user", "content": "x"}]},
    )
    audit = llm_gateway_client.get("/api/v1/admin/llm/audit").json()
    assert len(audit) >= 1


def test_chat_completion_with_jwt(llm_gateway_client, routing_setup, monkeypatch, admin_token):
    _, _, agent = routing_setup
    _stub_provider_call(monkeypatch)
    r = llm_gateway_client.post(
        "/v1/chat/completions",
        headers={"X-Agent": agent, "Authorization": f"Bearer {admin_token}"},
        json={"model": "auto", "messages": [{"role": "user", "content": "x"}]},
    )
    assert r.status_code == 200
