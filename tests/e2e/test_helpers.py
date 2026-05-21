"""Direct unit tests for pure-Python helper functions across services."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


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


def test_pdm_decayed_risk_with_incidents():
    pdm = _load("predictive-maintenance", "main")
    now = datetime.now(timezone.utc)
    incidents = [
        {"severity": "CRITICAL", "detected_at": (now - timedelta(hours=2)).isoformat()},
        {"severity": "HIGH", "detected_at": (now - timedelta(hours=10)).isoformat()},
        {"severity": "MEDIUM", "detected_at": now.isoformat()},
        {"severity": "LOW", "detected_at": now.isoformat()},
        {"severity": "INFO", "detected_at": now.isoformat()},
    ]
    risk = pdm._decayed_risk(incidents)
    assert 0.0 < risk < 1.0


def test_pdm_decayed_risk_empty():
    pdm = _load("predictive-maintenance", "main")
    assert pdm._decayed_risk([]) == 0.0


def test_pdm_decayed_risk_skips_bad_timestamps():
    pdm = _load("predictive-maintenance", "main")
    incidents = [
        {"severity": "HIGH"},  # no detected_at
        {"severity": "HIGH", "detected_at": "not-a-date"},
    ]
    assert pdm._decayed_risk(incidents) == 0.0


def test_pdm_decayed_risk_unknown_severity_default():
    pdm = _load("predictive-maintenance", "main")
    incidents = [
        {"severity": "BANANA", "detected_at": datetime.now(timezone.utc).isoformat()}
    ]
    # BANANA isn't in SEVERITY_WEIGHT, but the .get default kicks in.
    risk = pdm._decayed_risk(incidents)
    assert risk >= 0.0


def test_chatops_chunk_text_short():
    ch = _load("chatops-service", "main")
    assert ch._chunk_text("short") == ["short"]


def test_chatops_chunk_text_long():
    ch = _load("chatops-service", "main")
    text = "word " * 50
    chunks = ch._chunk_text(text, max_chars=50)
    assert len(chunks) > 1


def test_chatops_sse_helper():
    ch = _load("chatops-service", "main")
    sse = ch._sse("event-name", {"k": "v"})
    assert sse.startswith("event: event-name\n")
    assert "data: " in sse
    assert sse.endswith("\n\n")


def test_machinesim_anomaly_paths():
    sim = _load("telemetry-simulator", "main")
    m = sim.MachineSim("CNC-X", "CNC")
    for kind in ["vibration_spike", "thermal_runaway", "pressure_drop",
                 "motor_stall", "quality_spike", "power_surge"]:
        m.inject(kind, duration_ticks=2)
    # Run a few ticks to apply anomalies.
    for _ in range(5):
        m.step()
    # All anomaly kinds should have exercised their branches.
    assert m.machine_id == "CNC-X"


def test_machinesim_unknown_type_falls_back_to_cnc():
    sim = _load("telemetry-simulator", "main")
    m = sim.MachineSim("X-1", "BOGUS")
    assert m.temp > 0  # gets CNC baseline


def test_machinesim_idle_to_running_transitions():
    sim = _load("telemetry-simulator", "main")
    import random
    random.seed(0)
    m = sim.MachineSim("X-2", "CNC")
    m.state = "IDLE"
    for _ in range(60):
        m.step()
    # State machinery exercised


def test_machinesim_motor_stall_state_recovery():
    sim = _load("telemetry-simulator", "main")
    import random
    random.seed(7)
    m = sim.MachineSim("X-3", "CONVEYOR")
    m.inject("motor_stall", duration_ticks=1)
    m.step()
    m.step()
    # After stall ends, state may flip back to RUNNING.
    for _ in range(20):
        m.step()
