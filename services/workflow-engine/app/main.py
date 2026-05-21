"""Workflow Engine Service — LangGraph runtime over Hermes agents."""

from __future__ import annotations

import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from forgemind_common import get_logger, setup_logging
from forgemind_common.observability import install_metrics

from .graphs import GRAPHS, WorkflowState

setup_logging("workflow-engine")
log = get_logger(__name__)

app = FastAPI(title="ForgeMind Workflow Engine (LangGraph)", version="0.1.0")
install_metrics(app, "workflow-engine")


# In-memory run history. Production: persist to Postgres + LangGraph
# checkpointer (Postgres or Redis) for true resumability.
RUN_HISTORY: deque[dict[str, Any]] = deque(maxlen=300)


class WorkflowRunRequest(BaseModel):
    incident_id: str | None = None
    machine_id: str | None = None
    operator_note: str | None = None
    approved: bool = False


@app.get("/api/v1/workflows")
async def list_workflows() -> list[dict[str, Any]]:
    return [{"name": k, "nodes": list(g.get_graph().nodes)} for k, g in GRAPHS.items()]


@app.post("/api/v1/workflows/{name}/run")
async def run_workflow(name: str, req: WorkflowRunRequest) -> dict[str, Any]:
    graph = GRAPHS.get(name)
    if graph is None:
        raise HTTPException(404, f"unknown workflow {name}")
    state: WorkflowState = {
        "workflow": name,
        "status": "running",
    }
    if req.incident_id:
        state["incident_id"] = req.incident_id
    if req.machine_id:
        state["machine_id"] = req.machine_id
    if req.operator_note:
        state["operator_note"] = req.operator_note
    if req.approved:
        state["approved"] = True

    run_id = str(uuid.uuid4())
    started = datetime.now(timezone.utc)
    t0 = time.perf_counter()
    try:
        final_state = await graph.ainvoke(state)
        status = final_state.get("status") or "completed"
    except Exception as exc:  # noqa: BLE001
        final_state = {**state, "status": "error", "error": str(exc)}
        status = "error"
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    rec = {
        "run_id": run_id,
        "workflow": name,
        "started_at": started.isoformat(),
        "elapsed_ms": elapsed_ms,
        "status": status,
        "state": _serialize_state(final_state),
    }
    RUN_HISTORY.appendleft(rec)
    return rec


@app.get("/api/v1/workflows/runs")
async def list_runs(limit: int = 50, name: str | None = None) -> list[dict[str, Any]]:
    items = list(RUN_HISTORY)
    if name:
        items = [r for r in items if r["workflow"] == name]
    return items[:limit]


@app.get("/api/v1/workflows/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    for r in RUN_HISTORY:
        if r["run_id"] == run_id:
            return r
    raise HTTPException(404, "run not found")


def _serialize_state(state: dict[str, Any]) -> dict[str, Any]:
    # Pydantic models / sets / etc — coerce to JSON-friendly via str fallback
    import json

    return json.loads(json.dumps(state, default=str))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
