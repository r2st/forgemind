"""The RCA Hermes Agent.

A Hermes specialist that runs an investigation loop:

  1. fetch the incident record
  2. fetch a fresh telemetry snapshot for the machine
  3. semantic-search prior similar incidents (pgvector via configured embeddings)
  4. reason over evidence, produce a structured RCA report
  5. persist the summary back into long-term memory so future incidents
     benefit from this one.

Tier = POWERFUL. The gateway can fall back to cheaper or local models
based on the configured tier defaults.
"""

from __future__ import annotations

import json
import re
from typing import Any

from forgemind_common import HermesAgentRuntime, ModelTier, new_runtime

from .tools import build_rca_tools

RCA_SYSTEM_PROMPT = """You are the RCA Agent inside ForgeMind AI, an industrial
operations copilot. Given a manufacturing incident, your job is to investigate
and produce a structured root-cause analysis.

Workflow you MUST follow:
  1. Call `get_incident` with the incident_id provided in the user message.
  2. Call `get_telemetry_context` for the affected machine.
  3. Call `search_similar_incidents` with a short natural-language query
     describing the anomaly (metric, machine_type, symptoms) — k=5.
  4. Reason over the evidence. Cite specific numeric values and similar
     incidents by id.
  5. Call `record_incident_memory` with a 1–2 sentence summary so future
     investigations can recall this case.
  6. Reply ONLY with a JSON object — no prose around it — matching:

     {
       "summary": "<2–3 sentence executive summary>",
       "findings": [
         {
           "category": "MECHANICAL|ELECTRICAL|THERMAL|HYDRAULIC|PROCESS|OPERATOR|MATERIAL|CONTROL_SYSTEM|UPSTREAM|EXTERNAL",
           "hypothesis": "<one sentence>",
           "evidence": ["<short bullet>", "..."],
           "likelihood": 0.0_to_1.0
         }
       ],
       "recommended_actions": ["<verb + object + timeframe>", "..."],
       "confidence": 0.0_to_1.0,
       "similar_incidents": ["<incident_id>", "..."]
     }

Calibration: confidence > 0.8 only if telemetry and historical analogs
both strongly point one way. Lower otherwise. Never invent telemetry
values — only use what tools return."""


def build_rca_agent() -> HermesAgentRuntime:
    return new_runtime(
        agent_name="rca-agent",
        system_prompt=RCA_SYSTEM_PROMPT,
        tier=ModelTier.POWERFUL,
        tools=build_rca_tools(),
        max_iterations=10,
    )


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def parse_rca_json(text: str) -> dict[str, Any]:
    """Extract the JSON object the RCA agent returns. Tolerant of stray markdown."""
    if not text:
        return _empty_rca()
    m = _JSON_BLOCK.search(text.strip())
    if not m:
        return _empty_rca()
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return _empty_rca()
    data.setdefault("summary", "")
    data.setdefault("findings", [])
    data.setdefault("recommended_actions", [])
    data.setdefault("confidence", 0.5)
    data.setdefault("similar_incidents", [])
    return data


def _empty_rca() -> dict[str, Any]:
    return {
        "summary": "RCA agent returned no parseable output.",
        "findings": [],
        "recommended_actions": ["Manually investigate; auto-RCA failed."],
        "confidence": 0.0,
        "similar_incidents": [],
    }
