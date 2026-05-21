"""Exercise the tool handlers in ai-orchestrator/agents.py and supervisor.py,
plus the chatops-service tool handlers."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


def _load_module(service: str, mod_name: str):
    """Load a service submodule by absolute file path."""
    repo = Path(__file__).resolve().parent.parent.parent
    svc_dir = repo / "services" / service
    svc_app = svc_dir / "app"
    if str(svc_dir) not in sys.path:
        sys.path.insert(0, str(svc_dir))

    # Reset 'app' namespace.
    for key in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
        del sys.modules[key]

    spec_app = importlib.util.spec_from_file_location(
        "app",
        str(svc_app / "__init__.py"),
        submodule_search_locations=[str(svc_app)],
    )
    app_pkg = importlib.util.module_from_spec(spec_app)
    sys.modules["app"] = app_pkg
    spec_app.loader.exec_module(app_pkg)

    spec = importlib.util.spec_from_file_location(
        f"app.{mod_name}", str(svc_app / f"{mod_name}.py")
    )
    m = importlib.util.module_from_spec(spec)
    sys.modules[f"app.{mod_name}"] = m
    spec.loader.exec_module(m)
    return m


# ---------------------------------------------------------------------
# ai-orchestrator/agents.py
# ---------------------------------------------------------------------


@pytest.fixture
def agents_mod():
    return _load_module("ai-orchestrator", "agents")


@pytest.mark.asyncio
async def test_http_helpers(agents_mod):
    # Stub the httpx.AsyncClient that runs inside _http_get/_http_post.
    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    async def fake_get(self, url, params=None):
        return _R()

    async def fake_post(self, url, json=None):
        return _R()

    with patch("httpx.AsyncClient.get", fake_get), patch(
        "httpx.AsyncClient.post", fake_post
    ):
        out = await agents_mod._http_get("http://x/y")
        assert out == {"ok": True}
        out = await agents_mod._http_post("http://x/y", {})
        assert out == {"ok": True}


@pytest.mark.asyncio
async def test_monitoring_tools(agents_mod):
    reg = agents_mod._monitoring_tools()
    list_inc = reg.get("list_recent_incidents")
    snap = reg.get("get_machine_snapshot")

    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"a": 1}]

    async def fake_get(self, url, params=None):
        return _R()

    with patch("httpx.AsyncClient.get", fake_get):
        out = await list_inc.handler(machine_id="CNC-1", severity="HIGH", limit=10)
        assert "a" in out
        out2 = await snap.handler()
        assert "a" in out2


@pytest.mark.asyncio
async def test_pdm_tools(agents_mod):
    reg = agents_mod._pdm_tools()
    rim = reg.get("recent_incidents_for_machine")
    snap = reg.get("get_machine_snapshot")

    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"x": 1}]

    async def fake_get(self, url, params=None):
        return _R()

    with patch("httpx.AsyncClient.get", fake_get):
        assert "x" in await rim.handler(machine_id="m", limit=5)
        assert "x" in await snap.handler()


@pytest.mark.asyncio
async def test_opt_tools(agents_mod):
    reg = agents_mod._opt_tools()

    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"y": 2}]

    async def fake_get(self, url, params=None):
        return _R()

    with patch("httpx.AsyncClient.get", fake_get):
        assert "y" in await reg.get("get_machine_snapshot").handler()
        assert "y" in await reg.get("list_recent_incidents").handler(limit=10)


@pytest.mark.asyncio
async def test_reporting_tools(agents_mod):
    reg = agents_mod._reporting_tools()

    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"z": 3}]

    async def fake_get(self, url, params=None):
        return _R()

    with patch("httpx.AsyncClient.get", fake_get):
        assert "z" in await reg.get("list_recent_incidents").handler(limit=20)
        assert "z" in await reg.get("list_recent_rca").handler(limit=5)


@pytest.mark.asyncio
async def test_call_rca_service(agents_mod):
    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"report_id": "abc"}

    async def fake_post(self, url, json=None):
        return _R()

    with patch("httpx.AsyncClient.post", fake_post):
        out = await agents_mod.call_rca_service("inc-1")
        assert out == {"report_id": "abc"}
        out2 = await agents_mod.call_rca_service("inc-2", extra_context="more")
        assert out2 == {"report_id": "abc"}


def test_specialist_registry_built(agents_mod):
    reg = agents_mod.build_specialist_registry()
    assert {"monitoring", "predictive_maintenance", "production_optimization", "reporting"} <= set(reg.keys())


# ---------------------------------------------------------------------
# ai-orchestrator/supervisor.py
# ---------------------------------------------------------------------


@pytest.fixture
def supervisor_mod():
    # supervisor.py imports from agents — load both into the same `app`
    # namespace.
    _load_module("ai-orchestrator", "agents")
    return _load_module("ai-orchestrator", "supervisor")


@pytest.mark.asyncio
async def test_supervisor_delegate_to_rca_missing_id(supervisor_mod):
    rt = supervisor_mod.build_supervisor()
    delegate = rt.tools.get("delegate_to_agent")
    out = await delegate.handler(agent="rca", task="x")
    assert "error" in out


@pytest.mark.asyncio
async def test_supervisor_delegate_to_unknown(supervisor_mod):
    rt = supervisor_mod.build_supervisor()
    delegate = rt.tools.get("delegate_to_agent")
    out = await delegate.handler(agent="nonsense", task="x")
    assert "unknown agent" in out


@pytest.mark.asyncio
async def test_supervisor_delegate_to_rca_calls_service(supervisor_mod):
    rt = supervisor_mod.build_supervisor()
    delegate = rt.tools.get("delegate_to_agent")

    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"report_id": "x", "summary": "ok"}

    async def fake_post(self, url, json=None):
        return _R()

    with patch("httpx.AsyncClient.post", fake_post):
        out = await delegate.handler(agent="rca", task="extra", incident_id="abc")
    assert "report_id" in out


@pytest.mark.asyncio
async def test_supervisor_delegate_to_rca_error(supervisor_mod):
    rt = supervisor_mod.build_supervisor()
    delegate = rt.tools.get("delegate_to_agent")

    async def fake_post(self, url, json=None):
        raise RuntimeError("network down")

    with patch("httpx.AsyncClient.post", fake_post):
        out = await delegate.handler(agent="rca", task="t", incident_id="x")
    assert "network down" in out


@pytest.mark.asyncio
async def test_supervisor_delegate_to_specialist(supervisor_mod):
    rt = supervisor_mod.build_supervisor()
    delegate = rt.tools.get("delegate_to_agent")
    out = await delegate.handler(agent="monitoring", task="status?")
    # Monitoring agent returns a runtime activity result.
    parsed = json.loads(out)
    assert parsed["agent"] == "monitoring"
    assert parsed["status"] in ("completed", "error")


@pytest.mark.asyncio
async def test_supervisor_list_specialists(supervisor_mod):
    rt = supervisor_mod.build_supervisor()
    out = await rt.tools.get("list_specialists").handler()
    parsed = json.loads(out)
    assert "monitoring" in parsed
    assert "rca" in parsed


# ---------------------------------------------------------------------
# chatops-service/agent.py
# ---------------------------------------------------------------------


@pytest.fixture
def chatops_mod():
    return _load_module("chatops-service", "agent")


@pytest.mark.asyncio
async def test_chatops_tools_present(chatops_mod):
    reg = chatops_mod.build_chat_tools()
    names = set(reg._tools.keys())
    assert "query_incidents" in names
    # Other tools depend on registry composition.
    assert len(names) >= 1


@pytest.mark.asyncio
async def test_chatops_query_incidents(chatops_mod):
    reg = chatops_mod.build_chat_tools()
    qi = reg.get("query_incidents")

    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"i": 1}]

    async def fake_get(self, url, params=None):
        return _R()

    with patch("httpx.AsyncClient.get", fake_get):
        out = await qi.handler(machine_id="m", severity="HIGH", limit=10)
        assert "i" in out
        out2 = await qi.handler()
        assert "i" in out2


@pytest.mark.asyncio
async def test_chatops_build_with_mcp(chatops_mod):
    """The async builder may attempt to load MCP tools; verify it returns
    a HermesAgentRuntime regardless of failure."""
    rt = await chatops_mod.build_chatops_agent_with_mcp()
    assert rt.agent_name == "chatops-agent"
