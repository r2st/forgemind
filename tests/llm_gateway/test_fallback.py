"""Tests for fallback chain configuration and execution."""

import pytest
from unittest.mock import patch, AsyncMock, Mock
import httpx


def test_get_fallback_chain(client):
    """Test getting fallback chain for an agent."""
    response = client.get("/api/v1/admin/llm/agents/rca-agent/fallback")
    assert response.status_code == 200
    
    data = response.json()
    assert "fallback_model_ids" in data
    assert isinstance(data["fallback_model_ids"], list)


def test_update_fallback_chain(client, sample_provider_data, sample_model_data):
    """Test updating fallback chain."""
    # Create provider
    provider_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = provider_response.json()["id"]
    
    # Create multiple models
    model_ids = []
    for i in range(3):
        model_data = {
            **sample_model_data,
            "provider_id": provider_id,
            "model_name": f"gpt-4o-{i}",
            "display_name": f"GPT-4o Model {i}"
        }
        model_response = client.post("/api/v1/admin/llm/models", json=model_data)
        model_ids.append(model_response.json()["id"])
    
    # Set fallback chain
    fallback_data = {"fallback_model_ids": model_ids}
    response = client.put("/api/v1/admin/llm/agents/rca-agent/fallback", json=fallback_data)
    assert response.status_code == 200
    
    data = response.json()
    assert data["fallback_model_ids"] == model_ids


def test_fallback_chain_order_preserved(client, sample_provider_data, sample_model_data):
    """Test that fallback chain order is preserved."""
    # Create provider
    provider_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = provider_response.json()["id"]
    
    # Create models
    model_ids = []
    for i in range(3):
        model_data = {
            **sample_model_data,
            "provider_id": provider_id,
            "model_name": f"model-{i}"
        }
        model_response = client.post("/api/v1/admin/llm/models", json=model_data)
        model_ids.append(model_response.json()["id"])
    
    # Set fallback chain in specific order
    fallback_data = {"fallback_model_ids": [model_ids[2], model_ids[0], model_ids[1]]}
    client.put("/api/v1/admin/llm/agents/rca-agent/fallback", json=fallback_data)
    
    # Retrieve and verify order
    response = client.get("/api/v1/admin/llm/agents/rca-agent/fallback")
    data = response.json()
    assert data["fallback_model_ids"] == [model_ids[2], model_ids[0], model_ids[1]]


@pytest.mark.asyncio
async def test_fallback_execution_primary_success(client, sample_provider_data, sample_model_data):
    """Test fallback: primary model succeeds, no fallback needed."""
    # Create provider and model
    provider_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = provider_response.json()["id"]
    
    model_data = {**sample_model_data, "provider_id": provider_id}
    model_response = client.post("/api/v1/admin/llm/models", json=model_data)
    model_id = model_response.json()["id"]
    
    # Set routing
    routing_data = {"primary_model_id": model_id}
    client.put("/api/v1/admin/llm/agents/test-agent/routing", json=routing_data)
    
    # Mock successful response
    mock_response = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-4o",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "Test response"},
            "finish_reason": "stop"
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    }
    
    with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
        mock_response_obj = Mock()
        mock_response_obj.status_code = 200
        mock_response_obj.json = Mock(return_value=mock_response)
        mock_post.return_value = mock_response_obj
        
        # Make inference request
        chat_request = {
            "messages": [{"role": "user", "content": "Test"}],
            "temperature": 0.7
        }
        response = client.post(
            "/v1/chat/completions",
            json=chat_request,
            headers={"X-Agent": "test-agent"}
        )
        
        if response.status_code != 200:
            print(f"Error response: {response.json()}")
        assert response.status_code == 200
        data = response.json()
        assert data["choices"][0]["message"]["content"] == "Test response"
        # Verify no fallback was used
        assert data.get("_forgemind_metadata", {}).get("fallback_used") is False


@pytest.mark.asyncio
async def test_fallback_execution_primary_fails(client, sample_provider_data, sample_model_data):
    """Test fallback: primary fails, fallback succeeds."""
    # Create provider
    provider_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = provider_response.json()["id"]
    
    # Create primary and fallback models
    primary_model_data = {**sample_model_data, "provider_id": provider_id, "model_name": "primary"}
    primary_response = client.post("/api/v1/admin/llm/models", json=primary_model_data)
    primary_id = primary_response.json()["id"]
    
    fallback_model_data = {**sample_model_data, "provider_id": provider_id, "model_name": "fallback"}
    fallback_response = client.post("/api/v1/admin/llm/models", json=fallback_model_data)
    fallback_id = fallback_response.json()["id"]
    
    # Set routing and fallback
    client.put("/api/v1/admin/llm/agents/test-agent/routing", json={"primary_model_id": primary_id})
    client.put("/api/v1/admin/llm/agents/test-agent/fallback", json={"fallback_model_ids": [fallback_id]})
    
    # Mock primary failure, fallback success
    success_response = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "fallback",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "Fallback response"},
            "finish_reason": "stop"
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    }
    
    call_count = 0
    async def mock_post_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call (primary) fails
            raise httpx.RequestError("Connection error")
        else:
            # Second call (fallback) succeeds
            response = Mock()
            response.status_code = 200
            response.json = Mock(return_value=success_response)
            return response
    
    with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = mock_post_side_effect
        
        chat_request = {
            "messages": [{"role": "user", "content": "Test"}],
            "temperature": 0.7
        }
        response = client.post(
            "/v1/chat/completions",
            json=chat_request,
            headers={"X-Agent": "test-agent"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["choices"][0]["message"]["content"] == "Fallback response"
        # Verify fallback was used
        assert data.get("_forgemind_metadata", {}).get("fallback_used") is True
        assert call_count == 2  # Primary + 1 fallback attempt
