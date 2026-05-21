"""Predictive Maintenance Service.

Combines an analytical risk model with the PdM Hermes agent (via the
orchestrator) to produce per-machine failure forecasts.

Analytical layer: weighted sum of recent CRITICAL/HIGH incidents +
rolling vibration / temperature anomaly scores, decayed by recency.
Agent layer: explains the score and proposes a maintenance window.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException

from forgemind_common import get_logger, get_settings, setup_logging
from forgemind_common.observability import install_metrics

setup_logging("predictive-maintenance")
log = get_logger(__name__)
settings = get_settings()

app = FastAPI(title="ForgeMind Predictive Maintenance", version="0.1.0")
install_metrics(app, "predictive-maintenance")


SEVERITY_WEIGHT = {
    "CRITICAL": 1.0,
    "HIGH": 0.7,
    "MEDIUM": 0.35,
    "LOW": 0.1,
    "INFO": 0.0,
}


async def _list_machines() -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get("http://telemetry-simulator:8000/api/v1/machines")
        r.raise_for_status()
        return r.json()


async def _incidents_for(machine_id: str, limit: int = 200) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"{settings.anomaly_service_url}/api/v1/incidents",
            params={"machine_id": machine_id, "limit": limit},
        )
        r.raise_for_status()
        return r.json()


def _decayed_risk(incidents: list[dict[str, Any]], half_life_h: float = 12.0) -> float:
    if not incidents:
        return 0.0
    now = datetime.now(timezone.utc)
    score = 0.0
    for inc in incidents:
        try:
            ts = datetime.fromisoformat(inc["detected_at"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        age_h = max(0.0, (now - ts).total_seconds() / 3600.0)
        decay = math.exp(-math.log(2) * age_h / half_life_h)
        w = SEVERITY_WEIGHT.get(inc.get("severity", "MEDIUM"), 0.3)
        score += w * decay
    # squash to 0..1
    return float(1.0 - math.exp(-score / 3.0))


@app.get("/api/v1/predictions")
async def predictions() -> list[dict[str, Any]]:
    machines = await _list_machines()
    out: list[dict[str, Any]] = []
    for m in machines:
        incs = await _incidents_for(m["machine_id"])
        risk = _decayed_risk(incs)
        # heuristic ETA: lower risk => later
        eta_h = max(2.0, 240.0 * (1.0 - risk) ** 2)
        win_start = datetime.now(timezone.utc) + timedelta(hours=max(1.0, eta_h * 0.6))
        win_end = win_start + timedelta(hours=max(2.0, eta_h * 0.25))
        out.append(
            {
                "machine_id": m["machine_id"],
                "machine_type": m["machine_type"],
                "risk_24h": min(1.0, risk * 0.8 + 0.05),
                "risk_72h": min(1.0, risk * 1.0 + 0.1),
                "estimated_failure_in_hours": round(eta_h, 1),
                "recommended_window_start": win_start.isoformat(),
                "recommended_window_end": win_end.isoformat(),
                "contributing_signals": sorted({i.get("metric") for i in incs if i.get("metric")}),
                "rationale": (
                    f"Risk derived from {len(incs)} recent incidents weighted by severity "
                    "and decayed by 12-hour half-life."
                ),
            }
        )
    out.sort(key=lambda r: r["risk_72h"], reverse=True)
    return out


@app.get("/api/v1/predictions/{machine_id}")
async def predict_one(machine_id: str) -> dict[str, Any]:
    all_preds = await predictions()
    for p in all_preds:
        if p["machine_id"] == machine_id:
            return p
    raise HTTPException(404, "machine not found")


@app.post("/api/v1/predictions/explain/{machine_id}")
async def explain(machine_id: str) -> dict[str, Any]:
    """Ask the Hermes PdM agent (via orchestrator) for a richer narrative."""
    task = (
        f"Produce a predictive maintenance forecast for machine_id={machine_id}. "
        "Use recent_incidents_for_machine + get_machine_snapshot. Return the JSON object only."
    )
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(
            f"{settings.orchestrator_url}/api/v1/agents/run", json={"task": task}
        )
        r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
