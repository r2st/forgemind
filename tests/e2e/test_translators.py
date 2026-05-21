"""E2E tests for the LLM-gateway provider translators."""

from __future__ import annotations

import importlib
import pytest


def _load_translators():
    # Make sure services/llm-gateway is on sys.path.
    return importlib.import_module("translators") if False else _load()


def _load():
    import sys
    from pathlib import Path

    p = Path(__file__).resolve().parent.parent.parent / "services" / "llm-gateway"
    sys.path.insert(0, str(p))
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    import app.translators as m
    import app.schemas as s
    return m, s


@pytest.mark.asyncio
async def test_openai_translator_passthrough():
    mod, schemas = _load()
    t = mod.OpenAICompatibleTranslator("https://api.openai.com/v1")
    req = schemas.ChatCompletionRequest(
        model="gpt-4o-mini",
        messages=[schemas.ChatMessage(role="user", content="hello")],
        temperature=0.5,
        max_tokens=100,
    )
    url, payload, headers = await t.translate_request(req, "sk-key")
    assert url == "https://api.openai.com/v1/chat/completions"
    assert headers["Authorization"] == "Bearer sk-key"
    assert payload["model"] == "gpt-4o-mini"

    sample_response = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "hi"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
    }
    resp = await t.translate_response(sample_response, "gpt-4o-mini")
    assert resp.choices[0].message.content == "hi"


@pytest.mark.asyncio
async def test_anthropic_translator():
    mod, schemas = _load()
    t = mod.AnthropicTranslator("https://api.anthropic.com/v1")
    req = schemas.ChatCompletionRequest(
        model="claude-3-5-sonnet",
        messages=[
            schemas.ChatMessage(role="system", content="you are friendly"),
            schemas.ChatMessage(role="user", content="hello"),
        ],
        temperature=0.2,
        max_tokens=64,
    )
    url, payload, headers = await t.translate_request(req, "key-123")
    assert url.endswith("/messages")
    assert headers["x-api-key"] == "key-123"
    assert "anthropic-version" in headers
    assert payload["system"] == "you are friendly"
    assert payload["messages"][0]["role"] == "user"

    sample_response = {
        "id": "msg-1",
        "content": [{"type": "text", "text": "hi back"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }
    resp = await t.translate_response(sample_response, "claude-3-5-sonnet")
    assert resp.choices[0].message.content == "hi back"
    assert resp.usage.total_tokens == 12


@pytest.mark.asyncio
async def test_anthropic_translator_no_system():
    mod, schemas = _load()
    t = mod.AnthropicTranslator("https://api.anthropic.com/v1")
    req = schemas.ChatCompletionRequest(
        model="claude-3-5-sonnet",
        messages=[schemas.ChatMessage(role="user", content="hi")],
    )
    _, payload, _ = await t.translate_request(req, "k")
    assert "system" not in payload


@pytest.mark.asyncio
async def test_gemini_translator():
    mod, schemas = _load()
    t = mod.GeminiTranslator("https://generativelanguage.googleapis.com/v1beta")
    req = schemas.ChatCompletionRequest(
        model="gemini-1.5-pro",
        messages=[
            schemas.ChatMessage(role="user", content="ping"),
            schemas.ChatMessage(role="assistant", content="pong"),
            schemas.ChatMessage(role="user", content="again"),
        ],
        temperature=0.1,
        max_tokens=32,
    )
    url, payload, headers = await t.translate_request(req, "api-key")
    assert "key=api-key" in url
    assert "gemini-1.5-pro:generateContent" in url
    assert payload["generationConfig"]["temperature"] == 0.1
    # roles should map: user→user, assistant→model.
    assert {c["role"] for c in payload["contents"]} <= {"user", "model"}

    sample_response = {
        "candidates": [
            {"content": {"parts": [{"text": "answer"}]}}
        ],
        "usageMetadata": {
            "promptTokenCount": 3,
            "candidatesTokenCount": 1,
            "totalTokenCount": 4,
        },
    }
    resp = await t.translate_response(sample_response, "gemini-1.5-pro")
    assert resp.choices[0].message.content == "answer"
    assert resp.usage.total_tokens == 4


@pytest.mark.asyncio
async def test_gemini_translator_empty_candidates():
    mod, schemas = _load()
    t = mod.GeminiTranslator("https://x.test/v1")
    resp = await t.translate_response({}, "gemini-1.5-pro")
    assert resp.choices[0].message.content == ""


def test_get_translator_factory():
    mod, schemas = _load()
    assert isinstance(
        mod.get_translator(schemas.ProviderType.ANTHROPIC, "u"), mod.AnthropicTranslator
    )
    assert isinstance(
        mod.get_translator(schemas.ProviderType.GEMINI, "u"), mod.GeminiTranslator
    )
    assert isinstance(
        mod.get_translator(schemas.ProviderType.OPENAI, "u"),
        mod.OpenAICompatibleTranslator,
    )
    assert isinstance(
        mod.get_translator(schemas.ProviderType.OLLAMA, "u"),
        mod.OpenAICompatibleTranslator,
    )


def test_translator_base_class_raises():
    mod, _ = _load()
    import asyncio

    with pytest.raises(NotImplementedError):
        asyncio.get_event_loop().run_until_complete(
            mod.ProviderTranslator().translate_request(None, "k")
        )
    with pytest.raises(NotImplementedError):
        asyncio.get_event_loop().run_until_complete(
            mod.ProviderTranslator().translate_response({}, "m")
        )


@pytest.mark.asyncio
async def test_anthropic_translator_response_no_content():
    mod, _ = _load()
    t = mod.AnthropicTranslator("u")
    resp = await t.translate_response({}, "claude")
    assert resp.choices[0].message.content == ""
