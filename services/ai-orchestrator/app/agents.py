"""Specialist Hermes agents managed by the supervisor.

Each agent is a HermesAgentRuntime instance with its own system prompt
and tool registry. The supervisor calls them via the `delegate_to_agent`
tool — that's how multi-agent collaboration works here.
"""

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

# ----------------------------------------------------------------------
# Shared HTTP helpers (used by tools)
# ----------------------------------------------------------------------


async def _http_get(url: str, **params: Any) -> Any:
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(url, params=params or None)
        r.raise_for_status()
        return r.json()


async def _http_post(url: str, payload: dict[str, Any]) -> Any:
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        return r.json()


# ----------------------------------------------------------------------
# Monitoring Agent
# ----------------------------------------------------------------------


def _monitoring_tools() -> ToolRegistry:
    reg = ToolRegistry()

    @reg.register(
        name="list_recent_incidents",
        description="List recent incidents (optionally filtered by machine or severity).",
        parameters={
            "type": "object",
            "properties": {
                "machine_id": {"type": "string"},
                "severity": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    )
    async def list_recent_incidents(
        machine_id: str | None = None, severity: str | None = None, limit: int = 20
    ) -> str:
        params: dict[str, Any] = {"limit": limit}
        if machine_id:
            params["machine_id"] = machine_id
        if severity:
            params["severity"] = severity
        data = await _http_get(f"{settings.anomaly_service_url}/api/v1/incidents", **params)
        return json.dumps(data, default=str)

    @reg.register(
        name="get_machine_snapshot",
        description="Get a live telemetry snapshot for every machine in the plant.",
        parameters={"type": "object", "properties": {}},
    )
    async def get_machine_snapshot() -> str:
        data = await _http_get("http://telemetry-simulator:8000/api/v1/snapshot")
        return json.dumps(data, default=str)

    return reg


MONITORING_PROMPT = """You are the Monitoring Agent inside ForgeMind AI.
Your job is to triage the operational state of the plant: list active incidents,
identify the most pressing problems, and recommend which specialist to engage.
Always cite incident_ids, machine_ids, and concrete metric values."""


def build_monitoring_agent() -> HermesAgentRuntime:
    return new_runtime(
        "monitoring-agent",
        MONITORING_PROMPT,
        tier=ModelTier.FAST,
        tools=_monitoring_tools(),
        max_iterations=6,
    )


# ----------------------------------------------------------------------
# Predictive Maintenance Agent
# ----------------------------------------------------------------------


def _pdm_tools() -> ToolRegistry:
    reg = ToolRegistry()

    @reg.register(
        name="recent_incidents_for_machine",
        description="Recent incidents for a single machine (last N).",
        parameters={
            "type": "object",
            "properties": {
                "machine_id": {"type": "string"},
                "limit": {"type": "integer", "default": 30},
            },
            "required": ["machine_id"],
        },
    )
    async def recent_incidents_for_machine(machine_id: str, limit: int = 30) -> str:
        data = await _http_get(
            f"{settings.anomaly_service_url}/api/v1/incidents",
            machine_id=machine_id,
            limit=limit,
        )
        return json.dumps(data, default=str)

    @reg.register(
        name="get_machine_snapshot",
        description="Live telemetry snapshot for every machine.",
        parameters={"type": "object", "properties": {}},
    )
    async def get_machine_snapshot() -> str:
        data = await _http_get("http://telemetry-simulator:8000/api/v1/snapshot")
        return json.dumps(data, default=str)

    return reg


PDM_PROMPT = """You are the Predictive Maintenance Agent inside ForgeMind AI.
Given a machine, estimate failure risk over the next 24/72h and recommend a
maintenance window. Use recent incidents + telemetry trends. Always return
a JSON object:

{
  "machine_id": "...",
  "risk_24h": 0..1,
  "risk_72h": 0..1,
  "estimated_failure_in_hours": int,
  "recommended_window_hours_from_now": [start_h, end_h],
  "contributing_signals": ["..."],
  "rationale": "1-2 sentences"
}
No prose outside the JSON."""


def build_pdm_agent() -> HermesAgentRuntime:
    return new_runtime(
        "predictive-maintenance-agent",
        PDM_PROMPT,
        tier=ModelTier.POWERFUL,
        tools=_pdm_tools(),
        max_iterations=8,
    )


# ----------------------------------------------------------------------
# Production Optimization Agent
# ----------------------------------------------------------------------


def _opt_tools() -> ToolRegistry:
    reg = ToolRegistry()

    @reg.register(
        name="get_machine_snapshot",
        description="Live telemetry for every machine in the plant.",
        parameters={"type": "object", "properties": {}},
    )
    async def get_machine_snapshot() -> str:
        data = await _http_get("http://telemetry-simulator:8000/api/v1/snapshot")
        return json.dumps(data, default=str)

    @reg.register(
        name="list_recent_incidents",
        description="Recent incidents across the plant.",
        parameters={
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 50}},
        },
    )
    async def list_recent_incidents(limit: int = 50) -> str:
        data = await _http_get(
            f"{settings.anomaly_service_url}/api/v1/incidents", limit=limit
        )
        return json.dumps(data, default=str)

    return reg


OPT_PROMPT = """You are the Production Optimization Agent inside ForgeMind AI.
Identify throughput bottlenecks and propose line balancing or scheduling tweaks.
Cite machine_ids, units_produced, defect counts. Return a JSON object:

{
  "bottlenecks": [{"machine_id": "...", "reason": "...", "impact_units_per_hour": int}],
  "recommendations": ["..."],
  "expected_throughput_uplift_pct": float
}
No prose outside JSON."""


def build_optimization_agent() -> HermesAgentRuntime:
    return new_runtime(
        "production-optimization-agent",
        OPT_PROMPT,
        tier=ModelTier.POWERFUL,
        tools=_opt_tools(),
        max_iterations=8,
    )


# ----------------------------------------------------------------------
# Reporting Agent
# ----------------------------------------------------------------------


def _reporting_tools() -> ToolRegistry:
    reg = ToolRegistry()

    @reg.register(
        name="list_recent_incidents",
        description="Recent incidents across the plant.",
        parameters={
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 100}},
        },
    )
    async def list_recent_incidents(limit: int = 100) -> str:
        data = await _http_get(
            f"{settings.anomaly_service_url}/api/v1/incidents", limit=limit
        )
        return json.dumps(data, default=str)

    @reg.register(
        name="list_recent_rca",
        description="Recent RCA reports.",
        parameters={
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 25}},
        },
    )
    async def list_recent_rca(limit: int = 25) -> str:
        data = await _http_get(
            f"{settings.rca_service_url}/api/v1/rca/reports", limit=limit
        )
        return json.dumps(data, default=str)

    return reg


REPORTING_PROMPT = """You are the Reporting Agent inside ForgeMind AI. Produce
a concise executive summary of plant operations covering: incidents by severity,
top affected machines, RCA highlights, recommended actions. Use plain English,
no markdown. Limit to ~250 words."""


def build_reporting_agent() -> HermesAgentRuntime:
    return new_runtime(
        "reporting-agent",
        REPORTING_PROMPT,
        tier=ModelTier.POWERFUL,
        tools=_reporting_tools(),
        max_iterations=6,
    )


# ----------------------------------------------------------------------
# RCA Agent — delegated via HTTP to the RCA service
# ----------------------------------------------------------------------


async def call_rca_service(incident_id: str, extra_context: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"incident_id": incident_id}
    if extra_context:
        payload["extra_context"] = extra_context
    return await _http_post(f"{settings.rca_service_url}/api/v1/rca/run", payload)


# ----------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------


def build_specialist_registry() -> dict[str, HermesAgentRuntime]:
    return {
        "monitoring": build_monitoring_agent(),
        "predictive_maintenance": build_pdm_agent(),
        "production_optimization": build_optimization_agent(),
        "reporting": build_reporting_agent(),
    }
