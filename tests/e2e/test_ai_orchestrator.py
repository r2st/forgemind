"""E2E tests for the AI orchestrator (supervisor) service."""

from __future__ import annotations


def test_list_agents(orchestrator_client):
    r = orchestrator_client.get("/api/v1/agents")
    assert r.status_code == 200
    agents = r.json()
    names = {a["name"] for a in agents}
    assert {
        "supervisor",
        "rca-agent",
        "chatops-agent",
        "reporting-agent",
        "predictive-maintenance-agent",
    }.issubset(names)


def test_agent_activity_empty(orchestrator_client):
    r = orchestrator_client.get("/api/v1/agents/activity")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_run_supervisor_agent(orchestrator_client):
    r = orchestrator_client.post(
        "/api/v1/agents/run",
        json={"task": "Give me a quick plant status summary."},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["agent_name"] == "supervisor-agent"
    assert body["status"] in ("completed", "error")
    assert "result" in body


def test_run_supervisor_activity_recorded(orchestrator_client):
    orchestrator_client.post(
        "/api/v1/agents/run", json={"task": "What is the most recent incident?"}
    )
    r = orchestrator_client.get("/api/v1/agents/activity", params={"limit": 5})
    assert r.status_code == 200
    activity = r.json()
    assert len(activity) >= 1
