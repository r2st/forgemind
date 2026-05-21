"""Cover forgemind_common.runtime_config edge cases."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from forgemind_common import (
    config_for_admin,
    load_runtime_config,
    resolve_llm_config,
    save_runtime_config,
    update_agent_config,
    update_default_config,
)
from forgemind_common import runtime_config as rc
from forgemind_common.config import get_settings


@pytest.fixture
def temp_config(monkeypatch):
    """Point AGENT_CONFIG_PATH at a fresh temp file."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "agent_config.json"
        monkeypatch.setattr(get_settings(), "agent_config_path", str(path))
        # invalidate cache so the new path is read
        get_settings.cache_clear()  # type: ignore[attr-defined]
        monkeypatch.setenv("AGENT_CONFIG_PATH", str(path))
        get_settings.cache_clear()  # type: ignore[attr-defined]
        yield path


def test_load_runtime_config_missing(temp_config):
    cfg = load_runtime_config()
    assert cfg == {"default": {}, "agents": {}}


def test_load_runtime_config_corrupt(temp_config):
    temp_config.write_text("not json")
    cfg = load_runtime_config()
    assert cfg == {"default": {}, "agents": {}}


def test_load_runtime_config_not_dict(temp_config):
    temp_config.write_text(json.dumps([1, 2, 3]))
    cfg = load_runtime_config()
    assert cfg == {"default": {}, "agents": {}}


def test_save_and_load_round_trip(temp_config):
    save_runtime_config(
        {
            "default": {"provider": "openai-compatible", "model": "gpt-4o"},
            "agents": {
                "rca-agent": {"provider": "default", "api_key": "k", "enabled": True},
                "": {"ignored": True},  # invalid name, dropped
            },
        }
    )
    cfg = load_runtime_config()
    assert cfg["agents"]["rca-agent"]["provider"] == "default"


def test_update_default_and_agent(temp_config):
    update_default_config({"provider": "openai-compatible", "model": "gpt-4o-mini"})
    update_agent_config("rca-agent", {"api_key": "k", "base_url": "http://x/y"})
    update_agent_config("rca-agent", {"clear_api_key": True})
    cfg = load_runtime_config()
    assert cfg["agents"]["rca-agent"]["api_key"] == ""


def test_resolve_with_overrides(temp_config):
    update_default_config({"provider": "openai-compatible", "api_key": "k1", "model": "gpt-4o"})
    update_agent_config("rca-agent", {"api_key": "k2", "model": "claude-3"})
    resolved = resolve_llm_config("rca-agent")
    assert resolved.api_key == "k2"
    assert resolved.model_override == "claude-3"


def test_resolve_disabled(temp_config):
    update_default_config({"enabled": False})
    resolved = resolve_llm_config("rca-agent")
    assert resolved.enabled is False


def test_resolve_explicit_disabled(temp_config):
    update_default_config({"provider": "disabled"})
    resolved = resolve_llm_config()
    assert resolved.provider == "disabled"


def test_resolve_unknown_provider_treated_as_default(temp_config):
    # _clean_config rejects unknown providers, mapping them to "default"
    # which then resolves to settings.llm_provider.
    update_default_config({"provider": "weird-thing"})
    resolved = resolve_llm_config()
    assert resolved.provider in ("openai-compatible", "disabled")


def test_config_for_admin_default(temp_config):
    out = config_for_admin()
    assert "provider" in out
    assert "resolved_provider" in out


def test_config_for_admin_agent(temp_config):
    update_agent_config("rca-agent", {"provider": "openai-compatible", "api_key": "k"})
    out = config_for_admin("rca-agent")
    assert out["api_key_set"] is True


def test_mask_secret():
    assert rc.mask_secret("") == ""
    assert rc.mask_secret("abc") == "***"
    assert rc.mask_secret("abcdefghijklmnop") == "abcd...mnop"


def test_secret_fingerprint():
    assert rc._secret_fingerprint("") == ""
    assert len(rc._secret_fingerprint("key")) == 12


def test_normalize_provider_aliases():
    assert rc._normalize_provider("OpenAI") == "openai-compatible"
    assert rc._normalize_provider("generic") == "openai-compatible"
    assert rc._normalize_provider("custom") == "openai-compatible"
    assert rc._normalize_provider("openai-compatible") == "openai-compatible"


def test_clean_config_with_unknown_provider():
    cleaned = rc._clean_config({"provider": "weird"})
    assert cleaned["provider"] == "default"


def test_resolved_signature_changes():
    r = rc.ResolvedLLMConfig(
        provider="openai-compatible",
        base_url="http://x/",
        api_key="k",
        model_by_tier={t: "m" for t in rc.ModelTier},
    )
    assert r.signature() == r.signature()  # stable
    assert r.openai_base_url() == "http://x"  # trailing slash stripped


def test_tier_for_agent_unknown():
    from forgemind_common.llm_gateway import ModelTier

    assert rc._tier_for_agent("nonsense") == ModelTier.POWERFUL


def test_tier_for_fast_agent():
    from forgemind_common.llm_gateway import ModelTier

    # monitoring-agent is FAST
    assert rc._tier_for_agent("monitoring-agent") == ModelTier.FAST
