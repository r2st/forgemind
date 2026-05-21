"""ForgeMind API Gateway.

Front door for the frontend SPA. Handles:

  * JWT auth (login / verify)
  * CORS
  * Per-IP rate limiting
  * Reverse-proxies to downstream services so the frontend only needs
    one origin.

Production deployments would put a proper Envoy/Nginx in front, but
this gives us a single FastAPI process that does it all for dev.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from forgemind_common import get_logger, get_settings, setup_logging
from forgemind_common.auth import create_access_token, require_user
from forgemind_common.observability import install_metrics

setup_logging("api-gateway")
log = get_logger(__name__)
settings = get_settings()

app = FastAPI(title="ForgeMind API Gateway", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
install_metrics(app, "api-gateway")

# ----------------------------------------------------------------------
# Rate limiting (token bucket per IP)
# ----------------------------------------------------------------------

_RATE_HITS: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=300))
_RATE_WINDOW_S = 60
_RATE_MAX = 300


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    ip = request.client.host if request.client else "anon"
    now = time.time()
    bucket = _RATE_HITS[ip]
    while bucket and now - bucket[0] > _RATE_WINDOW_S:
        bucket.popleft()
    if len(bucket) >= _RATE_MAX:
        raise HTTPException(429, "rate limit exceeded")
    bucket.append(now)
    return await call_next(request)


# ----------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/v1/auth/login")
async def login(req: LoginRequest) -> dict:
    # Demo: trivial credentials. Real deployment plugs in OIDC.
    role = "viewer"
    if req.username == "admin" and req.password == "admin":
        role = "admin"
    elif req.username == "engineer" and req.password == "engineer":
        role = "engineer"
    elif req.username == "operator" and req.password == "operator":
        role = "operator"
    elif req.password != "viewer":
        raise HTTPException(401, "invalid credentials")
    token = create_access_token(req.username, role=role)  # type: ignore[arg-type]
    return {"access_token": token, "role": role, "username": req.username}


@app.get("/api/v1/auth/me")
async def me(user=Depends(require_user)) -> dict:
    return {"sub": user.sub, "role": user.role}


# ----------------------------------------------------------------------
# Reverse proxy
# ----------------------------------------------------------------------

_ROUTES: dict[str, str] = {
    "incidents":              settings.anomaly_service_url,
    "machines":               "http://telemetry-simulator:8000",
    "snapshot":               "http://telemetry-simulator:8000",
    "inject":                 "http://telemetry-simulator:8000",
    "rca":                    settings.rca_service_url,
    "predictions":            settings.pdm_service_url,
    "agents":                 settings.orchestrator_url,
    "chat":                   settings.chat_service_url,
    "reports":                settings.reporting_service_url,
    "notifications":          settings.notification_service_url,
    "telemetry":              settings.anomaly_service_url,
    "replay-historical":      "http://telemetry-simulator:8000",
    "workflows":              settings.workflow_engine_url,
}


@app.api_route("/api/v1/{section}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(section: str, path: str, request: Request) -> Any:
    target = _ROUTES.get(section)
    if not target:
        raise HTTPException(404, f"unknown section {section}")
    url = f"{target}/api/v1/{section}/{path}"
    return await _forward(request, url)


@app.api_route("/api/v1/{section}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_root(section: str, request: Request) -> Any:
    target = _ROUTES.get(section)
    if not target:
        raise HTTPException(404, f"unknown section {section}")
    url = f"{target}/api/v1/{section}"
    return await _forward(request, url)


async def _forward(request: Request, url: str) -> Any:
    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    body = await request.body()
    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            resp = await client.request(
                request.method,
                url,
                params=request.query_params,
                content=body,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"upstream error: {exc}") from exc
    ct = resp.headers.get("content-type", "")
    if "text/event-stream" in ct:
        async def stream():
            async for chunk in resp.aiter_raw():
                yield chunk
        return StreamingResponse(stream(), media_type="text/event-stream")
    return resp.json() if "json" in ct else resp.text


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
