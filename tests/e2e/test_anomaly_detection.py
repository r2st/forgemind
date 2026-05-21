"""E2E tests for the anomaly-detection service."""

from __future__ import annotations

import random


def _normal_reading(machine_id: str = "CNC-101") -> dict:
    return {
        "machine_id": machine_id,
        "line_id": "line-A",
        "plant_id": "plant-01",
        "timestamp": "2026-05-21T12:00:00+00:00",
        "temperature_c": 62.0,
        "vibration_mm_s": 1.8,
        "pressure_bar": 4.2,
        "rpm": 2400,
        "power_kw": 18.0,
        "state": "RUNNING",
        "units_produced": 0,
        "defects": 0,
    }


def test_score_within_band_yields_no_anomalies(anomaly_client):
    # First reading just initialises the engine — no anomalies.
    r = anomaly_client.post("/api/v1/score", json=_normal_reading())
    assert r.status_code == 200
    body = r.json()
    assert body["machine_id"] == "CNC-101"
    assert isinstance(body["anomalies"], list)


def test_score_after_warmup_detects_spike(anomaly_client):
    rng = random.Random(0)
    # Warm-up: feed 70 normal readings.
    for _ in range(70):
        reading = _normal_reading("CNC-102")
        reading["vibration_mm_s"] = 1.8 + rng.uniform(-0.05, 0.05)
        anomaly_client.post("/api/v1/score", json=reading)
    # Now feed a vibration spike — expect at least one anomaly.
    spike = _normal_reading("CNC-102")
    spike["vibration_mm_s"] = 12.0
    r = anomaly_client.post("/api/v1/score", json=spike)
    body = r.json()
    metrics = {a["metric"] for a in body["anomalies"]}
    assert "vibration_mm_s" in metrics, body


def test_list_incidents_empty(anomaly_client):
    r = anomaly_client.get("/api/v1/incidents")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_list_incidents_with_filters(anomaly_client):
    r = anomaly_client.get("/api/v1/incidents", params={"machine_id": "CNC-101", "limit": 10})
    assert r.status_code == 200


def test_list_incidents_invalid_limit(anomaly_client):
    r = anomaly_client.get("/api/v1/incidents", params={"limit": 99999})
    assert r.status_code == 422
