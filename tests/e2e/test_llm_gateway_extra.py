"""More coverage for LLM Gateway main.py: usage/health/cost with data,
provider health probe paths, audit log filters, JWT decoder."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest


def _admin_headers(api_gateway_client):
    r = api_gateway_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": os.environ["AUTH_ADMIN_PASS"]},
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create_provider(client, name):
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


def _create_model(client, provider_id, name):
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


def _setup_agent_with_calls(llm_gateway_client, monkeypatch, agent_name, n_calls=3):
    s = uuid.uuid4().hex[:6]
    p = _create_provider(llm_gateway_client, name=f"p-{s}")
    m = _create_model(llm_gateway_client, p["id"], name=f"m-{s}")
    llm_gateway_client.put(
        f"/api/v1/admin/llm/agents/{agent_name}/routing",
        json={"primary_model_id": m["id"]},
    )

    async def fake_post(self, url, *args, **kwargs):
        if "api.openai.com" in url:
            return httpx.Response(
                200,
                json={
                    "id": "x",
                    "object": "chat.completion",
                    "created": 1,
                    "model": m["model_name"],
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                },
            )
        return await httpx.AsyncClient.post(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    for _ in range(n_calls):
        llm_gateway_client.post(
            "/v1/chat/completions",
            headers={"X-Agent": agent_name},
            json={"model": "auto", "messages": [{"role": "user", "content": "x"}]},
        )
    return p, m


def test_usage_with_data(llm_gateway_client, monkeypatch):
    _setup_agent_with_calls(llm_gateway_client, monkeypatch, "usage-agent", n_calls=2)
    r = llm_gateway_client.get("/api/v1/admin/llm/usage")
    assert r.status_code == 200
    body = r.json()
    assert body["total_requests"] >= 2
    assert body["total_tokens"] >= 30
    assert "by_agent" in body


def test_usage_with_date_range(llm_gateway_client, monkeypatch):
    _setup_agent_with_calls(llm_gateway_client, monkeypatch, "usage-dt-agent", n_calls=1)
    yesterday = (datetime.utcnow() - timedelta(days=1)).isoformat()
    tomorrow = (datetime.utcnow() + timedelta(days=1)).isoformat()
    r = llm_gateway_client.get(
        "/api/v1/admin/llm/usage",
        params={"start_date": yesterday, "end_date": tomorrow},
    )
    assert r.status_code == 200


def test_cost_with_data(llm_gateway_client, monkeypatch):
    _setup_agent_with_calls(llm_gateway_client, monkeypatch, "cost-agent", n_calls=2)
    r = llm_gateway_client.get("/api/v1/admin/llm/cost")
    assert r.status_code == 200
    body = r.json()
    assert body["current_month_total"] > 0
    assert "by_provider" in body
    assert "projected_month_end" in body


def test_audit_log_with_filters(llm_gateway_client, monkeypatch):
    _setup_agent_with_calls(llm_gateway_client, monkeypatch, "audit-flt-agent", n_calls=2)
    r = llm_gateway_client.get(
        "/api/v1/admin/llm/audit",
        params={"agent_name": "audit-flt-agent", "limit": 10},
    )
    assert r.status_code == 200
    body = r.json()
    assert "entries" in body
    for entry in body["entries"]:
        assert entry["agent_name"] == "audit-flt-agent"


def test_audit_log_with_date_range(llm_gateway_client, monkeypatch):
    yesterday = (datetime.utcnow() - timedelta(days=1)).isoformat()
    tomorrow = (datetime.utcnow() + timedelta(days=1)).isoformat()
    r = llm_gateway_client.get(
        "/api/v1/admin/llm/audit",
        params={"start_date": yesterday, "end_date": tomorrow, "limit": 5},
    )
    assert r.status_code == 200


def test_provider_health_with_data(llm_gateway_client, api_gateway_client, monkeypatch):
    _create_provider(llm_gateway_client, name=f"h-{uuid.uuid4().hex[:6]}")

    async def fake_get(self, url, *args, **kwargs):
        # simulate a slow but successful upstream
        class _R:
            status_code = 200

            class elapsed:
                @staticmethod
                def total_seconds():
                    return 0.05

        return _R()

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    r = llm_gateway_client.get(
        "/api/v1/admin/llm/health",
        headers=_admin_headers(api_gateway_client),
    )
    assert r.status_code == 200
    body = r.json()
    assert "providers" in body


def test_provider_health_degraded(llm_gateway_client, api_gateway_client, monkeypatch):
    _create_provider(llm_gateway_client, name=f"h-deg-{uuid.uuid4().hex[:6]}")

    async def fake_get(self, url, *args, **kwargs):
        class _R:
            status_code = 200

            class elapsed:
                @staticmethod
                def total_seconds():
                    return 2.0  # > 1 second triggers degraded

        return _R()

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    r = llm_gateway_client.get(
        "/api/v1/admin/llm/health",
        headers=_admin_headers(api_gateway_client),
    )
    assert r.status_code == 200


def test_provider_health_unhealthy(llm_gateway_client, api_gateway_client, monkeypatch):
    _create_provider(llm_gateway_client, name=f"h-unh-{uuid.uuid4().hex[:6]}")

    async def fake_get(self, url, *args, **kwargs):
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    r = llm_gateway_client.get(
        "/api/v1/admin/llm/health",
        headers=_admin_headers(api_gateway_client),
    )
    assert r.status_code == 200


def test_provider_health_bad_status(llm_gateway_client, api_gateway_client, monkeypatch):
    _create_provider(llm_gateway_client, name=f"h-bad-{uuid.uuid4().hex[:6]}")

    async def fake_get(self, url, *args, **kwargs):
        class _R:
            status_code = 503

            class elapsed:
                @staticmethod
                def total_seconds():
                    return 0.1

        return _R()

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    r = llm_gateway_client.get(
        "/api/v1/admin/llm/health",
        headers=_admin_headers(api_gateway_client),
    )
    assert r.status_code == 200
