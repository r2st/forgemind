"""LLM-assisted severity classification via the configured LLM gateway.

We deliberately use the cheap tier here — severity classification is
high-volume and doesn't need a powerful model. If the configured model is
unavailable, the gateway client falls back through the configured tiers.
"""

from __future__ import annotations

import json
from typing import Any

from forgemind_common import get_logger
from forgemind_common.llm_gateway import GatewayError, ModelTier, get_gateway

log = get_logger(__name__)


SYSTEM_PROMPT = """You are a factory operations triage AI. Given a machine anomaly,
classify its severity and produce a short operator-facing title.

Respond as compact JSON with keys:
  severity   - one of INFO, LOW, MEDIUM, HIGH, CRITICAL
  title      - <= 80 chars
  description- <= 280 chars, plain English, no markdown

Calibration:
  CRITICAL  immediate stop / safety risk / major scrap
  HIGH      production at risk in next shift
  MEDIUM    investigate within shift
  LOW       informational, monitor
  INFO      noise / inside normal band
"""


async def classify_severity(payload: dict[str, Any]) -> dict[str, Any]:
    gw = get_gateway()
    user = json.dumps(payload, default=str)
    try:
        resp = await gw.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            tier=ModelTier.FAST,
            temperature=0.0,
            max_tokens=200,
            response_format={"type": "json_object"},
        )
        out = json.loads(resp.content or "{}")
        return {
            "severity": out.get("severity", "MEDIUM").upper(),
            "title": out.get("title") or f"{payload.get('metric','signal')} anomaly on {payload.get('machine_id')}",
            "description": out.get("description") or "Automated anomaly detection flagged this event.",
            "model_used": resp.usage.model,
            "tokens": resp.usage.total_tokens,
            "cost_usd": resp.usage.cost_usd,
        }
    except (GatewayError, json.JSONDecodeError) as exc:
        log.warning("severity.fallback_heuristic", error=str(exc))
        return _heuristic(payload)


def _heuristic(payload: dict[str, Any]) -> dict[str, Any]:
    score = float(payload.get("score") or 0.0)
    sev = "INFO"
    if score >= 0.9:
        sev = "CRITICAL"
    elif score >= 0.75:
        sev = "HIGH"
    elif score >= 0.6:
        sev = "MEDIUM"
    elif score >= 0.45:
        sev = "LOW"
    metric = payload.get("metric") or "signal"
    machine = payload.get("machine_id") or "unknown"
    return {
        "severity": sev,
        "title": f"{metric} anomaly on {machine}",
        "description": (
            f"Anomalous {metric}={payload.get('value')} (z={payload.get('z_score'):.2f}). "
            "Auto-classified by heuristic fallback."
        ),
        "model_used": "heuristic",
        "tokens": 0,
        "cost_usd": 0.0,
    }
