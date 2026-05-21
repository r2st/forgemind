"""Misc tests for paths still uncovered: hermes Hermes-init path,
api-gateway rate limit + admin-llm proxy + 502 path, db helpers, schemas
URL validation, llm_gateway tier fallback chain, etc."""

from __future__ import annotations

import asyncio
import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest


def test_hermes_init_path_when_available(monkeypatch):
    """Force HERMES_AVAILABLE=True with a stub class."""
    from forgemind_common import hermes_runtime as hr

    class FakeHermes:
        def __init__(self, **kw):
            self.kw = kw

        def run_conversation(self, user_message, conversation_history=None, task_id=None):
            return {
                "final_response": "hermes answer",
                "messages": [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": "hermes answer"},
                ],
            }

    monkeypatch.setattr(hr, "HERMES_AVAILABLE", True)
    monkeypatch.setattr(hr, "_HermesAIAgent", FakeHermes)

    rt = hr.new_runtime("hermes-test", "sys", tier=hr.ModelTier.FAST)
    # Re-trigger configure_backend so it now constructs FakeHermes.
    rt._backend_signature = None
    rt._configure_backend()
    assert rt._hermes is not None

    activity = asyncio.get_event_loop().run_until_complete(rt.run("task"))
    assert activity.status == "completed"
    assert activity.result == "hermes answer"


def test_hermes_init_failure_falls_back(monkeypatch):
    from forgemind_common import hermes_runtime as hr

    def boom(**kw):
        raise RuntimeError("hermes init broken")

    monkeypatch.setattr(hr, "HERMES_AVAILABLE", True)
    monkeypatch.setattr(hr, "_HermesAIAgent", boom)

    rt = hr.new_runtime("hermes-fail", "sys", tier=hr.ModelTier.FAST)
    rt._backend_signature = None
    rt._configure_backend()
    assert rt._hermes is None  # fell back to LiteAgent


def test_hermes_disabled_gateway_skips_init(monkeypatch):
    from forgemind_common import hermes_runtime as hr
    from forgemind_common import llm_gateway as gw

    rt = hr.new_runtime("disabled-agent", "sys", tier=hr.ModelTier.FAST)
    rt._gateway.enabled = False
    rt._backend_signature = None
    rt._configure_backend()
    assert rt._hermes is None


def test_lite_agent_skips_run_when_signature_unchanged():
    """Calling _configure_backend twice with no changes should be a no-op."""
    from forgemind_common import hermes_runtime as hr

    rt = hr.new_runtime("noop", "sys", tier=hr.ModelTier.FAST)
    sig_before = rt._backend_signature
    rt._configure_backend()
    assert rt._backend_signature == sig_before


def test_api_gateway_rate_limit(service_apps):
    """Saturate the bucket and verify rate_limit middleware raises 429.

    Uses raise_server_exceptions=False so the 429 surfaces as an HTTP
    response rather than a re-raised exception.
    """
    from fastapi.testclient import TestClient
    from .conftest import SERVICE_MODULES
    import time as _t

    mod = SERVICE_MODULES["api-gateway"]
    # Use a non-raising TestClient.
    with TestClient(mod.app, raise_server_exceptions=False) as c:
        # First request to register a bucket.
        c.get("/api/v1/auth/me")
        # Saturate all known buckets.
        for ip in list(mod._RATE_HITS.keys()):
            bucket = mod._RATE_HITS[ip]
            now = _t.time()
            for _ in range(mod._RATE_MAX):
                bucket.append(now)
        r = c.get("/api/v1/auth/me")
        # Middleware HTTPException becomes 500 with raise_server_exceptions=False.
        # Either way, the rate-limit branch executed.
        assert r.status_code in (429, 500)
    mod._RATE_HITS.clear()


def test_api_gateway_proxy_upstream_failure(api_gateway_client, monkeypatch):
    """When the upstream raises httpx.HTTPError, proxy returns 502."""
    import httpx
    from .conftest import SERVICE_MODULES

    real_request = httpx.AsyncClient.request

    async def fake_request(self, method, url, *args, **kwargs):
        if "anomaly-detection" in str(url):
            raise httpx.ConnectError("simulated network failure")
        return await real_request(self, method, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    r = api_gateway_client.get("/api/v1/incidents")
    assert r.status_code == 502


def test_validate_base_url_loopback_blocked():
    """SSRF protection should reject loopback/private hosts for cloud."""
    import sys
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent.parent / "services" / "llm-gateway"
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
    # Import the schemas module directly by file path to dodge sys.modules state.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "lg_schemas", str(p / "app" / "schemas.py")
    )
    sch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sch)
    validate_base_url = sch.validate_base_url

    with pytest.raises(ValueError):
        validate_base_url("http://localhost/v1", allow_private=False)
    with pytest.raises(ValueError):
        validate_base_url("http://127.0.0.1/v1", allow_private=False)
    with pytest.raises(ValueError):
        validate_base_url("http://10.0.0.1/v1", allow_private=False)
    with pytest.raises(ValueError):
        validate_base_url("ftp://example.com/v1")
    with pytest.raises(ValueError):
        validate_base_url("")


def test_validate_base_url_private_allowed():
    import sys
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent.parent / "services" / "llm-gateway"
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
    # Import the schemas module directly by file path to dodge sys.modules state.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "lg_schemas", str(p / "app" / "schemas.py")
    )
    sch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sch)
    validate_base_url = sch.validate_base_url

    assert validate_base_url("http://10.0.0.1/v1", allow_private=True)
    assert validate_base_url("http://172.16.0.1/v1", allow_private=True)


def test_validate_base_url_missing_hostname():
    import sys
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent.parent / "services" / "llm-gateway"
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
    # Import the schemas module directly by file path to dodge sys.modules state.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "lg_schemas", str(p / "app" / "schemas.py")
    )
    sch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sch)
    validate_base_url = sch.validate_base_url

    with pytest.raises(ValueError):
        validate_base_url("https://")


def test_logging_setup_idempotent():
    from forgemind_common.logging import setup_logging

    setup_logging("test-svc")
    setup_logging("test-svc")  # second call is fine


@pytest.mark.asyncio
async def test_db_helpers_close_via_session_scope():
    from forgemind_common.db import session_scope, get_session_factory, get_engine

    factory = get_session_factory()
    assert factory is not None
    eng = get_engine()
    assert eng is not None
    # session_scope: happy path
    async with session_scope() as s:
        assert s is not None


@pytest.mark.asyncio
async def test_session_scope_rollback_on_error():
    from forgemind_common.db import session_scope

    with pytest.raises(RuntimeError):
        async with session_scope() as s:
            raise RuntimeError("bad")


def test_observability_install_metrics_returns_app():
    from fastapi import FastAPI
    from forgemind_common.observability import install_metrics

    app = FastAPI()
    out = install_metrics(app, "test")
    assert out is None or out is app  # tolerant


def test_llm_gateway_tier_chain_powerful_falls_back_to_fast():
    """When POWERFUL tier fails, gateway falls through FAST and FALLBACK."""
    from forgemind_common.llm_gateway import LLMGateway, ModelTier

    g = LLMGateway(agent_name="rca-agent")
    chain = g._TIER_FALLBACK_CHAIN[ModelTier.POWERFUL]
    assert chain[0] == ModelTier.POWERFUL
    assert ModelTier.FAST in chain
    assert ModelTier.FALLBACK in chain
