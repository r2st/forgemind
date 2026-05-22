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

from forgemind_common import (
    KNOWN_AGENTS,
    config_for_admin,
    get_logger,
    get_settings,
    setup_logging,
    update_agent_config,
    update_default_config,
)
from forgemind_common.auth import create_access_token, require_user, require_admin
from forgemind_common.observability import install_metrics

setup_logging("api-gateway")
log = get_logger(__name__)
settings = get_settings()

app = FastAPI(title="ForgeMind API Gateway", version="0.1.0")

# CORS: In production, restrict to specific origins
import os
allowed_origins = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Content-Type", "Authorization", "X-Agent"],
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
    # Demo: credential check via environment variables for security.
    # Production deployment should use proper OIDC/OAuth2.
    import os
    import secrets
    
    # Check against environment-configured credentials
    valid_users = {
        os.getenv("AUTH_ADMIN_USER", "admin"): (os.getenv("AUTH_ADMIN_PASS"), "admin"),
        os.getenv("AUTH_ENGINEER_USER", "engineer"): (os.getenv("AUTH_ENGINEER_PASS"), "engineer"),
        os.getenv("AUTH_OPERATOR_USER", "operator"): (os.getenv("AUTH_OPERATOR_PASS"), "operator"),
        os.getenv("AUTH_VIEWER_USER", "viewer"): (os.getenv("AUTH_VIEWER_PASS"), "viewer"),
    }
    
    user_data = valid_users.get(req.username)
    if not user_data or not user_data[0]:
        raise HTTPException(401, "invalid credentials")
    
    expected_password, role = user_data
    if not secrets.compare_digest(req.password, expected_password):
        raise HTTPException(401, "invalid credentials")
    
    token = create_access_token(req.username, role=role)  # type: ignore[arg-type]
    return {"access_token": token, "role": role, "username": req.username}


@app.get("/api/v1/auth/me")
async def me(user=Depends(require_user)) -> dict:
    return {"sub": user.sub, "role": user.role}


# ----------------------------------------------------------------------
# Admin
# ----------------------------------------------------------------------


class LLMConfigUpdate(BaseModel):
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    clear_api_key: bool = False
    enabled: bool | None = None


_SERVICE_HEALTH: dict[str, str | None] = {
    "api-gateway": None,
    "llm-gateway": "http://llm-gateway:8000",
    "telemetry-simulator": "http://telemetry-simulator:8000",
    "telemetry-ingestion": "http://telemetry-ingestion:8000",
    "anomaly-detection": settings.anomaly_service_url,
    "rca-service": settings.rca_service_url,
    "predictive-maintenance": settings.pdm_service_url,
    "ai-orchestrator": settings.orchestrator_url,
    "workflow-engine": settings.workflow_engine_url,
    "chatops-service": settings.chat_service_url,
    "reporting-service": settings.reporting_service_url,
    "notification-service": settings.notification_service_url,
}


@app.get("/api/v1/admin/health")
async def admin_health(user=Depends(require_admin)) -> dict[str, Any]:
    services = await _check_services()
    ok = sum(1 for s in services if s["status"] == "ok")
    return {
        "summary": {
            "ok": ok,
            "total": len(services),
            "degraded": len(services) - ok,
        },
        "services": services,
    }


@app.get("/api/v1/admin/agents")
async def admin_agents(user=Depends(require_user)) -> dict[str, Any]:
    services = await _check_services()
    service_by_name = {s["name"]: s for s in services}
    agents: list[dict[str, Any]] = []
    for agent in KNOWN_AGENTS:
        health = service_by_name.get(agent["service"], {"status": "unknown"})
        cfg = config_for_admin(agent["name"])
        agent_status = "disabled"
        if cfg["resolved_enabled"]:
            agent_status = "ok" if health.get("status") == "ok" and cfg["resolved_api_key_set"] else "needs_config"
        agents.append({**agent, "health": health, "llm": cfg, "status": agent_status})
    return {
        "default_config": config_for_admin(),
        "llm_config_source": "admin",
        "agents": agents,
        "services": services,
    }


@app.put("/api/v1/admin/llm/default")
async def update_default_llm_config(req: LLMConfigUpdate, user=Depends(require_user)) -> dict[str, Any]:
    patch = req.model_dump(exclude_unset=True)
    update_default_config(patch)
    return config_for_admin()


@app.put("/api/v1/admin/agents/{agent_name}/config")
async def update_agent_llm_config(agent_name: str, req: LLMConfigUpdate, user=Depends(require_user)) -> dict[str, Any]:
    known = {a["name"] for a in KNOWN_AGENTS}
    if agent_name not in known:
        raise HTTPException(404, f"unknown agent {agent_name}")
    patch = req.model_dump(exclude_unset=True)
    update_agent_config(agent_name, patch)
    return config_for_admin(agent_name)


# ----------------------------------------------------------------------
# LLM Gateway Admin Endpoints (proxy to llm-gateway service)
# ----------------------------------------------------------------------

LLM_GATEWAY_URL = "http://llm-gateway:8000"


@app.api_route(
    "/api/v1/admin/llm",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    include_in_schema=False,
)
async def llm_admin_proxy_root(request: Request, user=Depends(require_user)) -> Any:
    """Proxy /api/v1/admin/llm (no trailing path) to the llm-gateway.

    Without this companion route, the generic reverse-proxy below would
    treat the URL as section=`admin`, path=`llm` and return a misleading
    404 ("unknown section admin"). See test_proxy_admin_llm_no_path.
    """
    return await _forward(request, f"{LLM_GATEWAY_URL}/api/v1/admin/llm")


@app.api_route(
    "/api/v1/admin/llm/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def llm_admin_proxy(path: str, request: Request, user=Depends(require_user)) -> Any:
    """Proxy all /api/v1/admin/llm/* requests to the llm-gateway service."""
    url = f"{LLM_GATEWAY_URL}/api/v1/admin/llm/{path}"
    return await _forward(request, url)


async def _check_services() -> list[dict[str, Any]]:
    async def one(name: str, base_url: str | None) -> dict[str, Any]:
        if base_url is None:
            return {
                "name": name,
                "status": "ok",
                "status_code": 200,
                "latency_ms": 0,
                "detail": "local",
            }
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{base_url.rstrip('/')}/healthz")
            elapsed = int((time.perf_counter() - t0) * 1000)
            return {
                "name": name,
                "status": "ok" if resp.status_code < 400 else "error",
                "status_code": resp.status_code,
                "latency_ms": elapsed,
                "detail": resp.text[:200],
            }
        except Exception as exc:  # noqa: BLE001
            elapsed = int((time.perf_counter() - t0) * 1000)
            return {
                "name": name,
                "status": "error",
                "status_code": 0,
                "latency_ms": elapsed,
                "detail": str(exc),
            }

    return await asyncio.gather(*(one(name, url) for name, url in _SERVICE_HEALTH.items()))


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
            log.error("upstream request failed", exc_info=True)
            raise HTTPException(502, "upstream service unavailable") from exc
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
