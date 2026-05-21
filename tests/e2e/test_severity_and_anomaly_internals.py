"""Direct coverage for anomaly-detection internals: severity + subscriber loop."""

from __future__ import annotations

import asyncio
import importlib
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest


def _load_anomaly_modules():
    """Load anomaly-detection submodules by file path so we don't fight
    other services' `app` namespaces in sys.modules."""
    import importlib.util
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent.parent
    ad_dir = repo / "services" / "anomaly-detection"
    ad_app = ad_dir / "app"
    if str(ad_dir) not in sys.path:
        sys.path.insert(0, str(ad_dir))

    for key in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
        del sys.modules[key]

    spec = importlib.util.spec_from_file_location(
        "app", str(ad_app / "__init__.py"),
        submodule_search_locations=[str(ad_app)],
    )
    app_mod = importlib.util.module_from_spec(spec)
    sys.modules["app"] = app_mod
    spec.loader.exec_module(app_mod)

    spec_sev = importlib.util.spec_from_file_location("app.severity", str(ad_app / "severity.py"))
    sev_mod = importlib.util.module_from_spec(spec_sev)
    sys.modules["app.severity"] = sev_mod
    spec_sev.loader.exec_module(sev_mod)

    spec_det = importlib.util.spec_from_file_location("app.detectors", str(ad_app / "detectors.py"))
    det_mod = importlib.util.module_from_spec(spec_det)
    sys.modules["app.detectors"] = det_mod
    spec_det.loader.exec_module(det_mod)

    return sev_mod, det_mod


@pytest.mark.asyncio
async def test_severity_classify_uses_gateway():
    sev, _ = _load_anomaly_modules()
    payload = {
        "machine_id": "CNC-101",
        "metric": "vibration_mm_s",
        "value": 12.0,
        "z_score": 5.5,
        "score": 0.95,
    }
    out = await sev.classify_severity(payload)
    assert out["severity"] in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
    assert "title" in out
    assert "description" in out


@pytest.mark.asyncio
async def test_severity_classify_falls_back_to_heuristic():
    sev, _ = _load_anomaly_modules()
    payload = {
        "machine_id": "CNC-101",
        "metric": "vibration_mm_s",
        "value": 12.0,
        "z_score": 5.5,
        "score": 0.95,
    }
    # Force the gateway path to raise so we exercise the fallback.
    from forgemind_common import llm_gateway as gw_mod

    async def boom(*args, **kwargs):
        raise gw_mod.GatewayError("upstream down")

    with patch.object(gw_mod.LLMGateway, "chat", boom):
        out = await sev.classify_severity(payload)
    assert out["model_used"] == "heuristic"


def test_severity_heuristic_buckets():
    sev, _ = _load_anomaly_modules()
    assert sev._heuristic({"score": 0.95, "metric": "x", "machine_id": "y", "value": 1.0, "z_score": 0.0})["severity"] == "CRITICAL"
    assert sev._heuristic({"score": 0.8, "metric": "x", "machine_id": "y", "value": 1.0, "z_score": 0.0})["severity"] == "HIGH"
    assert sev._heuristic({"score": 0.65, "metric": "x", "machine_id": "y", "value": 1.0, "z_score": 0.0})["severity"] == "MEDIUM"
    assert sev._heuristic({"score": 0.5, "metric": "x", "machine_id": "y", "value": 1.0, "z_score": 0.0})["severity"] == "LOW"
    assert sev._heuristic({"score": 0.1, "metric": "x", "machine_id": "y", "value": 1.0, "z_score": 0.0})["severity"] == "INFO"


def test_severity_heuristic_uses_defaults_for_missing_fields():
    sev, _ = _load_anomaly_modules()
    out = sev._heuristic({"score": 0.5, "value": 0.0, "z_score": 0.0})
    assert out["title"] == "signal anomaly on unknown"


def test_anomaly_engine_iforest_training_path():
    """Feed enough readings to trigger the iforest training branch."""
    sev, det = _load_anomaly_modules()
    eng = det.AnomalyEngine()
    from forgemind_common import TelemetryReading

    # First WARMUP+1 normal readings; then a spike should fire.
    for i in range(120):
        r = TelemetryReading(
            machine_id="X-1",
            line_id="line-A",
            plant_id="plant-01",
            timestamp=datetime.now(timezone.utc),
            temperature_c=62.0,
            vibration_mm_s=1.8,
            pressure_bar=4.2,
            rpm=2400,
            power_kw=18.0,
            state="RUNNING",
            units_produced=0,
            defects=0,
        )
        eng.feed(r)
    spike = TelemetryReading(
        machine_id="X-1",
        line_id="line-A",
        plant_id="plant-01",
        timestamp=datetime.now(timezone.utc),
        temperature_c=62.0,
        vibration_mm_s=20.0,
        pressure_bar=4.2,
        rpm=2400,
        power_kw=18.0,
        state="RUNNING",
        units_produced=0,
        defects=0,
    )
    anomalies = eng.feed(spike)
    assert len(anomalies) >= 1
