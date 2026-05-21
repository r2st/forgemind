"""Reporting Service.

Wraps the Reporting Hermes Agent and persists generated reports to
Postgres so executives can read shift summaries from the dashboard.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import JSON, DateTime, String, Text, desc, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from forgemind_common import get_logger, get_settings, setup_logging
from forgemind_common.db import get_engine, session_scope
from forgemind_common.observability import install_metrics

setup_logging("reporting-service")
log = get_logger(__name__)
settings = get_settings()


class Base(DeclarativeBase):
    pass


class ReportORM(Base):
    __tablename__ = "ops_reports"

    report_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(32))  # shift|daily|executive
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    eng = get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("reporting.started")
    yield


app = FastAPI(title="ForgeMind Reporting Service", version="0.1.0", lifespan=lifespan)
install_metrics(app, "reporting-service")


class GenerateRequest(BaseModel):
    kind: str = "shift"
    title: str | None = None


@app.post("/api/v1/reports/generate")
async def generate(req: GenerateRequest) -> dict:
    task = f"Generate a {req.kind} operations report for the plant. Use list_recent_incidents and list_recent_rca. Plain English."
    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(
            f"{settings.orchestrator_url}/api/v1/agents/run", json={"task": task}
        )
        r.raise_for_status()
    payload = r.json()
    body = payload.get("result") or ""
    title = req.title or f"{req.kind.title()} Report — {datetime.utcnow().isoformat(timespec='minutes')}Z"
    async with session_scope() as session:
        rec = ReportORM(kind=req.kind, title=title, body=body, meta={
            "activity_id": payload.get("activity_id"),
            "model_used": payload.get("model_used"),
            "cost_usd": payload.get("cost_usd"),
        })
        session.add(rec)
        await session.flush()
        rid = rec.report_id
    return {"report_id": str(rid), "title": title, "body": body}


@app.get("/api/v1/reports")
async def list_reports(limit: int = 25) -> list[dict]:
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(ReportORM).order_by(desc(ReportORM.generated_at)).limit(limit)
            )
        ).scalars().all()
    return [
        {
            "report_id": str(r.report_id),
            "kind": r.kind,
            "title": r.title,
            "body": r.body,
            "generated_at": r.generated_at.isoformat(),
            "meta": r.meta,
        }
        for r in rows
    ]


@app.get("/api/v1/reports/{report_id}")
async def get_report(report_id: str) -> dict:
    async with session_scope() as session:
        r = await session.get(ReportORM, uuid.UUID(report_id))
    if r is None:
        raise HTTPException(404, "report not found")
    return {
        "report_id": str(r.report_id),
        "kind": r.kind,
        "title": r.title,
        "body": r.body,
        "generated_at": r.generated_at.isoformat(),
        "meta": r.meta,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
