"""E2E tests for the API gateway (auth, admin, proxy)."""

from __future__ import annotations

import os


def test_login_admin(api_gateway_client):
    r = api_gateway_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": os.environ["AUTH_ADMIN_PASS"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "admin"
    assert body["access_token"]


def test_login_invalid_credentials(api_gateway_client):
    r = api_gateway_client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "wrong"}
    )
    assert r.status_code == 401


def test_login_unknown_user(api_gateway_client):
    r = api_gateway_client.post(
        "/api/v1/auth/login", json={"username": "nobody", "password": "x"}
    )
    assert r.status_code == 401


def test_me_requires_bearer(api_gateway_client):
    r = api_gateway_client.get("/api/v1/auth/me")
    assert r.status_code == 401


def test_me_with_bearer(api_gateway_client, admin_token):
    r = api_gateway_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["sub"] == "admin"
    assert body["role"] == "admin"


def test_admin_health_requires_admin(api_gateway_client, operator_token):
    r = api_gateway_client.get(
        "/api/v1/admin/health",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert r.status_code == 403


def test_admin_health_works(
    api_gateway_client,
    admin_token,
    llm_gateway_client,
    anomaly_client,
    rca_client,
    pdm_client,
    orchestrator_client,
    workflow_client,
    chatops_client,
    reporting_client,
    notification_client,
    simulator_client,
    ingestion_client,
):
    r = api_gateway_client.get(
        "/api/v1/admin/health",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "summary" in body
    assert "services" in body
    assert body["summary"]["total"] >= 10


def test_admin_agents(api_gateway_client, admin_token):
    r = api_gateway_client.get(
        "/api/v1/admin/agents",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "default_config" in body
    assert "agents" in body
    assert len(body["agents"]) >= 5


def test_admin_update_default_llm_config(api_gateway_client, admin_token):
    r = api_gateway_client.put(
        "/api/v1/admin/llm/default",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"provider": "openai-compatible", "model": "gpt-4o-mini"},
    )
    assert r.status_code == 200


def test_admin_update_unknown_agent_404(api_gateway_client, admin_token):
    r = api_gateway_client.put(
        "/api/v1/admin/agents/bogus-agent/config",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"provider": "openai-compatible"},
    )
    assert r.status_code == 404


def test_admin_update_known_agent(api_gateway_client, admin_token):
    r = api_gateway_client.put(
        "/api/v1/admin/agents/rca-agent/config",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"provider": "openai-compatible", "model": "gpt-4o"},
    )
    assert r.status_code == 200


def test_proxy_unknown_section(api_gateway_client):
    r = api_gateway_client.get("/api/v1/bogus_section")
    assert r.status_code == 404


def test_proxy_to_simulator(
    api_gateway_client, simulator_client
):
    r = api_gateway_client.get("/api/v1/machines")
    assert r.status_code == 200
    machines = r.json()
    assert isinstance(machines, list)
    assert len(machines) > 0


def test_proxy_to_anomaly_incidents(
    api_gateway_client, anomaly_client
):
    r = api_gateway_client.get("/api/v1/incidents")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_proxy_to_workflow_engine(api_gateway_client, workflow_client):
    r = api_gateway_client.get("/api/v1/workflows")
    assert r.status_code == 200
    workflows = r.json()
    assert any(w["name"] == "investigation" for w in workflows)


def test_proxy_to_reporting(api_gateway_client, reporting_client):
    r = api_gateway_client.get("/api/v1/reports")
    assert r.status_code == 200


def test_proxy_to_pdm(api_gateway_client, pdm_client, simulator_client, anomaly_client):
    r = api_gateway_client.get("/api/v1/predictions")
    assert r.status_code == 200


# ---------------------------------------------------------------------
# Regression: /api/v1/admin/llm/* must reach the llm-gateway proxy, NOT
# the generic reverse proxy that would 404 with "unknown section admin".
# https://github.com/r2st/forgemind/issues/<llm-admin-404>
# ---------------------------------------------------------------------


def test_proxy_admin_llm_providers(api_gateway_client, admin_token, llm_gateway_client):
    """The LLM admin SPA calls /admin/llm/providers on mount."""
    r = api_gateway_client.get(
        "/api/v1/admin/llm/providers",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text
    # Must NOT be the generic-proxy 404.
    assert "unknown section" not in r.text


def test_proxy_admin_llm_models(api_gateway_client, admin_token, llm_gateway_client):
    r = api_gateway_client.get(
        "/api/v1/admin/llm/models",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text


def test_proxy_admin_llm_usage(api_gateway_client, admin_token, llm_gateway_client):
    r = api_gateway_client.get(
        "/api/v1/admin/llm/usage",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text


def test_proxy_admin_llm_no_path(api_gateway_client, admin_token, llm_gateway_client):
    """/api/v1/admin/llm (no trailing path) must still hit the proxy and
    NOT fall through to the generic '/api/v1/{section}/{path:path}'
    handler that returns 'unknown section admin'."""
    r = api_gateway_client.get(
        "/api/v1/admin/llm",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    # Llm-gateway has no handler for /api/v1/admin/llm itself, so we
    # expect 404 or 405 from upstream — but NEVER "unknown section admin".
    assert "unknown section" not in r.text
    assert r.status_code in (200, 404, 405)


def test_proxy_admin_llm_trailing_slash(api_gateway_client, admin_token, llm_gateway_client):
    """/api/v1/admin/llm/ (trailing slash, empty path) must also bypass
    the generic proxy."""
    r = api_gateway_client.get(
        "/api/v1/admin/llm/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert "unknown section" not in r.text
    assert r.status_code in (200, 404, 405)
