"""Tests for model CRUD operations."""

import pytest


def test_create_model(client, sample_provider_data, sample_model_data):
    """Test creating a new model."""
    # First create a provider
    provider_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = provider_response.json()["id"]
    
    # Create model
    model_data = {**sample_model_data, "provider_id": provider_id}
    response = client.post("/api/v1/admin/llm/models", json=model_data)
    assert response.status_code == 200
    
    data = response.json()
    assert data["model_name"] == sample_model_data["model_name"]
    assert data["display_name"] == sample_model_data["display_name"]
    assert data["provider_id"] == provider_id
    assert data["enabled"] is True
    assert "id" in data


def test_list_models(client, sample_provider_data, sample_model_data):
    """Test listing models."""
    # Create provider and model
    provider_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = provider_response.json()["id"]
    
    model_data = {**sample_model_data, "provider_id": provider_id}
    client.post("/api/v1/admin/llm/models", json=model_data)
    
    # List models
    response = client.get("/api/v1/admin/llm/models")
    assert response.status_code == 200
    
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["model_name"] == sample_model_data["model_name"]


def test_get_model(client, sample_provider_data, sample_model_data):
    """Test getting a specific model."""
    # Create provider and model
    provider_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = provider_response.json()["id"]
    
    model_data = {**sample_model_data, "provider_id": provider_id}
    create_response = client.post("/api/v1/admin/llm/models", json=model_data)
    model_id = create_response.json()["id"]
    
    # Get model
    response = client.get(f"/api/v1/admin/llm/models/{model_id}")
    assert response.status_code == 200
    
    data = response.json()
    assert data["id"] == model_id
    assert data["model_name"] == sample_model_data["model_name"]


def test_update_model(client, sample_provider_data, sample_model_data):
    """Test updating a model."""
    # Create provider and model
    provider_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = provider_response.json()["id"]
    
    model_data = {**sample_model_data, "provider_id": provider_id}
    create_response = client.post("/api/v1/admin/llm/models", json=model_data)
    model_id = create_response.json()["id"]
    
    # Update model
    update_data = {"enabled": False, "cost_per_input_token": 0.00001}
    response = client.put(f"/api/v1/admin/llm/models/{model_id}", json=update_data)
    assert response.status_code == 200
    
    data = response.json()
    assert data["enabled"] is False
    assert data["cost_per_input_token"] == 0.00001


def test_delete_model(client, sample_provider_data, sample_model_data):
    """Test deleting a model."""
    # Create provider and model
    provider_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = provider_response.json()["id"]
    
    model_data = {**sample_model_data, "provider_id": provider_id}
    create_response = client.post("/api/v1/admin/llm/models", json=model_data)
    model_id = create_response.json()["id"]
    
    # Delete model
    response = client.delete(f"/api/v1/admin/llm/models/{model_id}")
    assert response.status_code == 200
    
    # Verify deletion
    get_response = client.get(f"/api/v1/admin/llm/models/{model_id}")
    assert get_response.status_code == 404


def test_create_model_with_invalid_provider(client, sample_model_data):
    """Test creating a model with invalid provider ID."""
    model_data = {**sample_model_data, "provider_id": "invalid-provider-id"}
    response = client.post("/api/v1/admin/llm/models", json=model_data)
    assert response.status_code in [404, 422]  # Provider not found or validation error
