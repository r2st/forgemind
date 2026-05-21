"""Smoke test — ensures conftest wires every service app correctly."""

from __future__ import annotations


def test_service_apps_load(service_apps):
    expected = {
        "llm-gateway",
        "telemetry-simulator",
        "telemetry-ingestion",
        "anomaly-detection",
        "rca-service",
        "predictive-maintenance",
        "ai-orchestrator",
        "workflow-engine",
        "chatops-service",
        "reporting-service",
        "notification-service",
        "api-gateway",
    }
    assert set(service_apps.keys()) == expected
