"""Pytest fixtures for LLM Gateway tests."""

import os
import sys
from pathlib import Path

import pytest
import asyncio
from fastapi.testclient import TestClient

# Add services/llm-gateway to path AND shared/ so forgemind_common imports.
repo_root = Path(__file__).parent.parent.parent
gateway_path = repo_root / "services" / "llm-gateway"
shared_path = repo_root / "shared"
sys.path.insert(0, str(gateway_path))
sys.path.insert(0, str(shared_path))

# Set test environment variables before importing app
os.environ["GATEWAY_SECRET_KEY"] = "rgIj78g3GcR0XU78dHUc8BR9ci5kVv34Fsw1jU5Ao_E="
os.environ["POSTGRES_DSN"] = "sqlite+aiosqlite:///:memory:?cache=shared"
os.environ["JWT_SECRET"] = "llm-gateway-tests-jwt-secret"
os.environ["ENABLE_AUTH"] = "false"

from app.main import app
from app import database


@pytest.fixture(scope="function", autouse=True)
def client():
    """FastAPI test client with fresh database."""
    # Reset global engine and session maker to ensure fresh DB for each test
    database.engine = None
    database.async_session_maker = None
    
    # TestClient handles async automatically and triggers startup events
    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client
    
    # Clean up the engine after the test
    if database.engine is not None:
        import asyncio
        try:
            # Try to dispose the engine
            asyncio.get_event_loop().run_until_complete(database.engine.dispose())
        except:
            pass
    database.engine = None
    database.async_session_maker = None


@pytest.fixture
def sample_provider_data():
    """Sample provider data for tests."""
    return {
        "name": "Test OpenAI",
        "kind": "cloud",
        "provider_type": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-test-key",
        "enabled": True,
        "provider_metadata": {}
    }


@pytest.fixture
def sample_model_data():
    """Sample model data for tests."""
    return {
        "model_name": "gpt-4o",
        "display_name": "GPT-4o",
        "context_window": 128000,
        "max_output_tokens": 4096,
        "cost_per_input_token": 0.000005,
        "cost_per_output_token": 0.000015,
        "capabilities": {
            "reasoning": True,
            "vision": True,
            "tools": True,
            "streaming": True
        },
        "enabled": True
    }


@pytest.fixture
def sample_routing_config():
    """Sample agent routing config for tests."""
    return {
        "routing_strategy": "highest_quality",
        "temperature": 0.7,
        "max_tokens": 4096,
        "reasoning_mode": True,
        "timeout_s": 120,
        "retry_policy": "exponential_backoff"
    }


def create_mock_http_response(status_code: int, json_data: dict):
    """Helper to create a properly structured mock HTTP response.
    
    httpx response.json() is synchronous, so we need to avoid AsyncMock for it.
    """
    from unittest.mock import AsyncMock
    mock_response = AsyncMock()
    mock_response.status_code = status_code
    mock_response.json = lambda: json_data  # Sync method, not async
    return mock_response
