"""Tests for provider request/response translation."""

import pytest
from unittest.mock import patch, AsyncMock


def test_openai_passthrough(client, sample_provider_data, sample_model_data):
    """Test that OpenAI-compatible requests pass through unchanged."""
    # Create OpenAI provider
    provider_response = client.post("/api/v1/admin/llm/providers", json=sample_provider_data)
    if provider_response.status_code != 200:
        print(f"Provider creation failed: {provider_response.status_code} - {provider_response.json()}")
    provider_id = provider_response.json()["id"]
    
    model_data = {**sample_model_data, "provider_id": provider_id}
    model_response = client.post("/api/v1/admin/llm/models", json=model_data)
    model_id = model_response.json()["id"]
    
    # Set routing with same temperature as request to test passthrough
    client.put("/api/v1/admin/llm/agents/test-agent/routing", json={
        "primary_model_id": model_id,
        "temperature": 0.7,
        "max_tokens": 100
    })
    
    # Original OpenAI request
    chat_request = {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"}
        ],
        "temperature": 0.7,
        "max_tokens": 100
    }
    
    # Mock OpenAI response
    mock_response = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-4o",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "Hello! How can I help you?"},
            "finish_reason": "stop"
        }],
        "usage": {"prompt_tokens": 15, "completion_tokens": 10, "total_tokens": 25}
    }
    
    with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
        mock_response_obj = AsyncMock()
        mock_response_obj.status_code = 200
        mock_response_obj.json = lambda: mock_response  # json() is sync in httpx
        mock_post.return_value = mock_response_obj
        
        response = client.post(
            "/v1/chat/completions",
            json=chat_request,
            headers={"X-Agent": "test-agent"}
        )
        
        if response.status_code != 200:
            print(f"ERROR: {response.status_code} - {response.json()}")
        assert response.status_code == 200
        data = response.json()
        assert data["choices"][0]["message"]["content"] == "Hello! How can I help you?"
        
        # Verify the request was passed through to the provider
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        sent_data = call_args.kwargs.get("json", {})
        assert sent_data["messages"] == chat_request["messages"]
        assert sent_data["temperature"] == chat_request["temperature"]


def test_anthropic_translation(client):
    """Test Anthropic request translation from OpenAI format."""
    # Create Anthropic provider
    anthropic_provider = {
        "name": "Anthropic",
        "kind": "cloud",
        "provider_type": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "api_key": "sk-ant-test",
        "enabled": True
    }
    provider_response = client.post("/api/v1/admin/llm/providers", json=anthropic_provider)
    provider_id = provider_response.json()["id"]
    
    # Create Claude model
    claude_model = {
        "provider_id": provider_id,
        "model_name": "claude-3-5-sonnet-20241022",
        "display_name": "Claude 3.5 Sonnet",
        "context_window": 200000,
        "max_output": 8192,
        "cost_per_input_tok": 0.000003,
        "cost_per_output_tok": 0.000015,
        "capabilities": ["reasoning", "tools"],
        "enabled": True
    }
    model_response = client.post("/api/v1/admin/llm/models", json=claude_model)
    model_id = model_response.json()["id"]
    
    # Set routing
    client.put("/api/v1/admin/llm/agents/test-agent/routing", json={"primary_model_id": model_id})
    
    # OpenAI-format request
    chat_request = {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"}
        ],
        "temperature": 0.7,
        "max_tokens": 100
    }
    
    # Mock Anthropic response
    mock_anthropic_response = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "Hello! How can I help you?"}],
        "model": "claude-3-5-sonnet-20241022",
        "usage": {"input_tokens": 15, "output_tokens": 10}
    }
    
    with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_anthropic_response
        
        response = client.post(
            "/v1/chat/completions",
            json=chat_request,
            headers={"X-Agent": "test-agent"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # Response should be translated back to OpenAI format
        assert "choices" in data
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert data["choices"][0]["message"]["content"] == "Hello! How can I help you?"
        assert "usage" in data
        assert data["usage"]["prompt_tokens"] == 15
        assert data["usage"]["completion_tokens"] == 10
        
        # Verify the request was translated to Anthropic format
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        sent_data = call_args.kwargs.get("json", {})
        
        # Anthropic uses 'messages' but system message is a separate field
        assert "messages" in sent_data
        assert sent_data["messages"][0]["role"] == "user"
        assert sent_data["messages"][0]["content"] == "Hello!"
        # System prompt should be in the 'system' field for Anthropic
        assert "system" in sent_data
        assert sent_data["system"] == "You are a helpful assistant."


def test_vllm_passthrough(client):
    """Test that vLLM (OpenAI-compatible) requests pass through."""
    # Create vLLM provider
    vllm_provider = {
        "name": "Local vLLM",
        "kind": "self_hosted",
        "provider_type": "vllm",
        "base_url": "http://localhost:8000/v1",
        "enabled": True
    }
    provider_response = client.post("/api/v1/admin/llm/providers", json=vllm_provider)
    provider_id = provider_response.json()["id"]
    
    # Create model
    vllm_model = {
        "provider_id": provider_id,
        "model_name": "meta-llama/Llama-3.2-3B-Instruct",
        "display_name": "Llama 3.2 3B",
        "context_window": 8192,
        "max_output": 2048,
        "cost_per_input_tok": 0.0,
        "cost_per_output_tok": 0.0,
        "capabilities": ["reasoning"],
        "enabled": True
    }
    model_response = client.post("/api/v1/admin/llm/models", json=vllm_model)
    model_id = model_response.json()["id"]
    
    # Set routing
    client.put("/api/v1/admin/llm/agents/test-agent/routing", json={"primary_model_id": model_id})
    
    chat_request = {
        "messages": [{"role": "user", "content": "Test"}],
        "temperature": 0.7
    }
    
    mock_response = {
        "id": "cmpl-test",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "meta-llama/Llama-3.2-3B-Instruct",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "Response"},
            "finish_reason": "stop"
        }],
        "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15}
    }
    
    with patch('httpx.AsyncClient.post', new_callable=AsyncMock) as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_response
        
        response = client.post(
            "/v1/chat/completions",
            json=chat_request,
            headers={"X-Agent": "test-agent"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["choices"][0]["message"]["content"] == "Response"
        
        # vLLM is OpenAI-compatible, so request should pass through unchanged
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        sent_data = call_args.kwargs.get("json", {})
        assert sent_data["messages"] == chat_request["messages"]
