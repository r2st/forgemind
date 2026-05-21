"""The Supervisor: a Hermes agent whose only tool is `delegate_to_agent`.

It reads a free-form operator request, decides which specialist(s) to
invoke, and synthesises the result. This is the multi-agent layer the
spec calls for: Hermes orchestrating Hermes.
"""

from __future__ import annotations

import json
from typing import Any

from forgemind_common import HermesAgentRuntime, ModelTier, ToolRegistry, new_runtime

from .agents import build_specialist_registry, call_rca_service


SUPERVISOR_PROMPT = """You are the Supervisor Agent inside ForgeMind AI.
You coordinate a team of specialist Hermes agents:

  * monitoring             — plant state, incident listing, triage
  * predictive_maintenance — failure risk forecasts per machine
  * production_optimization — bottleneck + throughput analysis
  * reporting              — executive operational summaries
  * rca                    — full root-cause investigation of one incident_id

Given an operator request, decide which specialists to invoke (one or more),
delegate via `delegate_to_agent`, then synthesize a final answer in plain English.
If the user mentions an incident_id, prefer delegating to `rca`. If they ask for
a shift summary or executive report, delegate to `reporting`. Always keep the
final answer concise (≤ 8 sentences) and cite the specialists you consulted."""


def build_supervisor() -> HermesAgentRuntime:
    specialists = build_specialist_registry()
    reg = ToolRegistry()

    @reg.register(
        name="delegate_to_agent",
        description="Run a specialist agent with a sub-task and get its answer back.",
        parameters={
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "enum": [
                        "monitoring",
                        "predictive_maintenance",
                        "production_optimization",
                        "reporting",
                        "rca",
                    ],
                },
                "task": {"type": "string"},
                "incident_id": {
                    "type": "string",
                    "description": "Required only when agent='rca'.",
                },
            },
            "required": ["agent", "task"],
        },
    )
    async def delegate_to_agent(
        agent: str, task: str, incident_id: str | None = None
    ) -> str:
        if agent == "rca":
            if not incident_id:
                return json.dumps({"error": "rca requires incident_id"})
            try:
                result = await call_rca_service(incident_id, extra_context=task)
                return json.dumps(result, default=str)
            except Exception as exc:  # noqa: BLE001
                return json.dumps({"error": str(exc)})
        runtime = specialists.get(agent)
        if runtime is None:
            return json.dumps({"error": f"unknown agent {agent}"})
        activity = await runtime.run(task)
        return json.dumps(
            {
                "agent": agent,
                "status": activity.status,
                "result": activity.result,
                "activity_id": activity.activity_id,
                "tool_calls": activity.tool_calls,
            },
            default=str,
        )

    @reg.register(
        name="list_specialists",
        description="Show the list of specialist agents available for delegation.",
        parameters={"type": "object", "properties": {}},
    )
    async def list_specialists() -> str:
        return json.dumps(list(specialists.keys()) + ["rca"])

    return new_runtime(
        "supervisor-agent",
        SUPERVISOR_PROMPT,
        tier=ModelTier.POWERFUL,
        tools=reg,
        max_iterations=10,
    )
