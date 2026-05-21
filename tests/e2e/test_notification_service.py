"""E2E tests for the notification-service."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone


def test_recent_notifications_empty(notification_client):
    r = notification_client.get("/api/v1/notifications/recent")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_notification_consumes_incident(notification_client):
    """Publishing to the incidents subject should put a row in recent."""
    from .conftest import BROKER

    incident = {
        "machine_id": "CNC-101",
        "severity": "CRITICAL",
        "title": "test critical incident",
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }
    asyncio.get_event_loop().run_until_complete(BROKER.publish("forgemind.incidents", incident))
    r = notification_client.get("/api/v1/notifications/recent")
    assert r.status_code == 200
    items = r.json()
    assert any(it["machine_id"] == "CNC-101" and it["severity"] == "CRITICAL" for it in items)


def test_notification_flood_suppression(notification_client):
    from .conftest import BROKER

    loop = asyncio.get_event_loop()
    for _ in range(20):
        loop.run_until_complete(
            BROKER.publish(
                "forgemind.incidents",
                {
                    "machine_id": "FLOOD-1",
                    "severity": "HIGH",
                    "title": "noisy",
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        )
    r = notification_client.get("/api/v1/notifications/recent")
    # FLOOD_LIMIT = 5 → at most 6 should land before suppression kicks in.
    matched = [it for it in r.json() if it["machine_id"] == "FLOOD-1"]
    assert 0 < len(matched) <= 6
