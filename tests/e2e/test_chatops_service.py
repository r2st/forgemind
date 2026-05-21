"""E2E tests for the chatops-service."""

from __future__ import annotations


def test_chat_creates_session(chatops_client):
    r = chatops_client.post(
        "/api/v1/chat", json={"message": "How many open incidents on CNC-101?"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"]
    assert body["response"]


def test_chat_session_history(chatops_client):
    sid = chatops_client.post(
        "/api/v1/chat", json={"message": "Hello?", "session_id": "sess-1"}
    ).json()["session_id"]
    r = chatops_client.get(f"/api/v1/chat/sessions/{sid}")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == sid
    assert isinstance(body["messages"], list)


def test_chat_stream_returns_sse(chatops_client):
    with chatops_client.stream(
        "POST",
        "/api/v1/chat/stream",
        json={"message": "Quick status update?"},
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        body = "".join(part for part in resp.iter_text())
    assert "event: done" in body
    assert "event: start" in body
