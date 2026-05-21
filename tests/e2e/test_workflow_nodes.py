"""Direct unit tests for individual workflow-engine node functions."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


def _load_workflow():
    repo = Path(__file__).resolve().parent.parent.parent
    svc_dir = repo / "services" / "workflow-engine"
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
    p = importlib.util.module_from_spec(spec_app)
    sys.modules["app"] = p
    spec_app.loader.exec_module(p)
    spec = importlib.util.spec_from_file_location("app.graphs", str(svc_app / "graphs.py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules["app.graphs"] = m
    spec.loader.exec_module(m)
    return m


@pytest.mark.asyncio
async def test_node_fetch_telemetry_skipped_when_no_machine_id():
    g = _load_workflow()
    state = await g.node_fetch_telemetry({})
    assert state["telemetry"] == {}


@pytest.mark.asyncio
async def test_node_fetch_telemetry_handles_error():
    g = _load_workflow()

    async def boom(*a, **k):
        raise RuntimeError("no upstream")

    with patch.object(g, "_http_get", boom):
        state = await g.node_fetch_telemetry({"machine_id": "X"})
    assert "_error" in state["telemetry"]


@pytest.mark.asyncio
async def test_node_run_rca_failure():
    g = _load_workflow()

    async def boom(url, payload):
        raise RuntimeError("rca down")

    with patch.object(g, "_http_post", boom):
        state = await g.node_run_rca({"incident_id": "id-1"})
    assert "rca failed" in state["error"]


@pytest.mark.asyncio
async def test_node_run_pdm_skipped_and_failure():
    g = _load_workflow()
    state = await g.node_run_pdm({})
    assert state["pdm_forecast"] == {}

    async def boom(url):
        raise RuntimeError("pdm down")

    with patch.object(g, "_http_get", boom):
        state = await g.node_run_pdm({"machine_id": "X"})
    assert "_error" in state["pdm_forecast"]


def test_node_assess_severity_promotes():
    g = _load_workflow()
    state = g.node_assess_severity(
        {
            "incident": {"severity": "MEDIUM"},
            "pdm_forecast": {"risk_72h": 0.9},
            "rca_report": {"confidence": 0.8},
        }
    )
    assert state["severity"] in ("HIGH", "CRITICAL")
    assert state["needs_human_approval"] is True


def test_node_assess_severity_unknown_severity_default():
    g = _load_workflow()
    # Unknown severity → MEDIUM idx (2)
    state = g.node_assess_severity({"incident": {"severity": "BANANA"}})
    assert state["severity"] in ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL")


def test_node_human_approval_gate_blocks():
    g = _load_workflow()
    s = g.node_human_approval_gate(
        {"needs_human_approval": True, "approved": False}
    )
    assert s["status"] == "blocked_on_approval"


def test_node_human_approval_gate_passes():
    g = _load_workflow()
    s = g.node_human_approval_gate({"needs_human_approval": False})
    assert "trace" in s


@pytest.mark.asyncio
async def test_node_notify_severity_channels():
    g = _load_workflow()
    s = await g.node_notify({"severity": "CRITICAL", "machine_id": "X"})
    assert "pager" in s["notified_channels"]
    assert "exec_email" in s["notified_channels"]

    s2 = await g.node_notify({"severity": "INFO"})
    assert s2["notified_channels"] == ["ui"]


def test_node_propose_window():
    g = _load_workflow()
    s = g.node_propose_window(
        {
            "machine_id": "X",
            "pdm_forecast": {
                "recommended_window_start": "2026-05-21T00:00:00",
                "recommended_window_end": "2026-05-21T02:00:00",
            },
        }
    )
    assert "Schedule" in s["recommendations"][0]


def test_node_require_approval():
    g = _load_workflow()
    s = g.node_require_approval({"pdm_forecast": {"risk_72h": 0.6}})
    assert s["needs_human_approval"] is True
    s2 = g.node_require_approval({"pdm_forecast": {"risk_72h": 0.1}})
    assert s2["needs_human_approval"] is False


def test_node_schedule():
    g = _load_workflow()
    s = g.node_schedule({"needs_human_approval": True, "approved": False})
    assert s["status"] == "blocked_on_approval"
    s2 = g.node_schedule({})
    assert s2["status"] == "completed"


@pytest.mark.asyncio
async def test_node_choose_remediation_invalid_json():
    g = _load_workflow()
    from forgemind_common import hermes_runtime as hr

    # Patch the module's _REMEDIATION agent.run to return non-JSON.
    fake_act = hr.AgentActivity(
        agent_name="remediation",
        task="t",
        status="completed",
        result="not valid json",
    )

    async def fake_run(*a, **k):
        return fake_act

    with patch.object(g._REMEDIATION, "run", fake_run):
        s = await g.node_choose_remediation({"rca_report": {"summary": "x"}})
    assert s["recommendations"] == []


@pytest.mark.asyncio
async def test_node_choose_remediation_non_list_json():
    g = _load_workflow()
    from forgemind_common import hermes_runtime as hr

    fake_act = hr.AgentActivity(
        agent_name="remediation",
        task="t",
        status="completed",
        result='{"not": "a list"}',
    )

    async def fake_run(*a, **k):
        return fake_act

    with patch.object(g._REMEDIATION, "run", fake_run):
        s = await g.node_choose_remediation({"rca_report": {}})
    assert s["recommendations"] == []


@pytest.mark.asyncio
async def test_node_choose_remediation_valid_list():
    g = _load_workflow()
    from forgemind_common import hermes_runtime as hr

    fake_act = hr.AgentActivity(
        agent_name="remediation",
        task="t",
        status="completed",
        result='["a","b"]',
    )

    async def fake_run(*a, **k):
        return fake_act

    with patch.object(g._REMEDIATION, "run", fake_run):
        s = await g.node_choose_remediation({"rca_report": {}})
    assert s["recommendations"] == ["a", "b"]


def test_node_decide_escalation():
    g = _load_workflow()
    assert g.node_decide_escalation({"incident": {"recent_critical_count": 3}})["severity"] == "CRITICAL"
    assert g.node_decide_escalation({"incident": {"recent_critical_count": 1}})["severity"] == "HIGH"
    assert g.node_decide_escalation({})["severity"] == "MEDIUM"
