"""LangGraph workflow definitions.

LangGraph is our deterministic stateful workflow layer. Each graph is a
finite-state machine whose nodes are *either*:

  * Pure Python steps (enrichment, validation, gating, persistence)
  * Calls into Hermes specialist agents (RCA, PdM, Reporting)
  * Calls into downstream services via HTTP

LangGraph owns the *control flow*; Hermes owns the agent behavior; the
configured OpenAI-compatible gateway owns inference.

Four graphs are defined here:

  * `investigation`        — full anomaly → RCA → recommendation flow
  * `maintenance_approval` — PdM forecast → human approval → schedule
  * `remediation`          — pick a remediation action and notify
  * `escalation`           — repeated CRITICAL → page on-call + executive

All graphs share the `WorkflowState` typed dict so steps can read/write
the same blackboard.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any, Literal, TypedDict

import httpx
from langgraph.graph import END, StateGraph

from forgemind_common import (
    HermesAgentRuntime,
    ModelTier,
    ToolRegistry,
    get_settings,
    new_runtime,
)

log = logging.getLogger(__name__)
settings = get_settings()


# ----------------------------------------------------------------------
# Shared state
# ----------------------------------------------------------------------


def _merge_list(left: list, right: list) -> list:
    return (left or []) + (right or [])


class WorkflowState(TypedDict, total=False):
    # Inputs
    workflow: str
    incident_id: str
    machine_id: str
    operator_note: str

    # Enrichment results
    incident: dict[str, Any]
    telemetry: dict[str, Any]
    similar_incidents: list[dict[str, Any]]

    # AI outputs
    rca_report: dict[str, Any]
    pdm_forecast: dict[str, Any]
    severity: str
    recommendations: list[str]

    # Control
    needs_human_approval: bool
    approved: bool
    notified_channels: Annotated[list[str], _merge_list]
    trace: Annotated[list[dict[str, Any]], _merge_list]

    # Result
    status: Literal["pending", "running", "completed", "blocked_on_approval", "error"]
    error: str | None


def _trace(node: str, **fields: Any) -> dict[str, Any]:
    return {"node": node, **fields}


# ----------------------------------------------------------------------
# Reusable HTTP helpers
# ----------------------------------------------------------------------


async def _http_get(url: str, **params: Any) -> Any:
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(url, params=params or None)
        r.raise_for_status()
        return r.json()


async def _http_post(url: str, payload: dict[str, Any]) -> Any:
    async with httpx.AsyncClient(timeout=180.0) as c:
        r = await c.post(url, json=payload)
        r.raise_for_status()
        return r.json()


# ======================================================================
# Investigation workflow
# ======================================================================


async def node_fetch_incident(state: WorkflowState) -> WorkflowState:
    incs = await _http_get(
        f"{settings.anomaly_service_url}/api/v1/incidents", limit=200
    )
    incident = next(
        (i for i in incs if i.get("incident_id") == state.get("incident_id")), {}
    )
    return {
        "incident": incident,
        "machine_id": incident.get("machine_id", state.get("machine_id", "")),
        "trace": [_trace("fetch_incident", found=bool(incident))],
    }


async def node_fetch_telemetry(state: WorkflowState) -> WorkflowState:
    mid = state.get("machine_id")
    if not mid:
        return {"telemetry": {}, "trace": [_trace("fetch_telemetry", skipped=True)]}
    try:
        snap = await _http_get("http://telemetry-simulator:8000/api/v1/snapshot")
        match = next((s for s in snap if s.get("machine_id") == mid), {})
    except Exception as exc:  # noqa: BLE001
        match = {"_error": str(exc)}
    return {"telemetry": match, "trace": [_trace("fetch_telemetry", machine=mid)]}


async def node_run_rca(state: WorkflowState) -> WorkflowState:
    try:
        report = await _http_post(
            f"{settings.rca_service_url}/api/v1/rca/run",
            {"incident_id": state["incident_id"], "extra_context": state.get("operator_note")},
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "rca_report": {},
            "error": f"rca failed: {exc}",
            "trace": [_trace("run_rca", error=str(exc))],
        }
    return {
        "rca_report": report,
        "recommendations": report.get("recommended_actions", []),
        "trace": [_trace("run_rca", confidence=report.get("confidence"))],
    }


async def node_run_pdm(state: WorkflowState) -> WorkflowState:
    mid = state.get("machine_id")
    if not mid:
        return {"pdm_forecast": {}, "trace": [_trace("run_pdm", skipped=True)]}
    try:
        forecast = await _http_get(
            f"{settings.pdm_service_url}/api/v1/predictions/{mid}"
        )
    except Exception as exc:  # noqa: BLE001
        forecast = {"_error": str(exc)}
    return {"pdm_forecast": forecast, "trace": [_trace("run_pdm", machine=mid)]}


def node_assess_severity(state: WorkflowState) -> WorkflowState:
    """Pure-Python severity assessor. Combines incident severity with PdM risk."""
    inc_sev = (state.get("incident", {}) or {}).get("severity", "MEDIUM")
    pdm_risk = float((state.get("pdm_forecast", {}) or {}).get("risk_72h", 0.0) or 0.0)
    rca_conf = float((state.get("rca_report", {}) or {}).get("confidence", 0.0) or 0.0)
    # Promote severity if PdM risk and RCA confidence both high.
    sev_order = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
    idx = sev_order.index(inc_sev) if inc_sev in sev_order else 2
    if pdm_risk > 0.8 and rca_conf > 0.7:
        idx = min(len(sev_order) - 1, idx + 1)
    severity = sev_order[idx]
    return {
        "severity": severity,
        "needs_human_approval": severity in ("HIGH", "CRITICAL"),
        "trace": [_trace("assess_severity", severity=severity, pdm_risk=pdm_risk)],
    }


def node_human_approval_gate(state: WorkflowState) -> WorkflowState:
    """Branch point. If approval is needed and not present, the graph
    pauses by routing to `wait_for_approval`. In production this would
    persist state and resume on webhook; here we mark blocked."""
    if state.get("needs_human_approval") and not state.get("approved"):
        return {
            "status": "blocked_on_approval",
            "trace": [_trace("approval_gate", blocked=True)],
        }
    return {"trace": [_trace("approval_gate", blocked=False)]}


async def node_notify(state: WorkflowState) -> WorkflowState:
    sev = state.get("severity", "INFO")
    channels = ["ui"]
    if sev in ("HIGH", "CRITICAL"):
        channels.append("pager")
    if sev == "CRITICAL":
        channels.append("exec_email")
    log.info(
        "workflow.notify",
        extra={
            "channels": channels,
            "machine_id": state.get("machine_id"),
            "severity": sev,
        },
    )
    return {
        "notified_channels": channels,
        "status": "completed",
        "trace": [_trace("notify", channels=channels)],
    }


def build_investigation_graph() -> Any:
    g = StateGraph(WorkflowState)
    g.add_node("fetch_incident", node_fetch_incident)
    g.add_node("fetch_telemetry", node_fetch_telemetry)
    g.add_node("run_rca", node_run_rca)
    g.add_node("run_pdm", node_run_pdm)
    g.add_node("assess_severity", node_assess_severity)
    g.add_node("approval_gate", node_human_approval_gate)
    g.add_node("notify", node_notify)

    g.set_entry_point("fetch_incident")
    g.add_edge("fetch_incident", "fetch_telemetry")
    g.add_edge("fetch_telemetry", "run_rca")
    g.add_edge("run_rca", "run_pdm")
    g.add_edge("run_pdm", "assess_severity")
    g.add_edge("assess_severity", "approval_gate")

    def _after_approval(state: WorkflowState) -> str:
        return "wait" if state.get("status") == "blocked_on_approval" else "go"

    g.add_conditional_edges("approval_gate", _after_approval, {"go": "notify", "wait": END})
    g.add_edge("notify", END)
    return g.compile()


# ======================================================================
# Maintenance Approval workflow
# ======================================================================


async def node_predict_failure(state: WorkflowState) -> WorkflowState:
    mid = state["machine_id"]
    forecast = await _http_get(f"{settings.pdm_service_url}/api/v1/predictions/{mid}")
    return {
        "pdm_forecast": forecast,
        "trace": [_trace("predict_failure", risk_72h=forecast.get("risk_72h"))],
    }


def node_propose_window(state: WorkflowState) -> WorkflowState:
    f = state.get("pdm_forecast", {}) or {}
    return {
        "recommendations": [
            f"Schedule {state['machine_id']} for maintenance "
            f"between {f.get('recommended_window_start')} and {f.get('recommended_window_end')}"
        ],
        "trace": [_trace("propose_window")],
    }


def node_require_approval(state: WorkflowState) -> WorkflowState:
    risk = float((state.get("pdm_forecast", {}) or {}).get("risk_72h", 0.0) or 0.0)
    needs = risk > 0.4
    return {
        "needs_human_approval": needs,
        "trace": [_trace("require_approval", needs=needs)],
    }


def node_schedule(state: WorkflowState) -> WorkflowState:
    if state.get("needs_human_approval") and not state.get("approved"):
        return {
            "status": "blocked_on_approval",
            "trace": [_trace("schedule", blocked=True)],
        }
    return {
        "status": "completed",
        "trace": [_trace("schedule", scheduled=True)],
    }


def build_maintenance_approval_graph() -> Any:
    g = StateGraph(WorkflowState)
    g.add_node("predict_failure", node_predict_failure)
    g.add_node("propose_window", node_propose_window)
    g.add_node("require_approval", node_require_approval)
    g.add_node("schedule", node_schedule)
    g.set_entry_point("predict_failure")
    g.add_edge("predict_failure", "propose_window")
    g.add_edge("propose_window", "require_approval")
    g.add_edge("require_approval", "schedule")
    g.add_edge("schedule", END)
    return g.compile()


# ======================================================================
# Remediation workflow
# ======================================================================


def _remediation_agent() -> HermesAgentRuntime:
    return new_runtime(
        agent_name="remediation-agent",
        system_prompt=(
            "You are the Remediation Agent. Given an RCA report and machine context, "
            "produce a short ordered list of remediation actions (one verb + object + timeframe each). "
            "Reply as a JSON list of strings, nothing else."
        ),
        tier=ModelTier.FAST,
        tools=ToolRegistry(),
        max_iterations=3,
    )


_REMEDIATION = _remediation_agent()


async def node_choose_remediation(state: WorkflowState) -> WorkflowState:
    rca = state.get("rca_report", {}) or {}
    task = (
        "RCA summary: " + (rca.get("summary") or "")
        + "\nFindings: " + json.dumps(rca.get("findings") or [])[:1500]
        + "\nReturn JSON list of remediation actions, max 5."
    )
    activity = await _REMEDIATION.run(task)
    try:
        actions = json.loads((activity.result or "").strip())
        if not isinstance(actions, list):
            actions = []
    except Exception:  # noqa: BLE001
        actions = []
    return {
        "recommendations": actions,
        "trace": [_trace("choose_remediation", n=len(actions))],
    }


def build_remediation_graph() -> Any:
    g = StateGraph(WorkflowState)
    g.add_node("choose_remediation", node_choose_remediation)
    g.add_node("notify", node_notify)
    g.set_entry_point("choose_remediation")
    g.add_edge("choose_remediation", "notify")
    g.add_edge("notify", END)
    return g.compile()


# ======================================================================
# Escalation workflow
# ======================================================================


async def node_check_recent_criticals(state: WorkflowState) -> WorkflowState:
    incs = await _http_get(
        f"{settings.anomaly_service_url}/api/v1/incidents",
        machine_id=state.get("machine_id"),
        severity="CRITICAL",
        limit=20,
    )
    return {
        "incident": {"recent_critical_count": len(incs)},
        "trace": [_trace("check_recent_criticals", n=len(incs))],
    }


def node_decide_escalation(state: WorkflowState) -> WorkflowState:
    n = (state.get("incident") or {}).get("recent_critical_count", 0)
    sev = "CRITICAL" if n >= 3 else "HIGH" if n >= 1 else "MEDIUM"
    return {
        "severity": sev,
        "trace": [_trace("decide_escalation", severity=sev)],
    }


def build_escalation_graph() -> Any:
    g = StateGraph(WorkflowState)
    g.add_node("check_recent_criticals", node_check_recent_criticals)
    g.add_node("decide_escalation", node_decide_escalation)
    g.add_node("notify", node_notify)
    g.set_entry_point("check_recent_criticals")
    g.add_edge("check_recent_criticals", "decide_escalation")
    g.add_edge("decide_escalation", "notify")
    g.add_edge("notify", END)
    return g.compile()


# ======================================================================
# Registry
# ======================================================================


GRAPHS: dict[str, Any] = {
    "investigation": build_investigation_graph(),
    "maintenance_approval": build_maintenance_approval_graph(),
    "remediation": build_remediation_graph(),
    "escalation": build_escalation_graph(),
}
