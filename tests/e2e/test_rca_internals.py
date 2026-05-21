"""Direct coverage of RCA service internals: tools and agent parser."""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


def _load_rca_modules():
    """Load RCA's app.agent and app.tools by file path, isolated from
    any conftest-cached `app` namespace owned by another service."""
    import importlib.util

    repo = Path(__file__).resolve().parent.parent.parent
    rca_app = repo / "services" / "rca-service" / "app"

    # Ensure forgemind_common imports are still satisfied.
    if str(repo / "services" / "rca-service") not in sys.path:
        sys.path.insert(0, str(repo / "services" / "rca-service"))

    # Force-load the rca-service app namespace.
    for key in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
        del sys.modules[key]
    spec_app = importlib.util.spec_from_file_location(
        "app", str(rca_app / "__init__.py"),
        submodule_search_locations=[str(rca_app)],
    )
    app_mod = importlib.util.module_from_spec(spec_app)
    sys.modules["app"] = app_mod
    spec_app.loader.exec_module(app_mod)

    spec_models = importlib.util.spec_from_file_location("app.models", str(rca_app / "models.py"))
    models_mod = importlib.util.module_from_spec(spec_models)
    sys.modules["app.models"] = models_mod
    spec_models.loader.exec_module(models_mod)

    spec_tools = importlib.util.spec_from_file_location("app.tools", str(rca_app / "tools.py"))
    tools_mod = importlib.util.module_from_spec(spec_tools)
    sys.modules["app.tools"] = tools_mod
    spec_tools.loader.exec_module(tools_mod)

    spec_agent = importlib.util.spec_from_file_location("app.agent", str(rca_app / "agent.py"))
    agent_mod = importlib.util.module_from_spec(spec_agent)
    sys.modules["app.agent"] = agent_mod
    spec_agent.loader.exec_module(agent_mod)

    return agent_mod, tools_mod


def test_parse_rca_json_valid():
    agent, _ = _load_rca_modules()
    parsed = agent.parse_rca_json(
        '{"summary":"x","findings":[],"recommended_actions":["a"],"confidence":0.9,"similar_incidents":[]}'
    )
    assert parsed["summary"] == "x"
    assert parsed["confidence"] == 0.9


def test_parse_rca_json_empty_input():
    agent, _ = _load_rca_modules()
    parsed = agent.parse_rca_json("")
    assert parsed["summary"]  # gets fallback message


def test_parse_rca_json_invalid_json():
    agent, _ = _load_rca_modules()
    parsed = agent.parse_rca_json("not json at all")
    assert "RCA agent returned no parseable output" in parsed["summary"]


def test_parse_rca_json_partial_json_inside_markdown():
    agent, _ = _load_rca_modules()
    text = "Here is the report:\n```\n{\"summary\": \"abc\"}\n```"
    parsed = agent.parse_rca_json(text)
    assert parsed["summary"] == "abc"


def test_parse_rca_json_malformed_json():
    agent, _ = _load_rca_modules()
    # JSON that decoder can't parse — should fall through to _empty_rca.
    parsed = agent.parse_rca_json("{not: 'json'}")
    assert "no parseable" in parsed["summary"]


def test_build_rca_tools_registry():
    _, tools = _load_rca_modules()
    reg = tools.build_rca_tools()
    names = set(reg._tools.keys())
    assert {"get_incident", "get_telemetry_context", "search_similar_incidents", "record_incident_memory"} <= names


@pytest.mark.asyncio
async def test_fetch_incident_no_match():
    _, tools = _load_rca_modules()

    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"incident_id": "other-id"}]

    async def fake_get(url, params=None):
        return _R()

    with patch("httpx.AsyncClient") as mock_cls:
        instance = mock_cls.return_value.__aenter__.return_value
        instance.get = AsyncMock(side_effect=fake_get)
        out = await tools._fetch_incident("missing")
    assert out == {}


@pytest.mark.asyncio
async def test_telemetry_context_no_match():
    _, tools = _load_rca_modules()

    class _R:
        status_code = 200

        def json(self):
            return [{"machine_id": "other"}]

    async def fake_get(url):
        return _R()

    with patch("httpx.AsyncClient") as mock_cls:
        instance = mock_cls.return_value.__aenter__.return_value
        instance.get = AsyncMock(side_effect=fake_get)
        out = await tools._telemetry_context("no-such-machine")
    assert out == {}


@pytest.mark.asyncio
async def test_telemetry_context_bad_status():
    _, tools = _load_rca_modules()

    class _R:
        status_code = 500

        def json(self):
            return []

    async def fake_get(url):
        return _R()

    with patch("httpx.AsyncClient") as mock_cls:
        instance = mock_cls.return_value.__aenter__.return_value
        instance.get = AsyncMock(side_effect=fake_get)
        out = await tools._telemetry_context("anything")
    assert out == {}


@pytest.mark.asyncio
async def test_similar_incidents_embed_fails():
    _, tools = _load_rca_modules()
    from forgemind_common import llm_gateway as gw

    async def boom(self, texts):
        raise RuntimeError("no embeddings")

    with patch.object(gw.LLMGateway, "embed", boom):
        out = await tools._similar_incidents("x")
    assert out == []


@pytest.mark.asyncio
async def test_persist_memory_embed_fails():
    _, tools = _load_rca_modules()
    from forgemind_common import llm_gateway as gw

    async def boom(self, texts):
        raise RuntimeError("no embeddings")

    with patch.object(gw.LLMGateway, "embed", boom):
        out = await tools._persist_memory(
            incident_id="11111111-1111-1111-1111-111111111111",
            machine_id="m",
            machine_type="CNC",
            severity="HIGH",
            summary="test",
        )
    assert out == {"persisted": False, "reason": "embedding failed"}


def test_tool_get_incident_handler_via_registry():
    _, tools = _load_rca_modules()
    reg = tools.build_rca_tools()
    t = reg.get("get_incident")
    assert t is not None
    assert t.name == "get_incident"
    # Schemas exposed.
    schemas = reg.openai_schema()
    names = [s["function"]["name"] for s in schemas]
    assert "get_incident" in names


def test_rca_empty_returns_actions():
    agent, _ = _load_rca_modules()
    out = agent._empty_rca()
    assert "Manually investigate" in out["recommended_actions"][0]
