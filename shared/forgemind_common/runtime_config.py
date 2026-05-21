"""Runtime LLM configuration for ForgeMind agents.

The admin panel writes a small shared JSON file with provider/model/key
overrides. Agent services read it on every run, so switching a key or
provider does not require rebuilding containers.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .config import get_settings
from .tfy_gateway import ModelTier

ProviderName = Literal["default", "truefoundry", "openai", "openai-compatible", "disabled"]

KNOWN_AGENTS: list[dict[str, str]] = [
    {
        "name": "supervisor-agent",
        "display_name": "Supervisor",
        "role": "routes requests to specialist agents",
        "tier": "powerful",
        "service": "ai-orchestrator",
    },
    {
        "name": "monitoring-agent",
        "display_name": "Monitoring Agent",
        "role": "triages incidents and plant state",
        "tier": "fast",
        "service": "ai-orchestrator",
    },
    {
        "name": "predictive-maintenance-agent",
        "display_name": "Predictive Maintenance Agent",
        "role": "forecasts failure risk and maintenance windows",
        "tier": "powerful",
        "service": "ai-orchestrator",
    },
    {
        "name": "production-optimization-agent",
        "display_name": "Production Optimization Agent",
        "role": "finds bottlenecks and scheduling improvements",
        "tier": "powerful",
        "service": "ai-orchestrator",
    },
    {
        "name": "reporting-agent",
        "display_name": "Reporting Agent",
        "role": "generates shift and executive summaries",
        "tier": "powerful",
        "service": "ai-orchestrator",
    },
    {
        "name": "rca-agent",
        "display_name": "RCA Agent",
        "role": "investigates root cause for incidents",
        "tier": "powerful",
        "service": "rca-service",
    },
    {
        "name": "chatops-agent",
        "display_name": "ChatOps Agent",
        "role": "operator-facing conversational interface",
        "tier": "powerful",
        "service": "chatops-service",
    },
    {
        "name": "remediation-agent",
        "display_name": "Remediation Agent",
        "role": "turns RCA output into remediation actions",
        "tier": "fast",
        "service": "workflow-engine",
    },
]


@dataclass
class AgentLLMConfig:
    provider: ProviderName = "default"
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    enabled: bool = True


@dataclass(frozen=True)
class ResolvedLLMConfig:
    provider: Literal["truefoundry", "openai", "openai-compatible", "disabled"]
    base_url: str
    api_key: str
    model_by_tier: dict[ModelTier, str]
    model_override: str = ""
    enabled: bool = True
    source: str = "settings"
    api_key_source: str = "settings"

    def model_for(self, tier: ModelTier) -> str:
        return self.model_override or self.model_by_tier[tier]

    def openai_base_url(self) -> str:
        base = self.base_url.rstrip("/")
        if self.provider == "truefoundry":
            return f"{base}/api/inference/openai"
        return base

    def signature(self) -> tuple[str, str, str, str, bool]:
        return (
            self.provider,
            self.openai_base_url(),
            self.model_override,
            _secret_fingerprint(self.api_key),
            self.enabled,
        )


def config_path() -> Path:
    return Path(get_settings().agent_config_path)


def load_runtime_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {"default": {}, "agents": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"default": {}, "agents": {}}
    if not isinstance(data, dict):
        return {"default": {}, "agents": {}}
    data.setdefault("default", {})
    data.setdefault("agents", {})
    return data


def save_runtime_config(data: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {
        "default": _clean_config(data.get("default") or {}),
        "agents": {
            name: _clean_config(cfg)
            for name, cfg in (data.get("agents") or {}).items()
            if isinstance(name, str) and isinstance(cfg, dict)
        },
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(clean, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)


def update_default_config(patch: dict[str, Any]) -> dict[str, Any]:
    data = load_runtime_config()
    current = data.get("default") or {}
    data["default"] = _apply_patch(current, patch)
    save_runtime_config(data)
    return data["default"]


def update_agent_config(agent_name: str, patch: dict[str, Any]) -> dict[str, Any]:
    data = load_runtime_config()
    agents = data.setdefault("agents", {})
    current = agents.get(agent_name) or {}
    agents[agent_name] = _apply_patch(current, patch)
    save_runtime_config(data)
    return agents[agent_name]


def get_agent_config(agent_name: str | None) -> AgentLLMConfig:
    data = load_runtime_config()
    raw = (data.get("agents") or {}).get(agent_name or "") or {}
    return AgentLLMConfig(**_clean_config(raw))


def resolve_llm_config(agent_name: str | None = None) -> ResolvedLLMConfig:
    settings = get_settings()
    data = load_runtime_config()
    default_raw = _clean_config(data.get("default") or {})
    agent_raw = _clean_config((data.get("agents") or {}).get(agent_name or "") or {})

    default_provider = default_raw.get("provider") or "default"
    provider = agent_raw.get("provider") or "default"
    if provider == "default":
        provider = default_provider
    if provider == "default":
        provider = settings.llm_provider
    if provider not in {"truefoundry", "openai", "openai-compatible", "disabled"}:
        provider = "disabled"

    settings_base, settings_key, tier_models = _settings_provider_defaults(provider)
    default_base = default_raw.get("base_url") or ""
    default_key = default_raw.get("api_key") or ""
    base_url = agent_raw.get("base_url") or default_base or settings_base
    api_key = agent_raw.get("api_key") or default_key or settings_key
    model_override = agent_raw.get("model") or default_raw.get("model") or ""
    enabled = bool(agent_raw.get("enabled", True)) and bool(default_raw.get("enabled", True))

    source = "agent" if agent_raw else ("runtime-default" if default_raw else "settings")
    api_key_source = "agent" if agent_raw.get("api_key") else ("runtime-default" if default_key else "settings")
    return ResolvedLLMConfig(
        provider=provider,  # type: ignore[arg-type]
        base_url=base_url,
        api_key=api_key,
        model_by_tier=tier_models,
        model_override=model_override,
        enabled=enabled,
        source=source,
        api_key_source=api_key_source,
    )


def config_for_admin(agent_name: str | None = None) -> dict[str, Any]:
    raw = get_agent_config(agent_name) if agent_name else AgentLLMConfig(**_clean_config((load_runtime_config().get("default") or {})))
    resolved = resolve_llm_config(agent_name)
    return {
        "provider": raw.provider,
        "base_url": raw.base_url,
        "model": raw.model,
        "enabled": raw.enabled,
        "api_key_set": bool(raw.api_key),
        "api_key_preview": mask_secret(raw.api_key),
        "resolved_provider": resolved.provider,
        "resolved_base_url": resolved.base_url,
        "resolved_model": resolved.model_for(_tier_for_agent(agent_name)),
        "resolved_enabled": resolved.enabled,
        "resolved_api_key_set": bool(resolved.api_key),
        "resolved_api_key_source": resolved.api_key_source,
    }


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _settings_provider_defaults(
    provider: str,
) -> tuple[str, str, dict[ModelTier, str]]:
    settings = get_settings()
    if provider == "truefoundry":
        return (
            settings.tfy_gateway_base_url,
            settings.tfy_gateway_api_key,
            {
                ModelTier.FAST: settings.tfy_model_fast,
                ModelTier.POWERFUL: settings.tfy_model_powerful,
                ModelTier.FALLBACK: settings.tfy_model_fallback,
                ModelTier.EMBEDDING: settings.tfy_model_embedding,
            },
        )
    if provider in {"openai", "openai-compatible"}:
        return (
            settings.openai_base_url,
            settings.openai_api_key,
            {
                ModelTier.FAST: settings.openai_model_fast,
                ModelTier.POWERFUL: settings.openai_model_powerful,
                ModelTier.FALLBACK: settings.openai_model_fallback,
                ModelTier.EMBEDDING: settings.openai_model_embedding,
            },
        )
    return (
        "",
        "",
        {
            ModelTier.FAST: "",
            ModelTier.POWERFUL: "",
            ModelTier.FALLBACK: "",
            ModelTier.EMBEDDING: "",
        },
    )


def _clean_config(raw: dict[str, Any]) -> dict[str, Any]:
    provider = str(raw.get("provider") or "default").strip()
    if provider not in {"default", "truefoundry", "openai", "openai-compatible", "disabled"}:
        provider = "default"
    return {
        "provider": provider,
        "base_url": str(raw.get("base_url") or "").strip(),
        "model": str(raw.get("model") or "").strip(),
        "api_key": str(raw.get("api_key") or "").strip(),
        "enabled": bool(raw.get("enabled", True)),
    }


def _apply_patch(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = _clean_config(current)
    for key in ("provider", "base_url", "model", "enabled"):
        if key in patch:
            out[key] = patch[key]
    if patch.get("clear_api_key"):
        out["api_key"] = ""
    elif "api_key" in patch and patch["api_key"] is not None:
        out["api_key"] = patch["api_key"]
    return _clean_config(out)


def _tier_for_agent(agent_name: str | None) -> ModelTier:
    for agent in KNOWN_AGENTS:
        if agent["name"] == agent_name:
            return ModelTier.FAST if agent["tier"] == "fast" else ModelTier.POWERFUL
    return ModelTier.POWERFUL


def _secret_fingerprint(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
