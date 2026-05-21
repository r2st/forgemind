"""E2E tests for the RCA service."""

from __future__ import annotations

import uuid


def test_run_rca_creates_report(rca_client, mock_gateway):
    incident_id = str(uuid.uuid4())
    r = rca_client.post("/api/v1/rca/run", json={"incident_id": incident_id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["incident_id"] == incident_id
    assert body["summary"]
    assert isinstance(body["findings"], list)
    assert isinstance(body["recommended_actions"], list)
    assert 0.0 <= body["confidence"] <= 1.0
    assert body["report_id"]


def test_list_rca_reports(rca_client):
    # generate one to ensure non-empty.
    rca_client.post("/api/v1/rca/run", json={"incident_id": str(uuid.uuid4())})
    r = rca_client.get("/api/v1/rca/reports")
    assert r.status_code == 200
    reports = r.json()
    assert isinstance(reports, list)
    assert len(reports) >= 1


def test_get_rca_report_by_id(rca_client):
    rid = rca_client.post(
        "/api/v1/rca/run", json={"incident_id": str(uuid.uuid4())}
    ).json()["report_id"]
    r = rca_client.get(f"/api/v1/rca/reports/{rid}")
    assert r.status_code == 200
    assert r.json()["report_id"] == rid


def test_get_rca_report_not_found(rca_client):
    r = rca_client.get(f"/api/v1/rca/reports/{uuid.uuid4()}")
    assert r.status_code == 404


def test_rca_agent_activity(rca_client):
    rca_client.post("/api/v1/rca/run", json={"incident_id": str(uuid.uuid4())})
    r = rca_client.get("/api/v1/agents/activity")
    assert r.status_code == 200
    activity = r.json()
    assert isinstance(activity, list)
    assert any(a.get("agent_name") == "rca-agent" for a in activity)
