"""Notification Service.

Listens to the incidents stream and fans out alerts. Currently logs and
keeps a ring buffer (the dashboard polls /api/v1/notifications/recent).
Real deployments plug in Slack, PagerDuty, MS Teams here.

Includes adaptive suppression: if a (machine, severity) pair fires more
than N times in a window, downgrade subsequent alerts in that window so
the operator isn't drowned.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from forgemind_common import get_logger, get_settings, setup_logging
from forgemind_common.messaging import subscribe
from forgemind_common.observability import install_metrics

setup_logging("notification-service")
log = get_logger(__name__)
settings = get_settings()


_NOTIFS: deque[dict] = deque(maxlen=500)
_FLOOD: dict[tuple[str, str], deque[float]] = defaultdict(lambda: deque(maxlen=20))
_FLOOD_WINDOW = 300.0   # 5 min
_FLOOD_LIMIT = 5


def _suppressed(machine: str, severity: str) -> bool:
    now = time.time()
    bucket = _FLOOD[(machine, severity)]
    while bucket and now - bucket[0] > _FLOOD_WINDOW:
        bucket.popleft()
    bucket.append(now)
    return len(bucket) > _FLOOD_LIMIT


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(_run())
    log.info("notification.started")
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="ForgeMind Notification Service", version="0.1.0", lifespan=lifespan)
install_metrics(app, "notification-service")


async def _run() -> None:
    async def handler(payload: dict) -> None:
        machine = payload.get("machine_id", "?")
        sev = payload.get("severity", "INFO")
        if _suppressed(machine, sev):
            log.info("notification.suppressed", machine=machine, sev=sev)
            return
        item = {
            "title": payload.get("title", "Incident"),
            "machine_id": machine,
            "severity": sev,
            "detected_at": payload.get("detected_at"),
            "channels": ["webhook", "ui"],
        }
        _NOTIFS.appendleft(item)
        log.info("notification.fired", **item)

    await subscribe(settings.incidents_subject, handler, queue="notification-service")
    while True:
        await asyncio.sleep(3600)


@app.get("/api/v1/notifications/recent")
async def recent(limit: int = 50) -> list[dict]:
    return list(_NOTIFS)[:limit]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
