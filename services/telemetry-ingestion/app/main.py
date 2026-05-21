"""Telemetry Ingestion Service.

Accepts batched telemetry from edge gateways over HTTP, validates, and
republishes to NATS so the anomaly-detection pipeline can consume.

Real factories push from PLCs / OPC-UA gateways; this service is the
seam where that integration lands.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from forgemind_common import TelemetryReading, get_logger, get_settings, setup_logging
from forgemind_common.messaging import publish
from forgemind_common.observability import install_metrics

setup_logging("telemetry-ingestion")
log = get_logger(__name__)
settings = get_settings()

app = FastAPI(title="ForgeMind Telemetry Ingestion", version="0.1.0")
install_metrics(app, "telemetry-ingestion")

# Tiny in-memory metrics so /api/v1/telemetry/health is useful.
_RECENT = deque(maxlen=10000)


class BatchRequest(BaseModel):
    readings: list[TelemetryReading]


@app.post("/api/v1/telemetry/batch")
async def ingest_batch(req: BatchRequest) -> dict:
    if not req.readings:
        raise HTTPException(400, "empty batch")
    t0 = time.perf_counter()
    for r in req.readings:
        await publish(settings.telemetry_subject, r.model_dump(mode="json"))
        _RECENT.append(time.time())
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return {"accepted": len(req.readings), "elapsed_ms": elapsed_ms}


@app.post("/api/v1/telemetry/single")
async def ingest_single(reading: TelemetryReading) -> dict:
    await publish(settings.telemetry_subject, reading.model_dump(mode="json"))
    _RECENT.append(time.time())
    return {"accepted": 1}


@app.get("/api/v1/telemetry/health")
async def ingest_health() -> dict:
    now = time.time()
    last_minute = sum(1 for t in _RECENT if now - t <= 60)
    last_hour = sum(1 for t in _RECENT if now - t <= 3600)
    return {
        "ingested_last_minute": last_minute,
        "ingested_last_hour": last_hour,
        "buffer_size": len(_RECENT),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
