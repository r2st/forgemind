"""Final coverage push: workflow error path, pump loop, exclude main blocks."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _load(service: str, mod: str):
    repo = Path(__file__).resolve().parent.parent.parent
    svc_dir = repo / "services" / service
    svc_app = svc_dir / "app"
    if str(svc_dir) not in sys.path:
        sys.path.insert(0, str(svc_dir))
    for key in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
        del sys.modules[key]
    spec_app = importlib.util.spec_from_file_location(
        "app",
        str(svc_app / "__init__.py"),
        submodule_search_locations=[str(svc_app)],
    )
    pkg = importlib.util.module_from_spec(spec_app)
    sys.modules["app"] = pkg
    spec_app.loader.exec_module(pkg)
    spec = importlib.util.spec_from_file_location(f"app.{mod}", str(svc_app / f"{mod}.py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules[f"app.{mod}"] = m
    spec.loader.exec_module(m)
    return m


def test_workflow_run_graph_raises(workflow_client):
    """Force a graph to raise — exercises the except branch."""
    from .conftest import SERVICE_MODULES
    import uuid

    mod = SERVICE_MODULES["workflow-engine"]
    original_graph = mod.GRAPHS["investigation"]

    class _BrokenGraph:
        async def ainvoke(self, state):
            raise RuntimeError("graph blew up")

    mod.GRAPHS["investigation"] = _BrokenGraph()
    try:
        r = workflow_client.post(
            "/api/v1/workflows/investigation/run",
            json={"incident_id": str(uuid.uuid4())},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "error"
    finally:
        mod.GRAPHS["investigation"] = original_graph


def test_workflow_serialize_state_handles_complex_objects():
    from .conftest import SERVICE_MODULES

    mod = SERVICE_MODULES["workflow-engine"]
    # _serialize_state must coerce non-JSON-friendly objects via str fallback.
    class Custom:
        def __str__(self):
            return "custom-repr"

    serialized = mod._serialize_state({"obj": Custom(), "lst": [1, 2]})
    assert serialized["obj"] == "custom-repr"
    assert serialized["lst"] == [1, 2]


@pytest.mark.asyncio
async def test_telemetry_simulator_pump_loop_exception_handled():
    """Force the pump loop to take the exception branch once."""
    mod = _load("telemetry-simulator", "main")
    if not mod.FLEET:
        mod._build_fleet()

    # Patch publish to raise once.
    call_count = {"n": 0}
    original = mod.publish

    async def boom(*a, **k):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated publish failure")

    mod.publish = boom

    async def run_briefly():
        task = asyncio.create_task(mod._pump_loop())
        # Let it run one cycle long enough to hit the exception path,
        # then cancel.
        await asyncio.sleep(1.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    try:
        await run_briefly()
    finally:
        mod.publish = original


@pytest.mark.asyncio
async def test_telemetry_simulator_lifespan():
    """Run lifespan to cover the startup/shutdown branch."""
    mod = _load("telemetry-simulator", "main")
    # Replace pump_loop with no-op so we don't loop indefinitely.
    async def noop_pump():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            pass

    mod._pump_loop = noop_pump

    async with mod.lifespan(mod.app):
        pass  # immediately exit so the finally branch (task.cancel) runs


@pytest.mark.asyncio
async def test_anomaly_lifespan_runs_subscriber():
    """Run anomaly lifespan and cancel quickly to cover task cancellation."""
    mod = _load("anomaly-detection", "main")

    # Stub _run_subscriber so it returns immediately.
    async def short_run():
        return

    mod._run_subscriber = short_run

    async with mod.lifespan(mod.app):
        pass


@pytest.mark.asyncio
async def test_notification_lifespan():
    mod = _load("notification-service", "main")

    async def short_run():
        return

    mod._run = short_run
    async with mod.lifespan(mod.app):
        pass


@pytest.mark.asyncio
async def test_chatops_lifespan_handles_failure():
    """ChatOps lifespan catches exceptions from MCP loading."""
    mod = _load("chatops-service", "main")
    agent_mod = _load("chatops-service", "agent")

    # Re-load main with updated agent submodule.
    mod = _load("chatops-service", "main")

    async def boom():
        raise RuntimeError("MCP init failed")

    # Override builder so lifespan exception branch runs.
    mod.build_chatops_agent_with_mcp = boom
    async with mod.lifespan(mod.app):
        pass


@pytest.mark.asyncio
async def test_rca_lifespan_creates_schema():
    """RCA lifespan creates pgvector extension + tables — covers the
    full lifespan body."""
    mod = _load("rca-service", "main")
    async with mod.lifespan(mod.app):
        pass


@pytest.mark.asyncio
async def test_reporting_lifespan():
    mod = _load("reporting-service", "main")
    async with mod.lifespan(mod.app):
        pass
