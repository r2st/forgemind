"""Tests for audit logging and quota enforcement."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock


def test_audit_log_records_inference(client, sample_provider_data, sample_model_data):
    """Test that audit log records inference calls."""
    # Create provider and model
    provider_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = provider_response.json()["id"]
    
    model_data = {**sample_model_data, "provider_id": provider_id}
    model_response = client.post("/api/v1/admin/llm/models", json=model_data)
    model_id = model_response.json()["id"]
    
    # Set routing
    client.put("/api/v1/admin/llm/agents/test-agent/routing", json={"primary_model_id": model_id})
    
    # Mock response
    mock_response_data = {
        "id": "chatcmpl-test-123",
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
        mock_response_obj = AsyncMock()
        mock_response_obj.status_code = 200
        mock_response_obj.json = lambda: mock_response_data
        mock_post.return_value = mock_response_obj
        
        # Make inference request
        chat_request = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Test"}],
            "temperature": 0.7
        }
        inference_response = client.post(
            "/v1/chat/completions",
            json=chat_request,
            headers={"X-Agent": "test-agent"}
        )
        
        assert inference_response.status_code == 200
    
    # Check audit log
    audit_response = client.get("/api/v1/admin/llm/audit?limit=10")
    assert audit_response.status_code == 200
    
    audit_data = audit_response.json()
    assert "entries" in audit_data
    assert len(audit_data["entries"]) > 0
    
    # Find the entry for our request
    entry = audit_data["entries"][0]
    assert entry["agent"] == "test-agent"
    assert entry["model"] == sample_model_data["model_name"]
    assert entry["status"] == "success"
    assert entry["input_tokens"] == 10
    assert entry["output_tokens"] == 20
    assert entry["fallback_used"] is False


def test_audit_log_filters(client, sample_provider_data, sample_model_data):
    """Test audit log filtering by agent, model, provider."""
    # Create provider and model
    provider_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = provider_response.json()["id"]
    
    model_data = {**sample_model_data, "provider_id": provider_id}
    model_response = client.post("/api/v1/admin/llm/models", json=model_data)
    model_id = model_response.json()["id"]
    
    # Set routing
    client.put("/api/v1/admin/llm/agents/test-agent/routing", json={"primary_model_id": model_id})
    
    mock_response_data = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-4o",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "Test"},
            "finish_reason": "stop"
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    }
    
    with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
        mock_response_obj = AsyncMock()
        mock_response_obj.status_code = 200
        mock_response_obj.json = lambda: mock_response_data
        mock_post.return_value = mock_response_obj
        
        # Make request
        chat_request = {"messages": [{"role": "user", "content": "Test"}]}
        client.post(
            "/v1/chat/completions",
            json=chat_request,
            headers={"X-Agent": "test-agent"}
        )
    
    # Test filtering by agent
    audit_response = client.get("/api/v1/admin/llm/audit?agent=test-agent")
    assert audit_response.status_code == 200
    entries = audit_response.json()["entries"]
    assert all(e["agent"] == "test-agent" for e in entries)
    
    # Test filtering by model
    audit_response = client.get(f"/api/v1/admin/llm/audit?model={sample_model_data['model_name']}")
    assert audit_response.status_code == 200
    entries = audit_response.json()["entries"]
    assert all(e["model"] == sample_model_data["model_name"] for e in entries)


def test_quota_enforcement_per_agent(client, sample_provider_data, sample_model_data):
    """Test that per-agent quotas are enforced."""
    # Create provider and model
    provider_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = provider_response.json()["id"]
    
    model_data = {**sample_model_data, "provider_id": provider_id}
    model_response = client.post("/api/v1/admin/llm/models", json=model_data)
    model_id = model_response.json()["id"]
    
    # Set routing with quota
    routing_config = {
        "primary_model_id": model_id,
        "quota": {
            "max_requests_per_hour": 5,
            "max_tokens_per_hour": 1000
        }
    }
    client.put("/api/v1/admin/llm/agents/quota-test-agent/routing", json=routing_config)
    
    mock_response_data = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-4o",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "Test"},
            "finish_reason": "stop"
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    }
    
    with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
        mock_response_obj = AsyncMock()
        mock_response_obj.status_code = 200
        mock_response_obj.json = lambda: mock_response_data
        mock_post.return_value = mock_response_obj
        
        chat_request = {"messages": [{"role": "user", "content": "Test"}]}
        
        # Make requests within quota
        for i in range(5):
            response = client.post(
                "/v1/chat/completions",
                json=chat_request,
                headers={"X-Agent": "quota-test-agent"}
            )
            assert response.status_code == 200
        
        # Next request should exceed quota
        response = client.post(
            "/v1/chat/completions",
            json=chat_request,
            headers={"X-Agent": "quota-test-agent"}
        )
        assert response.status_code == 429  # Too Many Requests


def test_cost_tracking(client, sample_provider_data, sample_model_data):
    """Test that costs are tracked correctly."""
    # Create provider and model
    provider_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    provider_id = provider_response.json()["id"]
    
    model_data = {
        **sample_model_data,
        "provider_id": provider_id,
        "cost_per_input_tok": 0.000005,  # $5 per 1M tokens
        "cost_per_output_tok": 0.000015  # $15 per 1M tokens
    }
    model_response = client.post("/api/v1/admin/llm/models", json=model_data)
    model_id = model_response.json()["id"]
    
    # Set routing
    client.put("/api/v1/admin/llm/agents/cost-test-agent/routing", json={"primary_model_id": model_id})
    
    mock_response_data = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-4o",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "Test"},
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 2000,
            "total_tokens": 3000
        }
    }
    
    with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
        mock_response_obj = AsyncMock()
        mock_response_obj.status_code = 200
        mock_response_obj.json = lambda: mock_response_data
        mock_post.return_value = mock_response_obj
        
        # Make inference request
        chat_request = {"messages": [{"role": "user", "content": "Test"}]}
        inference_response = client.post(
            "/v1/chat/completions",
            json=chat_request,
            headers={"X-Agent": "cost-test-agent"}
        )
        
        assert inference_response.status_code == 200
        
        # Verify cost is calculated and returned
        data = inference_response.json()
        metadata = data.get("_forgemind_metadata", {})
        
        # Cost = (1000 * 0.000005) + (2000 * 0.000015) = 0.005 + 0.03 = 0.035
        expected_cost = (1000 * 0.000005) + (2000 * 0.000015)
        assert "cost_usd" in metadata
        assert abs(metadata["cost_usd"] - expected_cost) < 0.0001
    
    # Check cost endpoint
    cost_response = client.get("/admin/cost?window=day")
    assert cost_response.status_code == 200
    
    cost_data = cost_response.json()
    assert "by_agent" in cost_data
    assert "cost-test-agent" in cost_data["by_agent"]
    assert cost_data["by_agent"]["cost-test-agent"] >= expected_cost
