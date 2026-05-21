"""Tests for provider CRUD operations."""

import pytest


def test_create_provider(client, sample_provider_data):
    """Test creating a new provider."""
    response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    assert response.status_code == 200
    
    data = response.json()
    assert data["name"] == sample_provider_data["name"]
    assert data["provider_type"] == sample_provider_data["provider_type"]
    assert data["base_url"] == sample_provider_data["base_url"]
    assert data["enabled"] is True
    assert "id" in data
    # API key should be encrypted, not returned in plain text
    assert data.get("api_key") != sample_provider_data["api_key"]


def test_list_providers(client, sample_provider_data):
    """Test listing providers."""
    # Create a provider first
    client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    
    response = client.get("/api/v1/admin/llm/providers")
    assert response.status_code == 200
    
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["name"] == sample_provider_data["name"]


def test_get_provider(client, sample_provider_data):
    """Test getting a specific provider."""
    # Create provider
    create_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = create_response.json()["id"]
    
    # Get provider
    response = client.get(f"/api/v1/admin/llm/providers/{provider_id}")
    assert response.status_code == 200
    
    data = response.json()
    assert data["id"] == provider_id
    assert data["name"] == sample_provider_data["name"]


def test_update_provider(client, sample_provider_data):
    """Test updating a provider."""
    # Create provider
    create_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = create_response.json()["id"]
    
    # Update provider
    update_data = {"name": "Updated Provider", "enabled": False}
    response = client.put(f"/api/v1/admin/llm/providers/{provider_id}", json=update_data)
    assert response.status_code == 200
    
    data = response.json()
    assert data["name"] == "Updated Provider"
    assert data["enabled"] is False


def test_delete_provider(client, sample_provider_data):
    """Test deleting a provider."""
    # Create provider
    create_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = create_response.json()["id"]
    
    # Delete provider
    response = client.delete(f"/api/v1/admin/llm/providers/{provider_id}")
    assert response.status_code == 200
    
    # Verify deletion
    get_response = client.get(f"/api/v1/admin/llm/providers/{provider_id}")
    assert get_response.status_code == 404


def test_create_provider_encryption(client, sample_provider_data):
    """Test that API keys are encrypted at rest."""
    response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    assert response.status_code == 200
    
    # The returned API key should NOT be the plain text key
    data = response.json()
    assert "api_key" not in data or data["api_key"] != sample_provider_data["api_key"]
    
    # Retrieve the provider and verify key is still not exposed
    provider_id = data["id"]
    get_response = client.get(f"/api/v1/admin/llm/providers/{provider_id}")
    get_data = get_response.json()
    assert "api_key" not in get_data or get_data["api_key"] != sample_provider_data["api_key"]


def test_create_provider_validation(client):
    """Test provider validation."""
    invalid_data = {
        "name": "Test",
        "kind": "invalid_kind",  # Invalid enum value
        "provider_type": "openai"
    }
    
    response = client.post("/api/v1/admin/llm/providers", json=invalid_data)
    assert response.status_code == 422  # Validation error
