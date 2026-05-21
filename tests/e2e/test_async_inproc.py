"""Async in-process tests using httpx ASGITransport so coverage can
trace into request handlers (TestClient's thread pool obscures them)."""

from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager

import httpx
import pytest


@asynccontextmanager
async def _app_client(app):
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


@pytest.mark.asyncio
async def test_async_provider_full_crud(service_apps):
    app = service_apps["llm-gateway"]
    async with _app_client(app) as c:
        s = uuid.uuid4().hex[:6]
        # Create.
        r = await c.post(
            "/api/v1/admin/llm/providers",
            json={
                "name": f"ap-{s}",
                "kind": "cloud",
                "provider_type": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
                "enabled": True,
                "provider_metadata": {"x": 1},
            },
        )
        assert r.status_code == 200
        prov = r.json()

        # Login as admin via api-gateway to fetch a token.
        api_app = service_apps["api-gateway"]
        async with _app_client(api_app) as api:
            login = await api.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": os.environ["AUTH_ADMIN_PASS"]},
            )
            token = login.json()["access_token"]

        hdr = {"Authorization": f"Bearer {token}"}

        # Get by ID.
        r = await c.get(f"/api/v1/admin/llm/providers/{prov['id']}", headers=hdr)
        assert r.status_code == 200
        # List.
        r = await c.get("/api/v1/admin/llm/providers", headers=hdr)
        assert r.status_code == 200
        # Update.
        r = await c.put(
            f"/api/v1/admin/llm/providers/{prov['id']}",
            json={"name": f"ap-renamed-{s}"},
        )
        assert r.status_code == 200
        # Update each field.
        for body in [
            {"base_url": "https://api.example.com/v1"},
            {"api_key": "sk-new"},
            {"clear_api_key": True},
            {"auth_header": "X-Custom"},
            {"enabled": False},
            {"provider_metadata": {"region": "us-west"}},
            {"provider_type": "ollama"},
            {"kind": "self_hosted"},
        ]:
            rr = await c.put(f"/api/v1/admin/llm/providers/{prov['id']}", json=body)
            assert rr.status_code == 200, (body, rr.text)
        # Delete.
        r = await c.delete(f"/api/v1/admin/llm/providers/{prov['id']}")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_async_model_full_crud(service_apps):
    app = service_apps["llm-gateway"]
    async with _app_client(app) as c:
        s = uuid.uuid4().hex[:6]
        # Create provider.
        r = await c.post(
            "/api/v1/admin/llm/providers",
            json={
                "name": f"amp-{s}",
                "kind": "cloud",
                "provider_type": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "k",
                "enabled": True,
                "provider_metadata": {},
            },
        )
        prov_id = r.json()["id"]
        # Create model.
        r = await c.post(
            "/api/v1/admin/llm/models",
            json={
                "provider_id": prov_id,
                "model_name": f"am-{s}",
                "display_name": "x",
                "context_window": 1000,
                "max_output_tokens": 500,
                "cost_per_input_token": 1e-6,
                "cost_per_output_token": 2e-6,
                "capabilities": {"reasoning": True, "vision": False, "tools": True, "streaming": True},
                "enabled": True,
            },
        )
        assert r.status_code == 200
        m = r.json()
        # Get by ID.
        r = await c.get(f"/api/v1/admin/llm/models/{m['id']}")
        assert r.status_code == 200
        # Update each field.
        for body in [
            {"display_name": "new"},
            {"context_window": 2000},
            {"max_output_tokens": 1000},
            {"cost_per_input_token": 3e-6},
            {"cost_per_output_token": 4e-6},
            {"capabilities": {"reasoning": False}},
            {"enabled": False},
        ]:
            rr = await c.put(f"/api/v1/admin/llm/models/{m['id']}", json=body)
            assert rr.status_code == 200, (body, rr.text)
        # Delete.
        r = await c.delete(f"/api/v1/admin/llm/models/{m['id']}")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_async_agent_routing(service_apps):
    app = service_apps["llm-gateway"]
    async with _app_client(app) as c:
        s = uuid.uuid4().hex[:6]
        prov = (
            await c.post(
                "/api/v1/admin/llm/providers",
                json={
                    "name": f"ar-{s}",
                    "kind": "cloud",
                    "provider_type": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "k",
                    "enabled": True,
                    "provider_metadata": {},
                },
            )
        ).json()
        m1 = (
            await c.post(
                "/api/v1/admin/llm/models",
                json={
                    "provider_id": prov["id"],
                    "model_name": f"m1-{s}",
                    "display_name": "1",
                    "context_window": 1,
                    "max_output_tokens": 1,
                    "cost_per_input_token": 0,
                    "cost_per_output_token": 0,
                    "capabilities": {},
                    "enabled": True,
                },
            )
        ).json()
        m2 = (
            await c.post(
                "/api/v1/admin/llm/models",
                json={
                    "provider_id": prov["id"],
                    "model_name": f"m2-{s}",
                    "display_name": "2",
                    "context_window": 1,
                    "max_output_tokens": 1,
                    "cost_per_input_token": 0,
                    "cost_per_output_token": 0,
                    "capabilities": {},
                    "enabled": True,
                },
            )
        ).json()

        agent = f"ar-{s}"
        r = await c.put(
            f"/api/v1/admin/llm/agents/{agent}/routing",
            json={"primary_model_id": m1["id"]},
        )
        assert r.status_code == 200, r.text

        # Update each field.
        for body in [
            {"primary_model_id": m2["id"]},
            {"fallback_model_ids": [m1["id"]]},
            {"temperature": 0.9},
            {"max_tokens": 500},
            {"reasoning_mode": True},
            {"timeout_s": 30.0},
            {"retry_policy": "fixed"},
            {"routing_strategy": "cheapest"},
            {"quota": {"max_requests_per_hour": 5}},
        ]:
            rr = await c.put(f"/api/v1/admin/llm/agents/{agent}/routing", json=body)
            assert rr.status_code == 200

        # Get fallback chain.
        rr = await c.get(f"/api/v1/admin/llm/agents/{agent}/fallback")
        assert rr.status_code == 200
        # Update fallback chain.
        rr = await c.put(
            f"/api/v1/admin/llm/agents/{agent}/fallback",
            json={"fallback_model_ids": [m1["id"], m2["id"]]},
        )
        assert rr.status_code == 200


@pytest.mark.asyncio
async def test_async_health_endpoints(service_apps):
    """Hit usage/cost/audit with proper data."""
    app = service_apps["llm-gateway"]
    api_app = service_apps["api-gateway"]
    async with _app_client(api_app) as api:
        login = await api.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": os.environ["AUTH_ADMIN_PASS"]},
        )
        token = login.json()["access_token"]
    hdr = {"Authorization": f"Bearer {token}"}

    async with _app_client(app) as c:
        # Usage, cost, audit endpoints.
        assert (await c.get("/api/v1/admin/llm/usage")).status_code == 200
        assert (await c.get("/api/v1/admin/llm/cost")).status_code == 200
        assert (await c.get("/api/v1/admin/llm/audit")).status_code == 200
        assert (await c.get("/api/v1/admin/llm/health", headers=hdr)).status_code == 200
