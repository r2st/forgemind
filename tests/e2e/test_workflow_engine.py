"""E2E tests for the workflow-engine (LangGraph) service."""

from __future__ import annotations

import uuid


def test_list_workflows(workflow_client):
    r = workflow_client.get("/api/v1/workflows")
    assert r.status_code == 200
    workflows = r.json()
    names = {w["name"] for w in workflows}
    assert {"investigation", "maintenance_approval", "remediation", "escalation"}.issubset(names)


def test_unknown_workflow_404(workflow_client):
    r = workflow_client.post(
        "/api/v1/workflows/bogus/run", json={"incident_id": str(uuid.uuid4())}
    )
    assert r.status_code == 404


def test_run_investigation_workflow(workflow_client):
    # No incident exists upstream, but the graph should still run and
    # capture an error state per node — the response should never 500.
    r = workflow_client.post(
        "/api/v1/workflows/investigation/run",
        json={"incident_id": str(uuid.uuid4()), "approved": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["workflow"] == "investigation"
    assert body["status"] in ("completed", "error", "blocked_on_approval")
    assert "state" in body
    assert "trace" in body["state"]


def test_list_runs(workflow_client):
    workflow_client.post(
        "/api/v1/workflows/investigation/run",
        json={"incident_id": str(uuid.uuid4()), "approved": True},
    )
    r = workflow_client.get("/api/v1/workflows/runs")
    assert r.status_code == 200
    runs = r.json()
    assert any(r2["workflow"] == "investigation" for r2 in runs)


def test_get_run_by_id(workflow_client):
    rid = workflow_client.post(
        "/api/v1/workflows/investigation/run",
        json={"incident_id": str(uuid.uuid4()), "approved": True},
    ).json()["run_id"]
    r = workflow_client.get(f"/api/v1/workflows/runs/{rid}")
    assert r.status_code == 200
    assert r.json()["run_id"] == rid


def test_get_run_not_found(workflow_client):
    r = workflow_client.get(f"/api/v1/workflows/runs/{uuid.uuid4()}")
    assert r.status_code == 404


def test_run_remediation_workflow(workflow_client):
    r = workflow_client.post(
        "/api/v1/workflows/remediation/run",
        json={"incident_id": str(uuid.uuid4()), "approved": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["workflow"] == "remediation"


def test_run_escalation_workflow(workflow_client):
    r = workflow_client.post(
        "/api/v1/workflows/escalation/run",
        json={"machine_id": "CNC-101"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["workflow"] == "escalation"
