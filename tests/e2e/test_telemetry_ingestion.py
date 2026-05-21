"""E2E tests for the telemetry-ingestion service."""

from __future__ import annotations


def test_ingest_single(ingestion_client, sample_reading):
    r = ingestion_client.post("/api/v1/telemetry/single", json=sample_reading)
    assert r.status_code == 200, r.text
    assert r.json() == {"accepted": 1}


def test_ingest_batch(ingestion_client, sample_reading):
    batch = {"readings": [sample_reading, {**sample_reading, "machine_id": "CNC-102"}]}
    r = ingestion_client.post("/api/v1/telemetry/batch", json=batch)
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] == 2
    assert "elapsed_ms" in body


def test_ingest_empty_batch_rejected(ingestion_client):
    r = ingestion_client.post("/api/v1/telemetry/batch", json={"readings": []})
    assert r.status_code == 400


def test_ingest_invalid_payload(ingestion_client):
    r = ingestion_client.post("/api/v1/telemetry/single", json={"machine_id": "X"})
    assert r.status_code == 422


def test_ingest_health(ingestion_client, sample_reading):
    ingestion_client.post("/api/v1/telemetry/single", json=sample_reading)
    r = ingestion_client.get("/api/v1/telemetry/health")
    assert r.status_code == 200
    body = r.json()
    assert body["buffer_size"] >= 1
    assert "ingested_last_minute" in body
    assert "ingested_last_hour" in body


def test_publishes_to_broker(ingestion_client, sample_reading):
    from .conftest import BROKER

    BROKER.published.clear()
    ingestion_client.post("/api/v1/telemetry/single", json=sample_reading)
    assert any(subj == "forgemind.telemetry" for subj, _ in BROKER.published)
