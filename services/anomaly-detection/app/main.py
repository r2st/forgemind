"""Anomaly Detection Service.

Subscribes to telemetry, runs the AnomalyEngine, persists incidents,
publishes `forgemind.incidents`, and exposes REST.

Suppression strategy: per (machine, metric), debounce within 30 s
to avoid flapping. The LLM severity classifier runs only after
debounce passes.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Query
from sqlalchemy import select, desc

from forgemind_common import (
    Incident,
    IncidentSeverity,
    TelemetryReading,
    get_logger,
    get_settings,
    setup_logging,
)
from forgemind_common.db import get_engine, session_scope
from forgemind_common.messaging import publish, subscribe
from forgemind_common.observability import (
    ANOMALY_COUNT,
    LLM_COST,
    LLM_TOKENS,
    install_metrics,
)

from .detectors import AnomalyEngine
from .models import Base, IncidentORM
from .severity import classify_severity

setup_logging("anomaly-detection")
log = get_logger(__name__)
settings = get_settings()

engine = AnomalyEngine()
_suppress: dict[tuple[str, str], datetime] = {}
SUPPRESS_WINDOW_S = 30.0


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Ensure schema exists.
    eng = get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Subscribe to telemetry stream.
    task = asyncio.create_task(_run_subscriber())
    log.info("anomaly_service.started")
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="ForgeMind Anomaly Detection", version="0.1.0", lifespan=lifespan)
install_metrics(app, "anomaly-detection")


async def _run_subscriber() -> None:
    async def handler(payload: dict) -> None:
        try:
            reading = TelemetryReading.model_validate(payload)
        except Exception:  # noqa: BLE001
            log.warning("anomaly.bad_payload", payload=payload)
            return
        await _handle_reading(reading)

    await subscribe(settings.telemetry_subject, handler, queue="anomaly-detection")
    # Keep coroutine alive.
    while True:
        await asyncio.sleep(3600)


async def _handle_reading(reading: TelemetryReading) -> None:
    anomalies = engine.feed(reading)
    if not anomalies:
        return
    now = datetime.now(timezone.utc)
    for a in anomalies:
        key = (reading.machine_id, a.metric)
        last = _suppress.get(key)
        if last and (now - last).total_seconds() < SUPPRESS_WINDOW_S:
            continue
        _suppress[key] = now
        await _record_anomaly(reading, a)


async def _record_anomaly(reading: TelemetryReading, a) -> None:  # noqa: ANN001
    payload = {
        "machine_id": reading.machine_id,
        "metric": a.metric,
        "value": a.value,
        "z_score": a.z_score,
        "iqr_score": a.iqr_score,
        "iforest_score": a.iforest_score,
        "score": a.score,
        "state": reading.state,
        "timestamp": reading.timestamp.isoformat(),
    }
    sev_info = await classify_severity(payload)
    incident = Incident(
        machine_id=reading.machine_id,
        line_id=reading.line_id,
        plant_id=reading.plant_id,
        title=sev_info["title"],
        description=sev_info["description"],
        severity=IncidentSeverity(sev_info["severity"]),
        detector="iforest+stat",
        metric=a.metric,
        score=a.score,
        confidence=a.confidence,
        z_score=a.z_score,
        context=payload,
    )

    async with session_scope() as session:
        session.add(
            IncidentORM(
                incident_id=incident.incident_id,
                machine_id=incident.machine_id,
                line_id=incident.line_id,
                plant_id=incident.plant_id,
                title=incident.title,
                description=incident.description,
                severity=incident.severity.value,
                status=incident.status.value,
                detector=incident.detector,
                metric=incident.metric,
                score=incident.score,
                confidence=incident.confidence,
                z_score=incident.z_score,
                detected_at=incident.detected_at,
                context=incident.context,
            )
        )

    ANOMALY_COUNT.labels(reading.machine_id, incident.severity.value).inc()
    if sev_info.get("model_used") and sev_info["model_used"] != "heuristic":
        LLM_TOKENS.labels(
            "anomaly-detection", "fast", sev_info["model_used"], "total"
        ).inc(sev_info.get("tokens", 0))
        LLM_COST.labels(
            "anomaly-detection", "fast", sev_info["model_used"]
        ).inc(sev_info.get("cost_usd", 0.0))

    await publish(settings.incidents_subject, incident.model_dump(mode="json"))
    log.info(
        "anomaly_service.incident",
        machine=reading.machine_id,
        metric=a.metric,
        sev=incident.severity.value,
        score=round(a.score, 3),
    )


# ----------------------------------------------------------------------
# REST
# ----------------------------------------------------------------------


@app.post("/api/v1/score")
async def score_one(reading: TelemetryReading) -> dict:
    """Score a single reading without publishing (handy for testing)."""
    anomalies = engine.feed(reading)
    return {
        "machine_id": reading.machine_id,
        "anomalies": [
            {
                "metric": a.metric,
                "value": a.value,
                "z_score": a.z_score,
                "iqr_score": a.iqr_score,
                "iforest_score": a.iforest_score,
                "score": a.score,
                "confidence": a.confidence,
            }
            for a in anomalies
        ],
    }


@app.get("/api/v1/incidents")
async def list_incidents(
    machine_id: str | None = None,
    severity: str | None = None,
    limit: int = Query(50, ge=1, le=500),
) -> list[dict]:
    stmt = select(IncidentORM).order_by(desc(IncidentORM.detected_at)).limit(limit)
    if machine_id:
        stmt = stmt.where(IncidentORM.machine_id == machine_id)
    if severity:
        stmt = stmt.where(IncidentORM.severity == severity.upper())
    async with session_scope() as session:
        rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "incident_id": str(r.incident_id),
            "machine_id": r.machine_id,
            "line_id": r.line_id,
            "plant_id": r.plant_id,
            "title": r.title,
            "description": r.description,
            "severity": r.severity,
            "status": r.status,
            "detector": r.detector,
            "metric": r.metric,
            "score": r.score,
            "confidence": r.confidence,
            "z_score": r.z_score,
            "detected_at": r.detected_at.isoformat(),
            "context": r.context,
        }
        for r in rows
    ]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
