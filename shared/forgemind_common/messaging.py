"""Async NATS publish/subscribe helpers used by streaming services."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

import nats
from nats.aio.client import Client as NATSClient
from nats.aio.msg import Msg

from .config import get_settings

logger = logging.getLogger(__name__)

_client: NATSClient | None = None
_lock = asyncio.Lock()


async def get_nats() -> NATSClient:
    global _client
    async with _lock:
        if _client is None or not _client.is_connected:
            s = get_settings()
            _client = await nats.connect(s.nats_url, reconnect_time_wait=2)
            logger.info("Connected to NATS at %s", s.nats_url)
        return _client


async def publish(subject: str, payload: dict[str, Any]) -> None:
    nc = await get_nats()
    await nc.publish(subject, json.dumps(payload, default=str).encode())


async def subscribe(
    subject: str,
    handler: Callable[[dict[str, Any]], Any],
    queue: str | None = None,
) -> None:
    nc = await get_nats()

    async def _wrap(msg: Msg) -> None:
        try:
            payload = json.loads(msg.data.decode())
            result = handler(payload)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:  # noqa: BLE001
            logger.exception("subscribe.handler_error subject=%s err=%s", subject, exc)

    await nc.subscribe(subject, queue=queue, cb=_wrap)


async def iter_messages(subject: str, queue: str | None = None) -> AsyncIterator[dict[str, Any]]:
    """Async iterator form for services that prefer a pull model."""
    nc = await get_nats()
    sub = await nc.subscribe(subject, queue=queue)
    try:
        async for msg in sub.messages:
            try:
                yield json.loads(msg.data.decode())
            except json.JSONDecodeError:
                continue
    finally:
        await sub.unsubscribe()
