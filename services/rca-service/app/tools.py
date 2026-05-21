"""Tools exposed to the RCA Hermes agent.

These are plain async Python functions that the agent can invoke. The
HermesAgentRuntime dispatches them locally and feeds results back into
the conversation.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
from sqlalchemy import desc, select, text

from forgemind_common import ToolRegistry, get_gateway, get_settings
from forgemind_common.db import session_scope

from .models import IncidentMemory

settings = get_settings()


async def _fetch_incident(incident_id: str) -> dict[str, Any]:
    """Look up an incident in the anomaly-detection service."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{settings.anomaly_service_url}/api/v1/incidents", params={"limit": 200})
        r.raise_for_status()
        for inc in r.json():
            if inc["incident_id"] == incident_id:
                return inc
    return {}


async def _telemetry_context(machine_id: str) -> dict[str, Any]:
    """Pull a recent telemetry snapshot for the machine."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"http://telemetry-simulator:8000/api/v1/snapshot"
        )
        if r.status_code == 200:
            for row in r.json():
                if row.get("machine_id") == machine_id:
                    return row
    return {}


async def _similar_incidents(query_text: str, k: int = 5) -> list[dict[str, Any]]:
    """Vector-similarity search over past incidents (pgvector)."""
    gw = get_gateway()
    try:
        [emb] = await gw.embed([query_text])
    except Exception:  # noqa: BLE001
        return []
    async with session_scope() as session:
        # pgvector cosine distance operator: <=>
        stmt = (
            select(
                IncidentMemory.incident_id,
                IncidentMemory.machine_id,
                IncidentMemory.severity,
                IncidentMemory.summary,
                IncidentMemory.embedding.cosine_distance(emb).label("distance"),
            )
            .order_by("distance")
            .limit(k)
        )
        rows = (await session.execute(stmt)).all()
    return [
        {
            "incident_id": str(r.incident_id),
            "machine_id": r.machine_id,
            "severity": r.severity,
            "summary": r.summary,
            "similarity": round(1.0 - float(r.distance), 4),
        }
        for r in rows
    ]


async def _persist_memory(
    *,
    incident_id: str,
    machine_id: str,
    machine_type: str,
    severity: str,
    summary: str,
) -> dict[str, Any]:
    gw = get_gateway()
    try:
        [emb] = await gw.embed([summary])
    except Exception:  # noqa: BLE001
        return {"persisted": False, "reason": "embedding failed"}
    async with session_scope() as session:
        mem = IncidentMemory(
            incident_id=uuid.UUID(incident_id) if isinstance(incident_id, str) else incident_id,
            machine_id=machine_id,
            machine_type=machine_type,
            severity=severity,
            summary=summary,
            embedding=emb,
        )
        session.add(mem)
    return {"persisted": True}


def build_rca_tools() -> ToolRegistry:
    """Tool registry handed to the RCA Hermes agent."""
    reg = ToolRegistry()

    @reg.register(
        name="get_incident",
        description="Fetch the full incident record by incident_id.",
        parameters={
            "type": "object",
            "properties": {"incident_id": {"type": "string"}},
            "required": ["incident_id"],
        },
    )
    async def get_incident(incident_id: str) -> str:
        return json.dumps(await _fetch_incident(incident_id), default=str)

    @reg.register(
        name="get_telemetry_context",
        description="Get the most recent telemetry snapshot for a machine.",
        parameters={
            "type": "object",
            "properties": {"machine_id": {"type": "string"}},
            "required": ["machine_id"],
        },
    )
    async def get_telemetry_context(machine_id: str) -> str:
        return json.dumps(await _telemetry_context(machine_id), default=str)

    @reg.register(
        name="search_similar_incidents",
        description="Semantic search over past incidents. Returns up to k closest matches.",
        parameters={
            "type": "object",
            "properties": {
                "query_text": {"type": "string"},
                "k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
            },
            "required": ["query_text"],
        },
    )
    async def search_similar_incidents(query_text: str, k: int = 5) -> str:
        return json.dumps(await _similar_incidents(query_text, k), default=str)

    @reg.register(
        name="record_incident_memory",
        description="Persist an incident summary into the long-term vector memory.",
        parameters={
            "type": "object",
            "properties": {
                "incident_id": {"type": "string"},
                "machine_id": {"type": "string"},
                "machine_type": {"type": "string"},
                "severity": {"type": "string"},
                "summary": {"type": "string"},
            },
            "required": ["incident_id", "machine_id", "summary", "severity"],
        },
    )
    async def record_incident_memory(
        incident_id: str,
        machine_id: str,
        severity: str,
        summary: str,
        machine_type: str = "",
    ) -> str:
        return json.dumps(
            await _persist_memory(
                incident_id=incident_id,
                machine_id=machine_id,
                machine_type=machine_type,
                severity=severity,
                summary=summary,
            )
        )

    return reg
