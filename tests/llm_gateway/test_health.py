"""Tests for provider health monitoring."""

import pytest
from unittest.mock import patch, AsyncMock, Mock
import httpx


def test_provider_health_all_healthy(client, sample_provider_data):
    """Test health check when all providers are healthy."""
    # Create provider
    provider_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = provider_response.json()["id"]
    
    # Mock successful health probe
    with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
        response_mock = Mock()
        response_mock.status_code = 200
        response_mock.elapsed.total_seconds = Mock(return_value=0.28)
        mock_get.return_value = response_mock
        
        response = client.get("/api/v1/admin/llm/health")
        assert response.status_code == 200
        
        data = response.json()
        assert "providers" in data
        assert len(data["providers"]) >= 1
        
        # Find our provider
        provider = next((p for p in data["providers"] if p["provider_id"] == provider_id), None)
        assert provider is not None
        assert provider["status"] == "healthy"
        assert provider["latency_ms"] > 0


def test_provider_health_degraded(client, sample_provider_data):
    """Test health check when provider is degraded (high latency)."""
    # Create provider
    provider_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = provider_response.json()["id"]
    
    # Mock slow response (degraded)
    with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
        response_mock = Mock()
        response_mock.status_code = 200
        response_mock.elapsed.total_seconds = Mock(return_value=5.0)  # 5 seconds
        mock_get.return_value = response_mock
        
        response = client.get("/api/v1/admin/llm/health")
        assert response.status_code == 200
        
        data = response.json()
        provider = next((p for p in data["providers"] if p["provider_id"] == provider_id), None)
        assert provider is not None
        assert provider["status"] == "degraded"
        assert provider["latency_ms"] > 1000


def test_provider_health_unhealthy(client, sample_provider_data):
    """Test health check when provider is unreachable."""
    # Create provider
    provider_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = provider_response.json()["id"]
    
    # Mock connection error
    with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.RequestError("Connection refused")
        
        response = client.get("/api/v1/admin/llm/health")
        assert response.status_code == 200
        
        data = response.json()
        provider = next((p for p in data["providers"] if p["provider_id"] == provider_id), None)
        assert provider is not None
        assert provider["status"] == "unhealthy"


def test_usage_analytics(client, sample_provider_data, sample_model_data):
    """Test usage analytics endpoint."""
    # Create provider and model
    provider_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = provider_response.json()["id"]
    
    model_data = {**sample_model_data, "provider_id": provider_id}
    model_response = client.post("/api/v1/admin/llm/models", json=model_data)
    model_id = model_response.json()["id"]
    
    # Set routing
    client.put("/api/v1/admin/llm/agents/analytics-test-agent/routing", json={"primary_model_id": model_id})
    
    mock_response = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-4o",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "Test"},
            "finish_reason": "stop"
        }],
        "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300}
    }
    
    with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_response
        
        # Make multiple requests
        for _ in range(3):
            chat_request = {"messages": [{"role": "user", "content": "Test"}]}
            client.post(
                "/v1/chat/completions",
                json=chat_request,
                headers={"X-Agent": "analytics-test-agent"}
            )
    
    # Check usage analytics
    usage_response = client.get("/api/v1/admin/llm/usage?agent=analytics-test-agent&window=1h")
    assert usage_response.status_code == 200
    
    usage_data = usage_response.json()
    assert "usage" in usage_data
    assert len(usage_data["usage"]) > 0
    
    # Find analytics for our agent
    agent_usage = next((u for u in usage_data["usage"] if u["agent"] == "analytics-test-agent"), None)
    assert agent_usage is not None
    assert agent_usage["requests"] >= 3
    assert agent_usage["input_tokens"] >= 300  # 3 * 100
    assert agent_usage["output_tokens"] >= 600  # 3 * 200
