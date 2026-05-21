"""E2E tests for the predictive-maintenance service."""

from __future__ import annotations


def test_predictions_list(pdm_client, simulator_client, anomaly_client):
    # simulator_client + anomaly_client are passed so their apps are
    # mounted on the routing transport before pdm calls them.
    r = pdm_client.get("/api/v1/predictions")
    assert r.status_code == 200, r.text
    preds = r.json()
    assert isinstance(preds, list)
    assert len(preds) > 0
    sample = preds[0]
    assert "machine_id" in sample
    assert "risk_72h" in sample
    assert 0.0 <= sample["risk_72h"] <= 1.0
    assert "recommended_window_start" in sample
    # sorted descending by risk_72h.
    risks = [p["risk_72h"] for p in preds]
    assert risks == sorted(risks, reverse=True)


def test_prediction_for_machine(pdm_client, simulator_client, anomaly_client):
    r = pdm_client.get("/api/v1/predictions/CNC-101")
    assert r.status_code == 200
    assert r.json()["machine_id"] == "CNC-101"


def test_prediction_for_unknown_machine(pdm_client, simulator_client, anomaly_client):
    r = pdm_client.get("/api/v1/predictions/BOGUS-999")
    assert r.status_code == 404


def test_pdm_explain(pdm_client, simulator_client, anomaly_client, orchestrator_client):
    r = pdm_client.post("/api/v1/predictions/explain/CNC-101")
    assert r.status_code == 200
    body = r.json()
    assert "result" in body or "agent_name" in body
