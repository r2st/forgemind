"""RCA Service — FastAPI front for the RCA Hermes agent."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select

from forgemind_common import get_activity_ledger, get_logger, setup_logging
from forgemind_common.db import get_engine, session_scope
from forgemind_common.observability import install_metrics

from .agent import build_rca_agent, parse_rca_json
from .models import Base, RCAReportORM

setup_logging("rca-service")
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    eng = get_engine()
    async with eng.begin() as conn:
        # Make sure the pgvector extension exists before creating tables
        # that reference Vector columns.
        from sqlalchemy import text

        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    log.info("rca_service.started")
    yield


app = FastAPI(title="ForgeMind RCA Service", version="0.1.0", lifespan=lifespan)
install_metrics(app, "rca-service")

agent = build_rca_agent()
ledger = get_activity_ledger()


class RCARunRequest(BaseModel):
    incident_id: str
    extra_context: str | None = None


@app.post("/api/v1/rca/run")
async def run_rca(req: RCARunRequest) -> dict:
    task = (
        f"Investigate incident_id={req.incident_id}. "
        "Follow the workflow exactly and return the JSON object only."
    )
    if req.extra_context:
        task += f"\n\nAdditional operator context: {req.extra_context}"

    activity = await agent.run(task)
    if activity.status != "completed":
        raise HTTPException(500, f"agent error: {activity.error}")

    parsed = parse_rca_json(activity.result or "")
    incident_uuid = uuid.UUID(req.incident_id)
    # We can't easily resolve machine_id without re-fetching, so use ""
    # if the agent didn't surface it. The activity messages have the
    # info if the operator wants to inspect.
    machine_id = ""
    for msg in reversed(activity.messages):
        if msg.get("role") == "tool" and "machine_id" in str(msg.get("content", "")):
            try:
                import json

                payload = json.loads(msg["content"])
                if isinstance(payload, dict) and payload.get("machine_id"):
                    machine_id = payload["machine_id"]
                    break
            except Exception:  # noqa: BLE001
                pass

    similar_ids = []
    for sid in parsed.get("similar_incidents", []) or []:
        try:
            similar_ids.append(str(uuid.UUID(sid)))
        except (ValueError, TypeError):
            continue

    async with session_scope() as session:
        report = RCAReportORM(
            incident_id=incident_uuid,
            machine_id=machine_id,
            summary=parsed["summary"],
            findings=parsed["findings"],
            recommended_actions=parsed["recommended_actions"],
            confidence=float(parsed.get("confidence", 0.5)),
            similar_incidents=similar_ids,
            model_used=activity.model_used,
            tokens_used=activity.tokens_in + activity.tokens_out,
            cost_usd=activity.cost_usd,
            activity_id=activity.activity_id,
        )
        session.add(report)
        await session.flush()
        rid = report.report_id

    return {
        "report_id": str(rid),
        "incident_id": req.incident_id,
        "summary": parsed["summary"],
        "findings": parsed["findings"],
        "recommended_actions": parsed["recommended_actions"],
        "confidence": parsed["confidence"],
        "similar_incidents": similar_ids,
        "activity_id": activity.activity_id,
        "model_used": activity.model_used,
        "cost_usd": activity.cost_usd,
    }


@app.get("/api/v1/rca/reports")
async def list_reports(limit: int = 50) -> list[dict]:
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(RCAReportORM).order_by(desc(RCAReportORM.generated_at)).limit(limit)
            )
        ).scalars().all()
    return [
        {
            "report_id": str(r.report_id),
            "incident_id": str(r.incident_id),
            "machine_id": r.machine_id,
            "generated_at": r.generated_at.isoformat(),
            "summary": r.summary,
            "findings": r.findings,
            "recommended_actions": r.recommended_actions,
            "confidence": r.confidence,
            "similar_incidents": r.similar_incidents,
            "model_used": r.model_used,
            "tokens_used": r.tokens_used,
            "cost_usd": r.cost_usd,
            "activity_id": r.activity_id,
        }
        for r in rows
    ]


@app.get("/api/v1/rca/reports/{report_id}")
async def get_report(report_id: str) -> dict:
    async with session_scope() as session:
        r = await session.get(RCAReportORM, uuid.UUID(report_id))
    if r is None:
        raise HTTPException(404, "RCA report not found")
    return {
        "report_id": str(r.report_id),
        "incident_id": str(r.incident_id),
        "machine_id": r.machine_id,
        "generated_at": r.generated_at.isoformat(),
        "summary": r.summary,
        "findings": r.findings,
        "recommended_actions": r.recommended_actions,
        "confidence": r.confidence,
        "similar_incidents": r.similar_incidents,
        "model_used": r.model_used,
        "tokens_used": r.tokens_used,
        "cost_usd": r.cost_usd,
        "activity_id": r.activity_id,
    }


@app.get("/api/v1/agents/activity")
async def agent_activity(limit: int = 100, agent_name: str | None = None) -> list[dict]:
    return ledger.snapshot(agent=agent_name, limit=limit)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
