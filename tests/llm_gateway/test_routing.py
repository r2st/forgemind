"""Tests for agent routing configuration."""

import pytest


def test_get_agent_routing_default(client):
    """Test getting routing config for an agent without custom config."""
    response = client.get("/api/v1/admin/llm/agents/rca-agent/routing")
    assert response.status_code == 200
    
    data = response.json()
    assert "routing_strategy" in data
    assert "temperature" in data


def test_update_agent_routing(client, sample_provider_data, sample_model_data, sample_routing_config):
    """Test updating agent routing configuration."""
    # Create provider and model
    provider_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = provider_response.json()["id"]
    
    model_data = {**sample_model_data, "provider_id": provider_id}
    model_response = client.post("/api/v1/admin/llm/models", json=model_data)
    model_id = model_response.json()["id"]
    
    # Update routing config
    routing_data = {**sample_routing_config, "primary_model_id": model_id}
    response = client.put("/api/v1/admin/llm/agents/rca-agent/routing", json=routing_data)
    assert response.status_code == 200
    
    data = response.json()
    assert data["primary_model_id"] == model_id
    assert data["routing_strategy"] == sample_routing_config["routing_strategy"]
    assert data["temperature"] == sample_routing_config["temperature"]


def test_routing_strategy_validation(client, sample_provider_data, sample_model_data):
    """Test that only valid routing strategies are accepted."""
    # Create provider and model
    provider_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = provider_response.json()["id"]
    
    model_data = {**sample_model_data, "provider_id": provider_id}
    model_response = client.post("/api/v1/admin/llm/models", json=model_data)
    model_id = model_response.json()["id"]
    
    # Valid strategies
    valid_strategies = [
        "cheapest",
        "lowest_latency",
        "highest_quality",
        "local_only",
        "gpu_aware",
        "compliance_aware"
    ]
    
    for strategy in valid_strategies:
        routing_data = {
            "primary_model_id": model_id,
            "routing_strategy": strategy
        }
        response = client.put("/api/v1/admin/llm/agents/rca-agent/routing", json=routing_data)
        assert response.status_code == 200
        assert response.json()["routing_strategy"] == strategy
    
    # Invalid strategy
    invalid_routing_data = {
        "primary_model_id": model_id,
        "routing_strategy": "invalid_strategy"
    }
    response = client.put("/api/v1/admin/llm/agents/rca-agent/routing", json=invalid_routing_data)
    assert response.status_code == 422  # Validation error


def test_per_agent_override(client, sample_provider_data, sample_model_data):
    """Test that per-agent routing config overrides defaults."""
    # Create provider and model
    provider_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = provider_response.json()["id"]
    
    model_data = {**sample_model_data, "provider_id": provider_id}
    model_response = client.post("/api/v1/admin/llm/models", json=model_data)
    model_id = model_response.json()["id"]
    
    # Set routing for RCA agent
    rca_routing = {
        "primary_model_id": model_id,
        "routing_strategy": "highest_quality",
        "temperature": 0.7
    }
    client.put("/api/v1/admin/llm/agents/rca-agent/routing", json=rca_routing)
    
    # Set different routing for ChatOps agent
    chatops_routing = {
        "primary_model_id": model_id,
        "routing_strategy": "cheapest",
        "temperature": 0.3
    }
    client.put("/api/v1/admin/llm/agents/chatops-agent/routing", json=chatops_routing)
    
    # Verify both agents have different configs
    rca_response = client.get("/api/v1/admin/llm/agents/rca-agent/routing")
    chatops_response = client.get("/api/v1/admin/llm/agents/chatops-agent/routing")
    
    assert rca_response.json()["routing_strategy"] == "highest_quality"
    assert rca_response.json()["temperature"] == 0.7
    
    assert chatops_response.json()["routing_strategy"] == "cheapest"
    assert chatops_response.json()["temperature"] == 0.3
