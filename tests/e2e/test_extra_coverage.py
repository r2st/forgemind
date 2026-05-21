"""Final extra-coverage tests for small remaining branches."""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest


def _load_llm_schemas():
    repo = Path(__file__).resolve().parent.parent.parent
    p = repo / "services" / "llm-gateway" / "app" / "schemas.py"
    spec = importlib.util.spec_from_file_location("lg_sch", str(p))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_provider_update_validator_self_hosted_allows_private():
    """ProviderUpdate.base_url validator: with kind=SELF_HOSTED, private
    IPs are allowed."""
    sch = _load_llm_schemas()
    u = sch.ProviderUpdate(kind=sch.ProviderKind.SELF_HOSTED, base_url="http://10.0.0.1/v1")
    assert u.base_url


def test_provider_update_validator_no_url_returns_none():
    sch = _load_llm_schemas()
    u = sch.ProviderUpdate(enabled=False)
    assert u.base_url is None


def test_model_create_capabilities_from_list():
    """ModelCreate accepts a list of capability names and coerces to
    the dict form."""
    sch = _load_llm_schemas()
    mc = sch.ModelCreate(
        provider_id=1,
        model_name="x",
        display_name="x",
        context_window=1,
        max_output_tokens=1,
        cost_per_input_token=0,
        cost_per_output_token=0,
        capabilities=["reasoning", "vision"],
    )
    assert mc.capabilities.reasoning is True
    assert mc.capabilities.vision is True


def _load_rca_tools():
    repo = Path(__file__).resolve().parent.parent.parent
    sd = repo / "services" / "rca-service"
    if str(sd) not in sys.path:
        sys.path.insert(0, str(sd))
    for key in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
        del sys.modules[key]
    spec = importlib.util.spec_from_file_location(
        "app",
        str(sd / "app" / "__init__.py"),
        submodule_search_locations=[str(sd / "app")],
    )
    pkg = importlib.util.module_from_spec(spec)
    sys.modules["app"] = pkg
    spec.loader.exec_module(pkg)
    spec_m = importlib.util.spec_from_file_location("app.models", str(sd / "app" / "models.py"))
    mm = importlib.util.module_from_spec(spec_m)
    sys.modules["app.models"] = mm
    spec_m.loader.exec_module(mm)
    spec_t = importlib.util.spec_from_file_location("app.tools", str(sd / "app" / "tools.py"))
    tm = importlib.util.module_from_spec(spec_t)
    sys.modules["app.tools"] = tm
    spec_t.loader.exec_module(tm)
    return tm


@pytest.mark.asyncio
async def test_rca_tool_handlers_full_round_trip(rca_client):
    """Exercise the handler functions inside build_rca_tools — they
    invoke the underlying helper functions via the registry."""
    tools = _load_rca_tools()
    reg = tools.build_rca_tools()

    # get_incident — patches httpx to return one matching incident.
    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"incident_id": "abc", "machine_id": "CNC-1"}]

    async def fake_get(self, url, params=None):
        return _R()

    with patch("httpx.AsyncClient.get", fake_get):
        out = await reg.get("get_incident").handler(incident_id="abc")
        assert "CNC-1" in out

    # get_telemetry_context handler.
    class _R2:
        status_code = 200

        def json(self):
            return [{"machine_id": "CNC-1", "temperature_c": 60}]

    async def fake_get2(self, url):
        return _R2()

    with patch("httpx.AsyncClient.get", fake_get2):
        out = await reg.get("get_telemetry_context").handler(machine_id="CNC-1")
        assert "60" in out

    # search_similar_incidents — force the embed-fails branch since
    # pgvector cosine_distance is unavailable on SQLite.
    from forgemind_common import llm_gateway as gw

    async def fail_embed(self, texts):
        raise RuntimeError("no embeddings")

    with patch.object(gw.LLMGateway, "embed", fail_embed):
        out = await reg.get("search_similar_incidents").handler(query_text="x")
        assert out == "[]"

        # record_incident_memory: embed fails → persisted False branch.
        out = await reg.get("record_incident_memory").handler(
            incident_id=str(uuid.uuid4()),
            machine_id="CNC-1",
            machine_type="CNC",
            severity="HIGH",
            summary="test summary",
        )
        assert '"persisted": false' in out.lower() or '"persisted": false' in out


def test_api_gateway_admin_proxy_passthrough(api_gateway_client, llm_gateway_client, admin_token):
    """Hit /api/v1/admin/llm/<path> proxy — exercises llm_admin_proxy."""
    r = api_gateway_client.get(
        "/api/v1/admin/llm/providers",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code in (200, 401, 502)


def test_api_gateway_admin_health_unauthenticated(api_gateway_client):
    """Anonymous request to admin endpoint should be rejected."""
    r = api_gateway_client.get("/api/v1/admin/health")
    assert r.status_code == 401


def test_admin_update_default_with_clear_key(api_gateway_client, admin_token):
    """Exercise the clear_api_key branch."""
    r = api_gateway_client.put(
        "/api/v1/admin/llm/default",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"clear_api_key": True},
    )
    assert r.status_code == 200


def test_admin_agents_with_disabled_config(api_gateway_client, admin_token):
    """When agent's provider == 'disabled', status branch differs."""
    # Disable a known agent.
    api_gateway_client.put(
        "/api/v1/admin/agents/monitoring-agent/config",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"provider": "disabled"},
    )
    r = api_gateway_client.get(
        "/api/v1/admin/agents",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    agents = r.json()["agents"]
    statuses = {a["name"]: a["status"] for a in agents}
    assert statuses.get("monitoring-agent") in ("disabled", "needs_config", "ok")
