"""E2E tests for the LLM-gateway service itself (admin + inference)."""

from __future__ import annotations


def _admin_headers(api_gateway_client) -> dict[str, str]:
    import os

    r = api_gateway_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": os.environ["AUTH_ADMIN_PASS"]},
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_health(llm_gateway_client):
    r = llm_gateway_client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"
    r = llm_gateway_client.get("/healthz")
    assert r.status_code == 200


def test_list_providers_empty(llm_gateway_client, api_gateway_client):
    r = llm_gateway_client.get(
        "/api/v1/admin/llm/providers",
        headers=_admin_headers(api_gateway_client),
    )
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_list_providers_requires_admin(llm_gateway_client):
    r = llm_gateway_client.get("/api/v1/admin/llm/providers")
    assert r.status_code == 401


def test_create_provider(llm_gateway_client):
    payload = {
        "name": "e2e-openai-create",
        "kind": "cloud",
        "provider_type": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-test",
        "enabled": True,
        "provider_metadata": {},
    }
    r = llm_gateway_client.post("/api/v1/admin/llm/providers", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "e2e-openai-create"
    # Raw API key must NOT come back.
    assert body.get("api_key_preview", "") != "sk-test"
    assert body.get("api_key_set") is True


def test_create_and_list_model(llm_gateway_client, api_gateway_client):
    prov = llm_gateway_client.post(
        "/api/v1/admin/llm/providers",
        json={
            "name": "e2e-openai-model",
            "kind": "cloud",
            "provider_type": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "enabled": True,
            "provider_metadata": {},
        },
    ).json()
    r = llm_gateway_client.post(
        "/api/v1/admin/llm/models",
        json={
            "provider_id": prov["id"],
            "model_name": "gpt-4o-mini-test",
            "display_name": "GPT-4o mini (test)",
            "context_window": 128000,
            "max_output_tokens": 4096,
            "cost_per_input_token": 0.0000015,
            "cost_per_output_token": 0.000006,
            "capabilities": {"reasoning": True, "tools": True},
            "enabled": True,
        },
    )
    assert r.status_code == 200, r.text
    listed = llm_gateway_client.get(
        "/api/v1/admin/llm/models",
        headers=_admin_headers(api_gateway_client),
    ).json()
    assert isinstance(listed, list)
    assert any(m["model_name"] == "gpt-4o-mini-test" for m in listed)


def test_chat_completions_requires_x_agent(llm_gateway_client):
    r = llm_gateway_client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert r.status_code == 400
    assert "X-Agent" in r.text


def test_audit_endpoint(llm_gateway_client):
    r = llm_gateway_client.get("/api/v1/admin/llm/audit")
    assert r.status_code == 200


def test_health_endpoint(llm_gateway_client, api_gateway_client):
    r = llm_gateway_client.get(
        "/api/v1/admin/llm/health",
        headers=_admin_headers(api_gateway_client),
    )
    assert r.status_code == 200


def test_usage_endpoint(llm_gateway_client):
    r = llm_gateway_client.get("/api/v1/admin/llm/usage")
    assert r.status_code == 200


def test_cost_endpoint(llm_gateway_client):
    r = llm_gateway_client.get("/api/v1/admin/llm/cost")
    assert r.status_code == 200


def test_v1_models_open(llm_gateway_client):
    # /v1/models is the OpenAI-compatible endpoint (no auth required).
    r = llm_gateway_client.get("/v1/models")
    assert r.status_code == 200
