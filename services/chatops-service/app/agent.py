"""ChatOps Hermes Agent — the operator-facing conversational interface."""

from __future__ import annotations

import json
from typing import Any

import httpx

from forgemind_common import (
    HermesAgentRuntime,
    ModelTier,
    ToolRegistry,
    get_settings,
    new_runtime,
)

settings = get_settings()


async def _http_get(url: str, **params: Any) -> Any:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url, params=params or None)
        r.raise_for_status()
        return r.json()


async def _http_post(url: str, payload: dict[str, Any]) -> Any:
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        return r.json()


def build_chat_tools() -> ToolRegistry:
    reg = ToolRegistry()

    @reg.register(
        name="query_incidents",
        description="List recent incidents. Optional filters: machine_id, severity, limit.",
        parameters={
            "type": "object",
            "properties": {
                "machine_id": {"type": "string"},
                "severity": {"type": "string"},
                "limit": {"type": "integer", "default": 25},
            },
        },
    )
    async def query_incidents(
        machine_id: str | None = None,
        severity: str | None = None,
        limit: int = 25,
    ) -> str:
        params: dict[str, Any] = {"limit": limit}
        if machine_id:
            params["machine_id"] = machine_id
        if severity:
            params["severity"] = severity
        return json.dumps(
            await _http_get(f"{settings.anomaly_service_url}/api/v1/incidents", **params),
            default=str,
        )

    @reg.register(
        name="get_machine_telemetry",
        description="Live telemetry snapshot for all machines.",
        parameters={"type": "object", "properties": {}},
    )
    async def get_machine_telemetry() -> str:
        return json.dumps(
            await _http_get("http://telemetry-simulator:8000/api/v1/snapshot"),
            default=str,
        )

    @reg.register(
        name="run_rca",
        description="Run a full RCA investigation on a specific incident_id.",
        parameters={
            "type": "object",
            "properties": {"incident_id": {"type": "string"}},
            "required": ["incident_id"],
        },
    )
    async def run_rca(incident_id: str) -> str:
        return json.dumps(
            await _http_post(
                f"{settings.rca_service_url}/api/v1/rca/run",
                {"incident_id": incident_id},
            ),
            default=str,
        )

    @reg.register(
        name="ask_supervisor",
        description="Delegate a complex multi-step question to the supervisor agent.",
        parameters={
            "type": "object",
            "properties": {"task": {"type": "string"}},
            "required": ["task"],
        },
    )
    async def ask_supervisor(task: str) -> str:
        return json.dumps(
            await _http_post(
                f"{settings.orchestrator_url}/api/v1/agents/run", {"task": task}
            ),
            default=str,
        )

    @reg.register(
        name="list_agent_activity",
        description="Recent Hermes agent runs across the platform.",
        parameters={
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 50}},
        },
    )
    async def list_agent_activity(limit: int = 50) -> str:
        return json.dumps(
            await _http_get(
                f"{settings.orchestrator_url}/api/v1/agents/activity", limit=limit
            ),
            default=str,
        )

    return reg


CHAT_SYSTEM_PROMPT = """You are the ChatOps Agent inside ForgeMind AI, talking
to a plant operator or shift manager. Be concise, factual, and grounded in
real telemetry — always use tools to fetch data instead of guessing.

When the user asks a complex multi-step question (covering RCA, optimization,
and reporting at once) call `ask_supervisor`. For simple lookups use the more
targeted tools (`query_incidents`, `get_machine_telemetry`, `run_rca`).
Cite machine_ids and severity levels in every answer. Keep responses
short — under 8 sentences — unless the user asks for detail."""


async def build_chatops_agent_with_mcp() -> HermesAgentRuntime:
    """Build the ChatOps agent with internal tools + TrueFoundry MCP Gateway tools.

    Falls back to internal-only tools if the MCP gateway isn't reachable
    (e.g. running tests with no TFY credentials).
    """
    from forgemind_common import get_mcp_gateway

    tools = build_chat_tools()
    try:
        mcp = get_mcp_gateway()
        mcp_tools = await mcp.build_tool_registry(
            servers=settings.tfy_mcp_enabled_servers,
            prefix_with_server=True,
        )
        # Merge MCP tools into the chat registry (internal tools win on name).
        for name, tool in mcp_tools._tools.items():
            tools._tools.setdefault(name, tool)
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("chatops.mcp_tools_unavailable", exc_info=True)
    return new_runtime(
        "chatops-agent",
        CHAT_SYSTEM_PROMPT,
        tier=ModelTier.POWERFUL,
        tools=tools,
        max_iterations=10,
    )


def build_chatops_agent() -> HermesAgentRuntime:
    """Sync variant kept for backwards compat — internal tools only."""
    return new_runtime(
        "chatops-agent",
        CHAT_SYSTEM_PROMPT,
        tier=ModelTier.POWERFUL,
        tools=build_chat_tools(),
        max_iterations=8,
    )
