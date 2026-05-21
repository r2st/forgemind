"""End-to-end test fixtures for ForgeMind AI.

We can't bring up docker compose inside the sandbox, so we wire every
FastAPI service into a single in-process harness:

* `shared/` and every `services/*` package are added to sys.path.
* Environment variables are set so that `forgemind_common` picks up
  SQLite (aiosqlite) instead of Postgres, a known JWT secret, and known
  admin/operator credentials.
* `pgvector.sqlalchemy.Vector` is replaced with a JSON column so the
  RCA service can create its tables on SQLite.
* `forgemind_common.messaging.publish` / `subscribe` are replaced with a
  pure-Python in-memory broker.
* `forgemind_common.llm_gateway.LLMGateway.chat` and `.embed` are
  replaced with a deterministic mock so agents don't need a real LLM
  provider.
* `httpx.AsyncClient` (the one each service uses to call its peers) is
  redirected to the in-process TestClient apps via a custom transport.
* Every per-service fixture wraps a `TestClient` so lifespan/startup
  hooks run, including the anomaly-detection NATS subscriber and the
  RCA service's `CREATE EXTENSION vector` shim.

The result: pytest can run the whole stack end-to-end against real
service code without any external dependencies.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import time
import types
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------
# Repo paths / sys.path
# ---------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SHARED = REPO_ROOT / "shared"
SERVICES = REPO_ROOT / "services"

# `shared/forgemind_common` lives at shared/.
sys.path.insert(0, str(SHARED))


# ---------------------------------------------------------------------
# Environment defaults — set BEFORE importing any service code so
# Settings() picks them up.
# ---------------------------------------------------------------------

os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault(
    "POSTGRES_DSN",
    "sqlite+aiosqlite:///file:forgemind_e2e?mode=memory&cache=shared&uri=true",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("NATS_URL", "nats://localhost:4222")
os.environ.setdefault("TELEMETRY_SUBJECT", "forgemind.telemetry")
os.environ.setdefault("INCIDENTS_SUBJECT", "forgemind.incidents")
os.environ.setdefault("JWT_SECRET", "e2e-test-jwt-secret-please-do-not-use")
os.environ.setdefault("AUTH_ADMIN_USER", "admin")
os.environ.setdefault("AUTH_ADMIN_PASS", "admin-pass-e2e")
os.environ.setdefault("AUTH_ENGINEER_USER", "engineer")
os.environ.setdefault("AUTH_ENGINEER_PASS", "engineer-pass-e2e")
os.environ.setdefault("AUTH_OPERATOR_USER", "operator")
os.environ.setdefault("AUTH_OPERATOR_PASS", "operator-pass-e2e")
os.environ.setdefault("AUTH_VIEWER_USER", "viewer")
os.environ.setdefault("AUTH_VIEWER_PASS", "viewer-pass-e2e")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
os.environ.setdefault("LLM_GATEWAY_URL", "http://llm-gateway:8000")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("GATEWAY_SECRET_KEY", "")  # gateway auto-generates
os.environ.setdefault("AGENT_CONFIG_PATH", str(REPO_ROOT / "tests" / "e2e" / ".runtime" / "agent_config.json"))
(REPO_ROOT / "tests" / "e2e" / ".runtime").mkdir(exist_ok=True)

# ---------------------------------------------------------------------
# Replace pgvector.sqlalchemy.Vector with a JSON column so SQLite can
# create the rca-service tables.
# ---------------------------------------------------------------------

import sqlalchemy as _sa  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncConnection as _AsyncConnection  # noqa: E402

# rca-service runs `CREATE EXTENSION IF NOT EXISTS vector` in its lifespan;
# SQLite doesn't understand that. Wrap AsyncConnection.execute so the
# statement is silently dropped on the sqlite dialect.

_REAL_AC_EXECUTE = _AsyncConnection.execute


async def _patched_ac_execute(self, statement, *args, **kwargs):  # type: ignore[no-untyped-def]
    text = getattr(statement, "text", None)
    if (
        text is not None
        and "CREATE EXTENSION" in text.upper()
        and getattr(self.engine.dialect, "name", "") == "sqlite"
    ):
        # No-op on sqlite — return a sentinel mock object that has minimal API.
        class _NoOpResult:
            def scalars(self):
                return self

            def first(self):
                return None

            def all(self):
                return []

            def one_or_none(self):
                return None

            def __iter__(self):
                return iter([])

        return _NoOpResult()
    return await _REAL_AC_EXECUTE(self, statement, *args, **kwargs)


_AsyncConnection.execute = _patched_ac_execute  # type: ignore[assignment]

try:
    import pgvector.sqlalchemy as _pgv  # type: ignore[import-not-found]

    class _FakeVector(_sa.types.TypeDecorator):
        impl = _sa.JSON
        cache_ok = True

        def __init__(self, dim: int | None = None, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.dim = dim

    _pgv.Vector = _FakeVector  # type: ignore[assignment]
except Exception:  # noqa: BLE001
    # pgvector not installed — install a stub module so imports succeed.
    fake_module = types.ModuleType("pgvector.sqlalchemy")

    class _FakeVector(_sa.types.TypeDecorator):  # type: ignore[no-redef]
        impl = _sa.JSON
        cache_ok = True

        def __init__(self, dim: int | None = None, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.dim = dim

    fake_module.Vector = _FakeVector  # type: ignore[attr-defined]
    sys.modules["pgvector"] = types.ModuleType("pgvector")
    sys.modules["pgvector.sqlalchemy"] = fake_module


# ---------------------------------------------------------------------
# Reset cached singletons in forgemind_common so the new env wins.
# ---------------------------------------------------------------------

from forgemind_common import config as _fm_config  # noqa: E402
_fm_config.get_settings.cache_clear()  # type: ignore[attr-defined]
from forgemind_common import db as _fm_db  # noqa: E402
_fm_db._engine = None
_fm_db._session_factory = None


# ---------------------------------------------------------------------
# In-memory NATS broker
# ---------------------------------------------------------------------


class _InMemBroker:
    def __init__(self) -> None:
        self.subscribers: dict[str, list[Callable[[dict[str, Any]], Any]]] = {}
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, subject: str, payload: dict[str, Any]) -> None:
        self.published.append((subject, payload))
        for cb in list(self.subscribers.get(subject, [])):
            res = cb(payload)
            if asyncio.iscoroutine(res):
                await res

    async def subscribe(
        self,
        subject: str,
        handler: Callable[[dict[str, Any]], Any],
        queue: str | None = None,
    ) -> None:
        self.subscribers.setdefault(subject, []).append(handler)


BROKER = _InMemBroker()


async def _broker_publish(subject: str, payload: dict[str, Any]) -> None:
    await BROKER.publish(subject, payload)


async def _broker_subscribe(
    subject: str,
    handler: Callable[[dict[str, Any]], Any],
    queue: str | None = None,
) -> None:
    await BROKER.subscribe(subject, handler, queue)


from forgemind_common import messaging as _fm_messaging  # noqa: E402
_fm_messaging.publish = _broker_publish  # type: ignore[assignment]
_fm_messaging.subscribe = _broker_subscribe  # type: ignore[assignment]


# ---------------------------------------------------------------------
# Mock LLM gateway client used by every agent and the severity
# classifier.
# ---------------------------------------------------------------------

from forgemind_common import llm_gateway as _fm_llm  # noqa: E402


class _MockGatewayResponse:
    def __init__(self, content: str, tool_calls: list[dict[str, Any]] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls or []
        self.raw: dict[str, Any] = {}
        self.usage = _fm_llm.GatewayUsage(
            model="mock-model",
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            cost_usd=0.0001,
            latency_ms=1.0,
            trace_id="mock-trace",
        )


class _MockGatewayBehavior:
    """Per-test customizable behavior."""

    def __init__(self) -> None:
        self.responder: Callable[
            [list[dict[str, Any]], _fm_llm.ModelTier], _MockGatewayResponse | str | dict[str, Any]
        ] | None = None
        self.calls: list[tuple[list[dict[str, Any]], _fm_llm.ModelTier]] = []

    def reset(self) -> None:
        self.responder = None
        self.calls.clear()


MOCK_GW = _MockGatewayBehavior()


async def _mock_chat(self: Any, messages: list[dict[str, Any]], tier: Any = None, **_kwargs: Any) -> Any:
    tier = tier or _fm_llm.ModelTier.POWERFUL
    MOCK_GW.calls.append((messages, tier))
    if MOCK_GW.responder is not None:
        out = MOCK_GW.responder(messages, tier)
    else:
        out = _default_response(messages, tier)
    if isinstance(out, _MockGatewayResponse):
        return out
    if isinstance(out, dict):
        return _MockGatewayResponse(json.dumps(out))
    return _MockGatewayResponse(str(out))


async def _mock_embed(self: Any, texts: list[str]) -> list[list[float]]:
    # Deterministic 1536-d zero vector per text — fine since we replaced
    # pgvector with JSON for SQLite.
    return [[0.0] * 1536 for _ in texts]


def _default_response(messages: list[dict[str, Any]], tier: Any) -> dict[str, Any] | str:
    """Heuristic responder used when a test doesn't supply its own."""
    last = (messages[-1].get("content") or "") if messages else ""
    last_l = last.lower() if isinstance(last, str) else ""
    sys_prompt = (messages[0].get("content") or "") if messages else ""

    # Severity classifier (anomaly-detection) — wants JSON.
    if "factory operations triage" in sys_prompt:
        return {
            "severity": "HIGH",
            "title": "anomaly detected",
            "description": "Auto classified by mock gateway.",
        }

    # RCA agent — wants a JSON object.
    if "RCA Agent inside ForgeMind" in sys_prompt or "structured root-cause analysis" in sys_prompt:
        return {
            "summary": "Mock RCA summary explaining the incident.",
            "findings": [
                {
                    "category": "MECHANICAL",
                    "hypothesis": "Bearing wear caused vibration spike",
                    "evidence": ["vibration > 4.0 mm/s"],
                    "likelihood": 0.8,
                }
            ],
            "recommended_actions": ["Replace bearing within 24h"],
            "confidence": 0.7,
            "similar_incidents": [],
        }

    # Reporting / chatops fallbacks — plain text.
    if "Supervisor Agent" in sys_prompt:
        return "Mock supervisor summary: monitored, no critical incidents."
    if "Reporting Agent" in sys_prompt or "executive summary" in last_l or "operations report" in last_l:
        return "Mock executive report: throughput stable, no urgent issues."
    if "ChatOps Agent" in sys_prompt:
        return "Mock chatops response citing machine-IDs and severity."

    # Remediation agent — wants a JSON list.
    if "Remediation Agent" in sys_prompt:
        return '["Replace bearing within 24h", "Schedule shutdown next maintenance window"]'

    return "Mock response."


# Capture originals BEFORE patching so test_llm_gateway_client.py can
# exercise the real HTTP paths via a scoped restore.
REAL_LLM_GATEWAY_METHODS = {
    "chat": _fm_llm.LLMGateway.chat,
    "embed": _fm_llm.LLMGateway.embed,
    "_chat_one": _fm_llm.LLMGateway._chat_one,
    "chat_stream": _fm_llm.LLMGateway.chat_stream,
}

# Patch class methods globally.
_fm_llm.LLMGateway.chat = _mock_chat  # type: ignore[assignment]
_fm_llm.LLMGateway.embed = _mock_embed  # type: ignore[assignment]


# ---------------------------------------------------------------------
# Service apps. We import each `app.main` lazily so env tweaks take
# effect first. Each service's package directory must be on sys.path
# while imported so `from .module import X` resolves.
# ---------------------------------------------------------------------


SERVICE_MODULES: dict[str, Any] = {}


def _load_service(service: str) -> Any:
    """Import services/<service>/app/main.py and return its FastAPI app."""
    svc_dir = SERVICES / service
    sys.path.insert(0, str(svc_dir))
    # Drop any cached `app.*` modules from a previous service so we don't
    # accidentally import one service's models when loading another.
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    mod = importlib.import_module("app.main")
    SERVICE_MODULES[service] = mod
    return mod.app


# ---------------------------------------------------------------------
# Inter-service HTTP redirection.
#
# Several services use `httpx.AsyncClient` to call peers at fixed
# hostnames (e.g. http://telemetry-simulator:8000). We install a custom
# httpx async transport on `httpx.AsyncClient.__init__` that recognises
# those hostnames and dispatches the request to the matching TestClient
# instead of going to the network.
# ---------------------------------------------------------------------

import httpx as _httpx  # noqa: E402

_HOST_MAP: dict[str, Any] = {}  # host -> ASGITransport


class _RoutingTransport(_httpx.AsyncBaseTransport):
    def __init__(self, fallback: _httpx.AsyncBaseTransport | None = None) -> None:
        self._fallback = fallback or _httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: _httpx.Request) -> _httpx.Response:
        host = request.url.host
        transport = _HOST_MAP.get(host)
        if transport is None:
            # Most upstream HTTP calls in tests should hit a known host.
            # If we hit the network we'd block — return a stub 503.
            return _httpx.Response(503, json={"detail": f"no in-process route for host {host}"})
        # Rewrite to a fake base so ASGITransport receives just the path.
        return await transport.handle_async_request(request)

    async def aclose(self) -> None:
        await self._fallback.aclose()


_REAL_ASYNC_INIT = _httpx.AsyncClient.__init__


def _patched_async_init(self: _httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
    if "transport" not in kwargs:
        kwargs["transport"] = _RoutingTransport()
    _REAL_ASYNC_INIT(self, *args, **kwargs)


_httpx.AsyncClient.__init__ = _patched_async_init  # type: ignore[assignment]


def _register_host(host: str, app: Any) -> None:
    _HOST_MAP[host] = _httpx.ASGITransport(app=app)


# ---------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def service_apps() -> dict[str, Any]:
    """Import every service's FastAPI app once for the session."""
    apps: dict[str, Any] = {}
    # Order chosen so the simpler services land first; doesn't really
    # matter since we sys.path.insert each time.
    apps["llm-gateway"] = _load_service("llm-gateway")
    apps["telemetry-simulator"] = _load_service("telemetry-simulator")
    apps["telemetry-ingestion"] = _load_service("telemetry-ingestion")
    apps["anomaly-detection"] = _load_service("anomaly-detection")
    apps["rca-service"] = _load_service("rca-service")
    apps["predictive-maintenance"] = _load_service("predictive-maintenance")
    apps["ai-orchestrator"] = _load_service("ai-orchestrator")
    apps["workflow-engine"] = _load_service("workflow-engine")
    apps["chatops-service"] = _load_service("chatops-service")
    apps["reporting-service"] = _load_service("reporting-service")
    apps["notification-service"] = _load_service("notification-service")
    apps["api-gateway"] = _load_service("api-gateway")

    for host, app in apps.items():
        _register_host(host, app)
    return apps


@pytest.fixture(autouse=True)
def _reset_state() -> Iterator[None]:
    """Reset broker and mock-gateway state between tests so tests don't bleed into each other."""
    BROKER.subscribers.clear()
    BROKER.published.clear()
    MOCK_GW.reset()
    yield


from fastapi.testclient import TestClient  # noqa: E402


def _client_for(app: Any) -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def simulator_client(service_apps: dict[str, Any]) -> Iterator[TestClient]:
    # The simulator's lifespan launches an infinite _pump_loop. Bypass
    # it by skipping lifespan (don't use TestClient as context manager)
    # and trigger _build_fleet() directly on the simulator module.
    app = service_apps["telemetry-simulator"]
    sim_mod = SERVICE_MODULES["telemetry-simulator"]
    if not sim_mod.FLEET:
        sim_mod._build_fleet()
    yield TestClient(app)


@pytest.fixture
def ingestion_client(service_apps: dict[str, Any]) -> Iterator[TestClient]:
    with _client_for(service_apps["telemetry-ingestion"]) as c:
        yield c


@pytest.fixture
def anomaly_client(service_apps: dict[str, Any]) -> Iterator[TestClient]:
    with _client_for(service_apps["anomaly-detection"]) as c:
        yield c


@pytest.fixture
def rca_client(service_apps: dict[str, Any]) -> Iterator[TestClient]:
    with _client_for(service_apps["rca-service"]) as c:
        yield c


@pytest.fixture
def pdm_client(service_apps: dict[str, Any]) -> Iterator[TestClient]:
    with _client_for(service_apps["predictive-maintenance"]) as c:
        yield c


@pytest.fixture
def orchestrator_client(service_apps: dict[str, Any]) -> Iterator[TestClient]:
    with _client_for(service_apps["ai-orchestrator"]) as c:
        yield c


@pytest.fixture
def workflow_client(service_apps: dict[str, Any]) -> Iterator[TestClient]:
    with _client_for(service_apps["workflow-engine"]) as c:
        yield c


@pytest.fixture
def chatops_client(service_apps: dict[str, Any]) -> Iterator[TestClient]:
    with _client_for(service_apps["chatops-service"]) as c:
        yield c


@pytest.fixture
def reporting_client(service_apps: dict[str, Any]) -> Iterator[TestClient]:
    with _client_for(service_apps["reporting-service"]) as c:
        yield c


@pytest.fixture
def notification_client(service_apps: dict[str, Any]) -> Iterator[TestClient]:
    with _client_for(service_apps["notification-service"]) as c:
        yield c


@pytest.fixture
def llm_gateway_client(service_apps: dict[str, Any]) -> Iterator[TestClient]:
    with _client_for(service_apps["llm-gateway"]) as c:
        yield c


@pytest.fixture
def api_gateway_client(service_apps: dict[str, Any]) -> Iterator[TestClient]:
    with _client_for(service_apps["api-gateway"]) as c:
        yield c


@pytest.fixture
def admin_token(api_gateway_client: TestClient) -> str:
    r = api_gateway_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": os.environ["AUTH_ADMIN_PASS"]},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture
def operator_token(api_gateway_client: TestClient) -> str:
    r = api_gateway_client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": os.environ["AUTH_OPERATOR_PASS"]},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture
def sample_reading() -> dict[str, Any]:
    return {
        "machine_id": "CNC-101",
        "line_id": "line-A",
        "plant_id": "plant-01",
        "timestamp": "2026-05-21T12:00:00+00:00",
        "temperature_c": 62.0,
        "vibration_mm_s": 1.8,
        "pressure_bar": 4.2,
        "rpm": 2400,
        "power_kw": 18.0,
        "state": "RUNNING",
        "units_produced": 0,
        "defects": 0,
    }


@pytest.fixture
def mock_gateway() -> _MockGatewayBehavior:
    return MOCK_GW
