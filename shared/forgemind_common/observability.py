"""Prometheus metrics + FastAPI middleware helpers."""

from __future__ import annotations

import time
from typing import Callable

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)

REQUEST_COUNT = Counter(
    "forgemind_http_requests_total",
    "Total HTTP requests",
    ["service", "method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "forgemind_http_request_seconds",
    "HTTP request latency",
    ["service", "method", "path"],
)
LLM_TOKENS = Counter(
    "forgemind_llm_tokens_total",
    "Total LLM tokens consumed via the configured LLM gateway",
    ["service", "tier", "model", "kind"],  # kind = prompt|completion
)
LLM_COST = Counter(
    "forgemind_llm_cost_usd",
    "Total LLM cost in USD via the configured LLM gateway",
    ["service", "tier", "model"],
)
ANOMALY_COUNT = Counter(
    "forgemind_anomalies_total",
    "Anomalies detected",
    ["machine_id", "severity"],
)


def install_metrics(app: FastAPI, service_name: str) -> None:
    @app.middleware("http")
    async def metrics_mw(request: Request, call_next: Callable):
        t0 = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - t0
        path = request.url.path
        REQUEST_LATENCY.labels(service_name, request.method, path).observe(elapsed)
        REQUEST_COUNT.labels(
            service_name, request.method, path, str(response.status_code)
        ).inc()
        return response

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": service_name}

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> dict[str, str]:
        return {"status": "ready", "service": service_name}
