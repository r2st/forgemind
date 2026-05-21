"""Tests for shared/forgemind_common/llm_client.py."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forgemind_common.llm_client import LLMClient, LLMUsage, LLMResponse, get_llm_client


class _MockResponse:
    def __init__(self, status_code: int, json_data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


@pytest.mark.asyncio
async def test_chat_success():
    client = LLMClient("rca-agent")
    fake_resp = _MockResponse(
        200,
        {
            "id": "x",
            "choices": [{"message": {"content": "hello"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        },
    )
    with patch.object(client._client, "post", AsyncMock(return_value=fake_resp)):
        out = await client.chat([{"role": "user", "content": "hi"}])
    assert out.content == "hello"
    assert out.usage.total_tokens == 6


@pytest.mark.asyncio
async def test_chat_with_temperature_and_tools():
    client = LLMClient("rca-agent")
    fake_resp = _MockResponse(
        200,
        {"choices": [{"message": {"content": "ok"}}], "usage": {}},
    )
    with patch.object(client._client, "post", AsyncMock(return_value=fake_resp)) as p:
        await client.chat(
            [{"role": "user", "content": "x"}],
            model="custom",
            temperature=0.5,
            max_tokens=100,
            tools=[{"type": "function"}],
        )
    payload = p.await_args.kwargs["json"]
    assert payload["temperature"] == 0.5
    assert payload["max_tokens"] == 100
    assert payload["tools"][0]["type"] == "function"


@pytest.mark.asyncio
async def test_chat_error_raises():
    client = LLMClient("rca-agent")
    fake_resp = _MockResponse(500, text="upstream boom")
    with patch.object(client._client, "post", AsyncMock(return_value=fake_resp)):
        with pytest.raises(RuntimeError, match="LLM Gateway error 500"):
            await client.chat([{"role": "user", "content": "x"}])


@pytest.mark.asyncio
async def test_chat_no_choices_returns_empty_content():
    client = LLMClient("rca-agent")
    fake_resp = _MockResponse(200, {"usage": {}})
    with patch.object(client._client, "post", AsyncMock(return_value=fake_resp)):
        out = await client.chat([{"role": "user", "content": "x"}])
    assert out.content == ""


@pytest.mark.asyncio
async def test_chat_stream_yields_tokens():
    client = LLMClient("rca-agent")

    async def fake_aiter_lines():
        yield "data: " + json.dumps({"choices": [{"delta": {"content": "hello "}}]})
        yield "data: " + json.dumps({"choices": [{"delta": {"content": "world"}}]})
        yield "data: [DONE]"

    class _StreamResp:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        def aiter_lines(self):
            return fake_aiter_lines()

        async def aread(self):
            return b""

    def fake_stream(*a, **k):
        return _StreamResp()

    with patch.object(client._client, "stream", fake_stream):
        tokens = []
        async for t in client.chat_stream([{"role": "user", "content": "x"}]):
            tokens.append(t)
    assert tokens == ["hello ", "world"]


@pytest.mark.asyncio
async def test_chat_stream_error():
    client = LLMClient("rca-agent")

    class _ErrResp:
        status_code = 500

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def aread(self):
            return b"server boom"

    def fake_stream(*a, **k):
        return _ErrResp()

    with patch.object(client._client, "stream", fake_stream):
        with pytest.raises(RuntimeError, match="LLM Gateway error 500"):
            async for _ in client.chat_stream([{"role": "user", "content": "x"}]):
                pass


def test_get_llm_client_factory():
    client = get_llm_client("test-agent")
    assert isinstance(client, LLMClient)
    assert client.agent_name == "test-agent"


def test_dataclass_defaults():
    u = LLMUsage()
    assert u.total_tokens == 0
    r = LLMResponse(content="x")
    assert r.usage.total_tokens == 0
