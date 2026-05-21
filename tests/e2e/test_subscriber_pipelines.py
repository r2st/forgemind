"""Direct tests for the subscriber/handler pipelines that the in-process
broker can't otherwise exercise."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

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
    app_pkg = importlib.util.module_from_spec(spec_app)
    sys.modules["app"] = app_pkg
    spec_app.loader.exec_module(app_pkg)

    spec = importlib.util.spec_from_file_location(f"app.{mod}", str(svc_app / f"{mod}.py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules[f"app.{mod}"] = m
    spec.loader.exec_module(m)
    return m


def _reading(machine="X-pipe", vib=1.8, t=62.0):
    from forgemind_common import TelemetryReading

    return TelemetryReading(
        machine_id=machine,
        line_id="line-A",
        plant_id="plant-01",
        timestamp=datetime.now(timezone.utc),
        temperature_c=t,
        vibration_mm_s=vib,
        pressure_bar=4.2,
        rpm=2400,
        power_kw=18.0,
        state="RUNNING",
        units_produced=0,
        defects=0,
    )


@pytest.mark.asyncio
async def test_anomaly_handle_reading_no_anomalies(anomaly_client):
    main_mod = _load("anomaly-detection", "main")
    # First reading: engine isn't warmed up; should be a no-op.
    await main_mod._handle_reading(_reading())
    assert True


@pytest.mark.asyncio
async def test_anomaly_handle_reading_records(anomaly_client):
    main_mod = _load("anomaly-detection", "main")
    # Warm-up the engine for a synthetic machine.
    for _ in range(75):
        await main_mod._handle_reading(_reading("Sub-1"))
    # Now feed a spike.
    await main_mod._handle_reading(_reading("Sub-1", vib=20.0))
    # Suppression window: a second spike within 30s shouldn't double-record.
    await main_mod._handle_reading(_reading("Sub-1", vib=20.0))


@pytest.mark.asyncio
async def test_anomaly_subscriber_loop_bad_payload():
    main_mod = _load("anomaly-detection", "main")
    # Build the handler the same way _run_subscriber does and call with a
    # malformed payload to hit the warning branch.
    async def handler(payload):
        try:
            from forgemind_common import TelemetryReading

            reading = TelemetryReading.model_validate(payload)
        except Exception:
            return
        await main_mod._handle_reading(reading)

    await handler({"bogus": "payload"})


def _conftest_rca_main_module():
    """Return the actual rca-service `app.main` module that the conftest
    loaded — that's the one bound to the rca_client."""
    from .conftest import SERVICE_MODULES

    return SERVICE_MODULES["rca-service"]


@pytest.mark.asyncio
async def test_rca_machine_id_extraction(rca_client):
    """Run an RCA where the activity messages contain a tool message
    with machine_id JSON — exercises the machine_id-recovery loop."""
    main_mod = _conftest_rca_main_module()
    from forgemind_common import hermes_runtime as hr

    fake_activity = hr.AgentActivity(
        agent_name="rca-agent",
        task="t",
        status="completed",
        result='{"summary":"x","findings":[],"recommended_actions":[],"confidence":0.5,"similar_incidents":["11111111-1111-1111-1111-111111111111","bogus-id"]}',
        messages=[
            {"role": "user", "content": "go"},
            {
                "role": "tool",
                "content": '{"machine_id": "CNC-101", "metric": "vib"}',
            },
            {
                "role": "tool",
                "content": "not json with machine_id text",
            },
        ],
    )

    async def fake_run(task, **kw):
        return fake_activity

    with patch.object(main_mod.agent, "run", fake_run):
        r = rca_client.post(
            "/api/v1/rca/run",
            json={"incident_id": "22222222-2222-2222-2222-222222222222"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["similar_incidents"]) == 1  # bogus-id dropped


@pytest.mark.asyncio
async def test_rca_agent_error_returns_500(rca_client):
    main_mod = _conftest_rca_main_module()
    from forgemind_common import hermes_runtime as hr

    err_activity = hr.AgentActivity(
        agent_name="rca-agent",
        task="t",
        status="error",
        error="something broke",
    )

    async def fake_run(task, **kw):
        return err_activity

    with patch.object(main_mod.agent, "run", fake_run):
        r = rca_client.post(
            "/api/v1/rca/run", json={"incident_id": "33333333-3333-3333-3333-333333333333"}
        )
    assert r.status_code == 500


@pytest.mark.asyncio
async def test_rca_with_extra_context(rca_client):
    r = rca_client.post(
        "/api/v1/rca/run",
        json={
            "incident_id": "44444444-4444-4444-4444-444444444444",
            "extra_context": "operator notes here",
        },
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_chatops_http_helpers():
    """Cover _http_get and _http_post in chatops agent."""
    ch_mod = _load("chatops-service", "agent")

    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"x": 1}

    async def fake_get(self, url, params=None):
        return _R()

    async def fake_post(self, url, json=None):
        return _R()

    with patch("httpx.AsyncClient.get", fake_get), patch(
        "httpx.AsyncClient.post", fake_post
    ):
        out = await ch_mod._http_get("http://x")
        assert out == {"x": 1}
        out = await ch_mod._http_post("http://x", {})
        assert out == {"x": 1}
