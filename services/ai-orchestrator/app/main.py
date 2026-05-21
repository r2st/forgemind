"""AI Orchestrator service — exposes the Hermes supervisor + activity ledger."""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from forgemind_common import get_activity_ledger, get_logger, setup_logging
from forgemind_common.observability import install_metrics

from .supervisor import build_supervisor

setup_logging("ai-orchestrator")
log = get_logger(__name__)

app = FastAPI(title="ForgeMind AI Orchestrator", version="0.1.0")
install_metrics(app, "ai-orchestrator")

supervisor = build_supervisor()
ledger = get_activity_ledger()


class AgentRunRequest(BaseModel):
    task: str
    history: list[dict] | None = None
    task_id: str | None = None


@app.post("/api/v1/agents/run")
async def run_agent(req: AgentRunRequest) -> dict:
    activity = await supervisor.run(req.task, history=req.history, task_id=req.task_id)
    return activity.to_dict()


@app.get("/api/v1/agents/activity")
async def agent_activity(limit: int = 100, agent_name: str | None = None) -> list[dict]:
    """Feeds the AI Agent Activity UI page."""
    return ledger.snapshot(agent=agent_name, limit=limit)


@app.get("/api/v1/agents")
async def list_agents() -> list[dict]:
    return [
        {"name": "supervisor", "tier": supervisor.tier.value, "role": "router"},
        {"name": "monitoring-agent", "tier": "fast", "role": "triage"},
        {"name": "predictive-maintenance-agent", "tier": "powerful", "role": "forecast"},
        {"name": "rca-agent", "tier": "powerful", "role": "investigation"},
        {"name": "production-optimization-agent", "tier": "powerful", "role": "bottleneck"},
        {"name": "reporting-agent", "tier": "powerful", "role": "summary"},
        {"name": "chatops-agent", "tier": "powerful", "role": "operator chat"},
    ]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
