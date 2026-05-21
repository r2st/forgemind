"""E2E tests for the reporting-service."""

from __future__ import annotations

import uuid


def test_generate_report(reporting_client):
    r = reporting_client.post(
        "/api/v1/reports/generate", json={"kind": "shift"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["report_id"]
    assert body["title"]
    assert body["body"]


def test_list_reports(reporting_client):
    reporting_client.post("/api/v1/reports/generate", json={"kind": "shift"})
    r = reporting_client.get("/api/v1/reports")
    assert r.status_code == 200
    reports = r.json()
    assert len(reports) >= 1


def test_get_report_by_id(reporting_client):
    rid = reporting_client.post(
        "/api/v1/reports/generate",
        json={"kind": "executive", "title": "Custom title"},
    ).json()["report_id"]
    r = reporting_client.get(f"/api/v1/reports/{rid}")
    assert r.status_code == 200
    body = r.json()
    assert body["report_id"] == rid
    assert body["kind"] == "executive"
    assert body["title"] == "Custom title"


def test_get_report_not_found(reporting_client):
    r = reporting_client.get(f"/api/v1/reports/{uuid.uuid4()}")
    assert r.status_code == 404
