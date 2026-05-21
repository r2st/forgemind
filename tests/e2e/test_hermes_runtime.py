"""Coverage for forgemind_common.hermes_runtime (LiteAgent loop)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from forgemind_common import (
    HermesAgentRuntime,
    ModelTier,
    Tool,
    ToolRegistry,
    new_runtime,
)
from forgemind_common import hermes_runtime as hr
from forgemind_common import llm_gateway as gw_mod


def test_tool_registry_register_and_schema():
    reg = ToolRegistry()

    @reg.register(
        name="t1",
        description="d",
        parameters={"type": "object", "properties": {}},
    )
    def fn(**_kwargs):
        return "ok"

    reg.add(
        Tool(
            name="t2",
            description="d2",
            parameters={"type": "object", "properties": {}},
            handler=lambda: "ok2",
        )
    )

    assert reg.get("t1") is not None
    assert reg.get("t2") is not None
    schemas = reg.openai_schema()
    assert {s["function"]["name"] for s in schemas} == {"t1", "t2"}
    assert reg.get("missing") is None


@pytest.mark.asyncio
async def test_lite_agent_no_tool_calls():
    rt = new_runtime("test-agent", "system", tier=ModelTier.FAST, tools=ToolRegistry())
    activity = await rt.run("task")
    assert activity.status == "completed"
    assert activity.result


@pytest.mark.asyncio
async def test_lite_agent_with_tools_and_resolution():
    reg = ToolRegistry()

    @reg.register(
        name="echo",
        description="echo back",
        parameters={"type": "object", "properties": {"text": {"type": "string"}}},
    )
    async def echo(text: str) -> str:
        return f"echo:{text}"

    rt = new_runtime("tool-agent", "system", tier=ModelTier.FAST, tools=reg)

    call_count = {"n": 0}

    async def chat_responder(self, messages, tier=None, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First call — return a tool call.
            return _resp_with_tool_call(
                tool_call_id="c1",
                name="echo",
                args={"text": "hi"},
            )
        return _resp_simple("final answer")

    with patch.object(gw_mod.LLMGateway, "chat", chat_responder):
        activity = await rt.run("task")
    assert activity.status == "completed"
    assert any(tc["tool"] == "echo" for tc in activity.tool_calls)
    assert "final answer" in activity.result


@pytest.mark.asyncio
async def test_lite_agent_unknown_tool():
    rt = new_runtime("agent-x", "sys", tier=ModelTier.FAST, tools=ToolRegistry())

    call_count = {"n": 0}

    async def chat_responder(self, messages, tier=None, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _resp_with_tool_call(
                tool_call_id="c2", name="ghost_tool", args={}
            )
        return _resp_simple("done")

    with patch.object(gw_mod.LLMGateway, "chat", chat_responder):
        activity = await rt.run("task")
    assert activity.status == "completed"
    # The unknown-tool branch should be recorded.
    assert any("unknown tool" in tc["result_preview"] for tc in activity.tool_calls)


@pytest.mark.asyncio
async def test_lite_agent_tool_handler_raises():
    reg = ToolRegistry()

    @reg.register(
        name="boom",
        description="raises",
        parameters={"type": "object", "properties": {}},
    )
    async def boom():
        raise RuntimeError("kaboom")

    rt = new_runtime("agent-b", "sys", tier=ModelTier.FAST, tools=reg)

    call_count = {"n": 0}

    async def chat_responder(self, messages, tier=None, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _resp_with_tool_call(
                tool_call_id="c3", name="boom", args={}
            )
        return _resp_simple("done")

    with patch.object(gw_mod.LLMGateway, "chat", chat_responder):
        activity = await rt.run("task")
    assert activity.status == "completed"
    assert any("ERROR" in tc["result_preview"] for tc in activity.tool_calls)


@pytest.mark.asyncio
async def test_lite_agent_sync_tool_returning_dict():
    reg = ToolRegistry()

    @reg.register(
        name="dictret",
        description="d",
        parameters={"type": "object", "properties": {}},
    )
    def dictret():
        return {"k": "v"}

    rt = new_runtime("agent-d", "sys", tier=ModelTier.FAST, tools=reg)

    call_count = {"n": 0}

    async def chat_responder(self, messages, tier=None, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _resp_with_tool_call(
                tool_call_id="c4", name="dictret", args={}
            )
        return _resp_simple("done")

    with patch.object(gw_mod.LLMGateway, "chat", chat_responder):
        activity = await rt.run("task")
    assert activity.status == "completed"


@pytest.mark.asyncio
async def test_lite_agent_gateway_disabled_recorded_as_error():
    rt = new_runtime("agent-disabled", "sys", tier=ModelTier.FAST)

    async def err(self, messages, tier=None, **kw):
        raise gw_mod.GatewayError("disabled")

    with patch.object(gw_mod.LLMGateway, "chat", err):
        activity = await rt.run("task")
    assert activity.status == "error"


def test_activity_to_dict_truncates():
    activity = hr.AgentActivity(
        agent_name="x",
        task="t",
        result="a" * 5000,
        messages=[{"role": "user", "content": "y"}] * 30,
    )
    d = activity.to_dict()
    assert len(d["result"]) == 4000
    assert len(d["messages"]) == 10


@pytest.mark.asyncio
async def test_activity_ledger_snapshot_filters():
    ledger = hr.ActivityLedger(capacity=10)
    for i in range(3):
        await ledger.record(hr.AgentActivity(agent_name="alpha", task=f"t{i}"))
        await ledger.record(hr.AgentActivity(agent_name="beta", task=f"t{i}"))
    assert len(ledger.snapshot()) == 6
    assert all(a["agent_name"] == "alpha" for a in ledger.snapshot(agent="alpha"))


def test_hermes_runtime_max_iter_zero():
    rt = HermesAgentRuntime(
        "agent-z",
        "sys",
        tier=ModelTier.FAST,
        max_iterations=0,
    )
    # max_iterations=0 means LiteAgent returns "[max iterations reached]" immediately.
    import asyncio

    activity = asyncio.get_event_loop().run_until_complete(rt.run("task"))
    assert activity.status == "completed"
    assert activity.result == "[max iterations reached]"


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _resp_simple(text: str):
    class R:
        content = text
        tool_calls: list = []
        raw: dict = {}

        class usage:
            prompt_tokens = 1
            completion_tokens = 1
            total_tokens = 2
            cost_usd = 0.0
            latency_ms = 1.0
            trace_id = ""
            model = "mock"
            cached = False

    return R()


def _resp_with_tool_call(tool_call_id: str, name: str, args: dict):
    class R:
        content = ""
        tool_calls = [
            {
                "id": tool_call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        ]
        raw: dict = {}

        class usage:
            prompt_tokens = 1
            completion_tokens = 1
            total_tokens = 2
            cost_usd = 0.0
            latency_ms = 1.0
            trace_id = ""
            model = "mock"
            cached = False

    return R()
