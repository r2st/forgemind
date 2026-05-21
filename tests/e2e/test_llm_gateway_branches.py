"""Cover the remaining branchy CRUD paths in LLM Gateway main.py."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

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


def test_provider_update_each_field(llm_gateway_client):
    """Each body gets a fresh provider so update branches are walked in
    isolation without compounding state."""
    bodies = [
        {"name_suffix": "n", "body": {"name": "renamed-name"}},
        {"name_suffix": "b", "body": {"base_url": "https://api.example.com/v1"}},
        {"name_suffix": "k", "body": {"api_key": "sk-new"}},
        {"name_suffix": "c", "body": {"clear_api_key": True}},
        {"name_suffix": "a", "body": {"auth_header": "X-Custom"}},
        {"name_suffix": "e", "body": {"enabled": False}},
        {"name_suffix": "m", "body": {"provider_metadata": {"region": "us-west"}}},
        {"name_suffix": "p", "body": {"provider_type": "ollama"}},
    ]
    for entry in bodies:
        s = uuid.uuid4().hex[:6]
        create_resp = llm_gateway_client.post(
            "/api/v1/admin/llm/providers",
            json={
                "name": f"upd-{entry['name_suffix']}-{s}",
                "kind": "cloud",
                "provider_type": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
                "enabled": True,
                "provider_metadata": {},
            },
        )
        assert create_resp.status_code == 200, create_resp.text
        p = create_resp.json()
        body = dict(entry["body"])
        if "name" in body:
            body["name"] = f"renamed-{s}"
        r = llm_gateway_client.put(
            f"/api/v1/admin/llm/providers/{p['id']}",
            json=body,
        )
        assert r.status_code == 200, (entry, r.text)


def test_provider_update_self_hosted_with_private_url(llm_gateway_client):
    """Updating kind=self_hosted should allow private IPs in the URL."""
    s = uuid.uuid4().hex[:6]
    p = _create_provider(llm_gateway_client, name=f"sh-{s}")
    r = llm_gateway_client.put(
        f"/api/v1/admin/llm/providers/{p['id']}",
        json={"kind": "self_hosted", "base_url": "http://10.0.0.1:8000/v1"},
    )
    assert r.status_code == 200, r.text


def test_provider_update_bad_url_rejected(llm_gateway_client):
    s = uuid.uuid4().hex[:6]
    p = _create_provider(llm_gateway_client, name=f"bu-{s}")
    r = llm_gateway_client.put(
        f"/api/v1/admin/llm/providers/{p['id']}",
        json={"base_url": "ftp://bad-protocol/v1"},
    )
    assert r.status_code in (400, 422)


def test_model_update_each_field(llm_gateway_client):
    s = uuid.uuid4().hex[:6]
    p = _create_provider(llm_gateway_client, name=f"mu-p-{s}")
    m = _create_model(llm_gateway_client, p["id"], name=f"mu-m-{s}")
    for body in [
        {"display_name": "new display"},
        {"context_window": 8192},
        {"max_output_tokens": 2048},
        {"cost_per_input_token": 5e-6},
        {"cost_per_output_token": 7e-6},
        {"capabilities": {"reasoning": True}},
        {"enabled": False},
    ]:
        r = llm_gateway_client.put(f"/api/v1/admin/llm/models/{m['id']}", json=body)
        assert r.status_code == 200


def test_agent_routing_update_each_field(llm_gateway_client):
    s = uuid.uuid4().hex[:6]
    p = _create_provider(llm_gateway_client, name=f"ar-{s}")
    m1 = _create_model(llm_gateway_client, p["id"], name=f"m1-{s}")
    m2 = _create_model(llm_gateway_client, p["id"], name=f"m2-{s}")
    agent = f"branch-agent-{s}"
    llm_gateway_client.put(
        f"/api/v1/admin/llm/agents/{agent}/routing",
        json={"primary_model_id": m1["id"]},
    )

    for body in [
        {"primary_model_id": m2["id"]},
        {"fallback_model_ids": [m1["id"]]},
        {"temperature": 0.9},
        {"max_tokens": 2048},
        {"reasoning_mode": True},
        {"timeout_s": 30.0},
        {"retry_policy": "fixed_backoff"},
        {"routing_strategy": "lowest_latency"},
        {"quota": {"max_requests_per_hour": 10}},
    ]:
        r = llm_gateway_client.put(f"/api/v1/admin/llm/agents/{agent}/routing", json=body)
        assert r.status_code == 200


def test_quota_token_limit_exceeded(llm_gateway_client, monkeypatch):
    s = uuid.uuid4().hex[:6]
    p = _create_provider(llm_gateway_client, name=f"tk-{s}")
    m = _create_model(llm_gateway_client, p["id"], name=f"tk-m-{s}")
    agent = f"tk-agent-{s}"
    llm_gateway_client.put(
        f"/api/v1/admin/llm/agents/{agent}/routing",
        json={
            "primary_model_id": m["id"],
            "quota": {"max_tokens_per_hour": 5},
        },
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
                    "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
                },
            )
        return await httpx.AsyncClient.post(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    # First call consumes 60 tokens (way > 5).
    r1 = llm_gateway_client.post(
        "/v1/chat/completions",
        headers={"X-Agent": agent},
        json={"model": "auto", "messages": [{"role": "user", "content": "x"}]},
    )
    assert r1.status_code == 200
    # Second call should hit the token quota.
    r2 = llm_gateway_client.post(
        "/v1/chat/completions",
        headers={"X-Agent": agent},
        json={"model": "auto", "messages": [{"role": "user", "content": "x"}]},
    )
    assert r2.status_code == 429


def test_quota_empty_dict_passes_through(llm_gateway_client, monkeypatch):
    s = uuid.uuid4().hex[:6]
    p = _create_provider(llm_gateway_client, name=f"ne-{s}")
    m = _create_model(llm_gateway_client, p["id"], name=f"ne-m-{s}")
    agent = f"ne-agent-{s}"
    # Empty quota dict — both limits None — should NOT block.
    llm_gateway_client.put(
        f"/api/v1/admin/llm/agents/{agent}/routing",
        json={"primary_model_id": m["id"], "quota": {}},
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
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )
        return await httpx.AsyncClient.post(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    r = llm_gateway_client.post(
        "/v1/chat/completions",
        headers={"X-Agent": agent},
        json={"model": "auto", "messages": [{"role": "user", "content": "x"}]},
    )
    assert r.status_code == 200


def test_jwt_invalid_format_falls_through(llm_gateway_client, monkeypatch):
    """A malformed bearer token should be accepted but logged as anonymous."""
    s = uuid.uuid4().hex[:6]
    p = _create_provider(llm_gateway_client, name=f"jw-{s}")
    m = _create_model(llm_gateway_client, p["id"], name=f"jw-m-{s}")
    agent = f"jw-agent-{s}"
    llm_gateway_client.put(
        f"/api/v1/admin/llm/agents/{agent}/routing",
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
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )
        return await httpx.AsyncClient.post(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    r = llm_gateway_client.post(
        "/v1/chat/completions",
        headers={"X-Agent": agent, "Authorization": "Bearer not-a-real-jwt"},
        json={"model": "auto", "messages": [{"role": "user", "content": "x"}]},
    )
    assert r.status_code == 200


def test_chat_completions_provider_failure(llm_gateway_client, monkeypatch):
    """Provider failure should be wrapped as 500 by the route handler."""
    s = uuid.uuid4().hex[:6]
    p = _create_provider(llm_gateway_client, name=f"pf-{s}")
    m = _create_model(llm_gateway_client, p["id"], name=f"pf-m-{s}")
    agent = f"pf-agent-{s}"
    llm_gateway_client.put(
        f"/api/v1/admin/llm/agents/{agent}/routing",
        json={"primary_model_id": m["id"]},
    )

    async def fake_post(self, url, *args, **kwargs):
        if "api.openai.com" in url:
            return httpx.Response(500, json={"error": "down"})
        return await httpx.AsyncClient.post(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    r = llm_gateway_client.post(
        "/v1/chat/completions",
        headers={"X-Agent": agent},
        json={"model": "auto", "messages": [{"role": "user", "content": "x"}]},
    )
    assert r.status_code in (500, 502)


def test_jwt_extract_invalid_returns_none():
    """Direct unit test of extract_user_from_jwt."""
    import importlib.util
    from pathlib import Path
    import sys

    repo = Path(__file__).resolve().parent.parent.parent
    p = repo / "services" / "llm-gateway"
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
    for key in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
        del sys.modules[key]
    spec = importlib.util.spec_from_file_location(
        "app",
        str(p / "app" / "__init__.py"),
        submodule_search_locations=[str(p / "app")],
    )
    app_pkg = importlib.util.module_from_spec(spec)
    sys.modules["app"] = app_pkg
    spec.loader.exec_module(app_pkg)
    spec_m = importlib.util.spec_from_file_location("app.main", str(p / "app" / "main.py"))
    m = importlib.util.module_from_spec(spec_m)
    sys.modules["app.main"] = m
    spec_m.loader.exec_module(m)

    assert m.extract_user_from_jwt(None) is None
    assert m.extract_user_from_jwt("Bearer not-a-jwt") is None


