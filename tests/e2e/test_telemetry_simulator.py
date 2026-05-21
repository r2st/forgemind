"""E2E tests for the telemetry-simulator service."""

from __future__ import annotations


def test_list_machines(simulator_client):
    r = simulator_client.get("/api/v1/machines")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 5
    sample = data[0]
    assert set(sample) >= {"machine_id", "machine_type", "line_id", "plant_id", "state"}


def test_snapshot(simulator_client):
    r = simulator_client.get("/api/v1/snapshot")
    assert r.status_code == 200
    snap = r.json()
    assert len(snap) > 0
    for row in snap:
        assert "temperature_c" in row
        assert "vibration_mm_s" in row
        assert "machine_id" in row


def test_inject_anomaly(simulator_client):
    r = simulator_client.post(
        "/api/v1/inject",
        json={"machine_id": "CNC-101", "kind": "vibration_spike", "duration_ticks": 30},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["machine_id"] == "CNC-101"
    assert body["kind"] == "vibration_spike"


def test_inject_unknown_machine(simulator_client):
    r = simulator_client.post(
        "/api/v1/inject",
        json={"machine_id": "BOGUS-999", "kind": "vibration_spike", "duration_ticks": 30},
    )
    assert r.status_code == 404


def test_inject_invalid_kind(simulator_client):
    r = simulator_client.post(
        "/api/v1/inject",
        json={"machine_id": "CNC-101", "kind": "bogus_kind", "duration_ticks": 30},
    )
    assert r.status_code == 422


def test_replay_historical(simulator_client):
    r = simulator_client.post("/api/v1/replay-historical")
    assert r.status_code == 200
    body = r.json()
    kinds = {entry["kind"] for entry in body["injected"]}
    assert "vibration_spike" in kinds
    assert "thermal_runaway" in kinds
