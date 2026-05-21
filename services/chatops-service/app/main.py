"""ChatOps Service — REST + SSE streaming over the ChatOps Hermes Agent."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from forgemind_common import get_logger, setup_logging
from forgemind_common.observability import install_metrics

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from .agent import build_chatops_agent, build_chatops_agent_with_mcp

setup_logging("chatops-service")
log = get_logger(__name__)

# Built once at startup with MCP tools merged in. We assign a placeholder
# now and replace it in the lifespan handler.
agent = build_chatops_agent()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global agent
    try:
        agent = await build_chatops_agent_with_mcp()
        log.info("chatops.mcp_tools_loaded", count=len(agent.tools._tools))
    except Exception:  # noqa: BLE001
        log.exception("chatops.mcp_init_failed")
    yield


app = FastAPI(title="ForgeMind ChatOps Service", version="0.1.0", lifespan=lifespan)
install_metrics(app, "chatops-service")

# Naive in-memory session store; production would use Redis.
SESSIONS: dict[str, list[dict[str, Any]]] = {}


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    stream: bool = True


@app.post("/api/v1/chat")
async def chat(req: ChatRequest) -> dict:
    sid = req.session_id or str(uuid.uuid4())
    history = SESSIONS.get(sid, [])
    activity = await agent.run(req.message, history=history, task_id=sid)
    SESSIONS[sid] = activity.messages[-50:]
    return {
        "session_id": sid,
        "response": activity.result or "",
        "activity_id": activity.activity_id,
        "model_used": activity.model_used,
        "tokens": activity.tokens_in + activity.tokens_out,
        "cost_usd": activity.cost_usd,
        "tool_calls": activity.tool_calls,
    }


@app.post("/api/v1/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    """SSE stream. We can't easily stream tokens from Hermes, so we
    chunk the final response and emit tool calls as separate events."""
    sid = req.session_id or str(uuid.uuid4())
    history = SESSIONS.get(sid, [])

    async def event_gen():
        yield _sse("start", {"session_id": sid})
        activity = await agent.run(req.message, history=history, task_id=sid)
        SESSIONS[sid] = activity.messages[-50:]
        for tc in activity.tool_calls:
            yield _sse("tool", tc)
            await asyncio.sleep(0)
        result = activity.result or ""
        # Stream by sentence so the UI feels alive.
        for chunk in _chunk_text(result, max_chars=120):
            yield _sse("token", {"text": chunk})
            await asyncio.sleep(0.02)
        yield _sse(
            "done",
            {
                "activity_id": activity.activity_id,
                "model_used": activity.model_used,
                "tokens": activity.tokens_in + activity.tokens_out,
                "cost_usd": activity.cost_usd,
            },
        )

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.get("/api/v1/chat/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    return {
        "session_id": session_id,
        "messages": SESSIONS.get(session_id, []),
    }


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _chunk_text(text: str, max_chars: int = 120) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    buf: list[str] = []
    count = 0
    for word in text.split(" "):
        buf.append(word)
        count += len(word) + 1
        if count >= max_chars:
            chunks.append(" ".join(buf))
            buf = []
            count = 0
    if buf:
        chunks.append(" ".join(buf))
    return chunks


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
