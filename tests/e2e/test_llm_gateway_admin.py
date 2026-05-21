"""Deep CRUD + admin coverage for the LLM Gateway service."""

from __future__ import annotations

import os


def _admin_headers(api_gateway_client):
    r = api_gateway_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": os.environ["AUTH_ADMIN_PASS"]},
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create_provider(client, name="ag-prov"):
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


def _create_model(client, provider_id, name="m-1"):
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


def test_provider_duplicate_name_rejected(llm_gateway_client):
    _create_provider(llm_gateway_client, name="dup-prov")
    r = llm_gateway_client.post(
        "/api/v1/admin/llm/providers",
        json={
            "name": "dup-prov",
            "kind": "cloud",
            "provider_type": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "enabled": True,
            "provider_metadata": {},
        },
    )
    assert r.status_code == 400


def test_provider_get_by_id(llm_gateway_client, api_gateway_client):
    p = _create_provider(llm_gateway_client, name="get-prov")
    r = llm_gateway_client.get(
        f"/api/v1/admin/llm/providers/{p['id']}",
        headers=_admin_headers(api_gateway_client),
    )
    assert r.status_code == 200
    assert r.json()["name"] == "get-prov"


def test_provider_get_not_found(llm_gateway_client, api_gateway_client):
    r = llm_gateway_client.get(
        "/api/v1/admin/llm/providers/9999",
        headers=_admin_headers(api_gateway_client),
    )
    assert r.status_code == 404


def test_provider_update(llm_gateway_client):
    p = _create_provider(llm_gateway_client, name="upd-prov")
    r = llm_gateway_client.put(
        f"/api/v1/admin/llm/providers/{p['id']}",
        json={"enabled": False},
    )
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is False


def test_provider_update_not_found(llm_gateway_client):
    r = llm_gateway_client.put(
        "/api/v1/admin/llm/providers/9999",
        json={"enabled": False},
    )
    assert r.status_code == 404


def test_provider_delete(llm_gateway_client):
    p = _create_provider(llm_gateway_client, name="del-prov")
    r = llm_gateway_client.delete(f"/api/v1/admin/llm/providers/{p['id']}")
    assert r.status_code == 200
    r = llm_gateway_client.delete(f"/api/v1/admin/llm/providers/{p['id']}")
    assert r.status_code == 404


def test_model_get_by_id(llm_gateway_client):
    p = _create_provider(llm_gateway_client, name="mget-prov")
    m = _create_model(llm_gateway_client, p["id"], name="m-get")
    r = llm_gateway_client.get(f"/api/v1/admin/llm/models/{m['id']}")
    assert r.status_code == 200
    assert r.json()["model_name"] == "m-get"


def test_model_get_not_found(llm_gateway_client):
    r = llm_gateway_client.get("/api/v1/admin/llm/models/9999")
    assert r.status_code == 404


def test_model_update(llm_gateway_client):
    p = _create_provider(llm_gateway_client, name="mu-prov")
    m = _create_model(llm_gateway_client, p["id"], name="m-upd")
    r = llm_gateway_client.put(
        f"/api/v1/admin/llm/models/{m['id']}",
        json={"enabled": False, "max_output_tokens": 2048},
    )
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert r.json()["max_output_tokens"] == 2048


def test_model_update_not_found(llm_gateway_client):
    r = llm_gateway_client.put(
        "/api/v1/admin/llm/models/9999",
        json={"enabled": False},
    )
    assert r.status_code == 404


def test_model_delete(llm_gateway_client):
    p = _create_provider(llm_gateway_client, name="md-prov")
    m = _create_model(llm_gateway_client, p["id"], name="m-del")
    r = llm_gateway_client.delete(f"/api/v1/admin/llm/models/{m['id']}")
    assert r.status_code == 200
    r = llm_gateway_client.delete(f"/api/v1/admin/llm/models/{m['id']}")
    assert r.status_code == 404


def test_create_model_invalid_provider(llm_gateway_client):
    r = llm_gateway_client.post(
        "/api/v1/admin/llm/models",
        json={
            "provider_id": 9999,
            "model_name": "x",
            "display_name": "x",
            "context_window": 100,
            "max_output_tokens": 100,
            "cost_per_input_token": 0,
            "cost_per_output_token": 0,
            "capabilities": {},
            "enabled": True,
        },
    )
    assert r.status_code in (400, 404)


def test_agent_routing_default(llm_gateway_client):
    r = llm_gateway_client.get("/api/v1/admin/llm/agents/never-seen/routing")
    assert r.status_code == 200
    assert r.json()["agent_name"] == "never-seen"


def test_agent_routing_create_and_update(llm_gateway_client):
    p = _create_provider(llm_gateway_client, name="ar-prov")
    m = _create_model(llm_gateway_client, p["id"], name="m-ar")
    r = llm_gateway_client.put(
        "/api/v1/admin/llm/agents/test-agent/routing",
        json={
            "primary_model_id": m["id"],
            "fallback_model_ids": [],
            "temperature": 0.3,
            "max_tokens": 500,
            "routing_strategy": "cheapest",
            "quota": {"max_requests_per_hour": 1000},
        },
    )
    assert r.status_code == 200, r.text
    # Re-read.
    r2 = llm_gateway_client.get("/api/v1/admin/llm/agents/test-agent/routing")
    assert r2.status_code == 200
    assert r2.json()["temperature"] == 0.3

    # Update.
    r3 = llm_gateway_client.put(
        "/api/v1/admin/llm/agents/test-agent/routing",
        json={"temperature": 0.5, "max_tokens": 1024, "retry_policy": "linear"},
    )
    assert r3.status_code == 200
    assert r3.json()["temperature"] == 0.5


def test_agent_routing_create_missing_primary(llm_gateway_client):
    r = llm_gateway_client.put(
        "/api/v1/admin/llm/agents/missing-primary/routing",
        json={"fallback_model_ids": []},
    )
    assert r.status_code == 400


def test_fallback_chain_endpoints(llm_gateway_client):
    p = _create_provider(llm_gateway_client, name="fb-prov")
    m1 = _create_model(llm_gateway_client, p["id"], name="m-fb-1")
    m2 = _create_model(llm_gateway_client, p["id"], name="m-fb-2")
    llm_gateway_client.put(
        "/api/v1/admin/llm/agents/fb-agent/routing",
        json={"primary_model_id": m1["id"], "fallback_model_ids": []},
    )
    r = llm_gateway_client.get("/api/v1/admin/llm/agents/fb-agent/fallback")
    assert r.status_code == 200
    body = r.json()
    assert body["fallback_model_ids"] == []
    # update
    r = llm_gateway_client.put(
        "/api/v1/admin/llm/agents/fb-agent/fallback",
        json={"fallback_model_ids": [m2["id"]]},
    )
    assert r.status_code == 200
    r = llm_gateway_client.get("/api/v1/admin/llm/agents/fb-agent/fallback")
    assert m2["id"] in r.json()["fallback_model_ids"]


def test_fallback_get_unknown_agent(llm_gateway_client):
    r = llm_gateway_client.get("/api/v1/admin/llm/agents/no-agent/fallback")
    assert r.status_code == 200
    assert r.json()["fallback_model_ids"] == []


def test_v1_models_lists_enabled(llm_gateway_client):
    p = _create_provider(llm_gateway_client, name="mlist-prov")
    _create_model(llm_gateway_client, p["id"], name="m-mlist")
    r = llm_gateway_client.get("/v1/models")
    assert r.status_code == 200
    body = r.json()
    assert "data" in body
    assert any(m["id"] == "m-mlist" for m in body["data"])
