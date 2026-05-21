"""Cover the real NATS messaging helpers by stubbing the NATS client."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest


def _reload_messaging():
    # Drop any cached `messaging` module so we can re-import with the
    # patched `nats` symbol.
    if "forgemind_common.messaging" in sys.modules:
        del sys.modules["forgemind_common.messaging"]
    import forgemind_common.messaging as m  # noqa: E402

    return m


@pytest.fixture(autouse=True)
def _restore_broker_patches():
    """After each test in this file, re-install the in-memory broker
    patches so other tests in the suite keep working."""
    yield
    # Re-do what conftest does at module-import time.
    if "forgemind_common.messaging" in sys.modules:
        del sys.modules["forgemind_common.messaging"]
    import forgemind_common.messaging as fm
    from .conftest import _broker_publish, _broker_subscribe

    fm.publish = _broker_publish
    fm.subscribe = _broker_subscribe


@pytest.mark.asyncio
async def test_publish_subscribe_real_path(monkeypatch):
    """Exercise the actual publish() / subscribe() code paths with a fake
    NATS client. The e2e conftest replaces them with an in-mem broker, so
    we reload the module here to get the original implementation."""
    m = _reload_messaging()

    fake_msg = MagicMock()
    fake_msg.data = json.dumps({"hello": "world"}).encode()

    captured: list[dict] = []

    async def handler(payload):
        captured.append(payload)

    fake_client = MagicMock()
    fake_client.is_connected = True
    fake_client.publish = AsyncMock()

    async def fake_subscribe(subject, queue=None, cb=None):
        # Simulate a message arrival.
        await cb(fake_msg)

    fake_client.subscribe = fake_subscribe

    async def fake_connect(*args, **kwargs):
        return fake_client

    monkeypatch.setattr(m.nats, "connect", fake_connect)
    m._client = None

    await m.publish("topic", {"v": 1})
    fake_client.publish.assert_called_once()

    await m.subscribe("topic", handler, queue="q")
    assert captured == [{"hello": "world"}]


@pytest.mark.asyncio
async def test_subscribe_handler_bad_payload(monkeypatch, caplog):
    m = _reload_messaging()
    fake_client = MagicMock()
    fake_client.is_connected = True
    fake_msg = MagicMock()
    fake_msg.data = b"this is not json"

    async def fake_subscribe(subject, queue=None, cb=None):
        await cb(fake_msg)

    fake_client.subscribe = fake_subscribe

    async def fake_connect(*a, **k):
        return fake_client

    monkeypatch.setattr(m.nats, "connect", fake_connect)
    m._client = None

    async def handler(payload):
        raise AssertionError("should not be called")

    await m.subscribe("topic", handler)


@pytest.mark.asyncio
async def test_iter_messages(monkeypatch):
    m = _reload_messaging()
    fake_client = MagicMock()
    fake_client.is_connected = True

    class _Sub:
        async def messages_gen(self):
            class _Msg:
                def __init__(self, body):
                    self.data = body

            yield _Msg(json.dumps({"a": 1}).encode())
            yield _Msg(b"not-json")
            yield _Msg(json.dumps({"a": 2}).encode())

        @property
        def messages(self):
            return self.messages_gen()

        async def unsubscribe(self):
            self.unsubscribed = True

    sub = _Sub()

    async def fake_subscribe(subject, queue=None):
        return sub

    fake_client.subscribe = fake_subscribe

    async def fake_connect(*a, **k):
        return fake_client

    monkeypatch.setattr(m.nats, "connect", fake_connect)
    m._client = None

    received = []
    async for payload in m.iter_messages("topic"):
        received.append(payload)
    assert received == [{"a": 1}, {"a": 2}]


@pytest.mark.asyncio
async def test_subscribe_sync_handler(monkeypatch):
    """Handler may be a sync function — covers the non-coroutine branch."""
    m = _reload_messaging()
    fake_client = MagicMock()
    fake_client.is_connected = True

    fake_msg = MagicMock()
    fake_msg.data = json.dumps({"k": "v"}).encode()

    async def fake_subscribe(subject, queue=None, cb=None):
        await cb(fake_msg)

    fake_client.subscribe = fake_subscribe

    async def fake_connect(*a, **k):
        return fake_client

    monkeypatch.setattr(m.nats, "connect", fake_connect)
    m._client = None

    received: list[dict] = []

    def sync_handler(payload):
        received.append(payload)

    await m.subscribe("topic", sync_handler)
    assert received == [{"k": "v"}]
