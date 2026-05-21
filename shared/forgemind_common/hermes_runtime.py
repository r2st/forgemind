"""Hermes Agent runtime, wired through a configurable OpenAI-compatible gateway.

This is the keystone integration between the runtime layers:

  * **Hermes** (Nous Research `hermes-agent`) provides the agent loop:
    tool calling, multi-turn memory, sub-agent delegation, skill
    creation, planning.

  * **LLM providers** supply the OpenAI-compatible inference substrate.
    TrueFoundry is supported for gateway routing and observability, but
    agents can also use direct OpenAI or another compatible endpoint.

We pass the resolved provider as Hermes's `base_url` + `api_key`, so each
agent can run through TrueFoundry, direct OpenAI, or a custom compatible
endpoint.

If the `hermes-agent` package isn't installed (e.g., during unit tests
or a thin deploy) we degrade gracefully to a `LiteAgent` that uses the
configured gateway directly with manual tool dispatch. The public API
(`HermesAgentRuntime.run`) is identical in both modes so callers don't
care.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import get_settings
from .tfy_gateway import GatewayError, ModelTier, get_gateway

log = logging.getLogger(__name__)

# Import Hermes lazily — it's a heavy dep and may not be installed in
# every container (e.g., the simulator doesn't need it).
try:  # pragma: no cover
    from run_agent import AIAgent as _HermesAIAgent  # type: ignore[import-not-found]
    HERMES_AVAILABLE = True
except Exception:  # noqa: BLE001
    _HermesAIAgent = None
    HERMES_AVAILABLE = False


# ---------------------------------------------------------------------
# Activity ledger
# ---------------------------------------------------------------------


@dataclass
class AgentActivity:
    """A single run of a Hermes agent. Surfaced on the AI Agent Activity UI."""

    activity_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_name: str = ""
    task: str = ""
    status: str = "running"        # running | completed | error
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    result: str | None = None
    error: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    tfy_trace_id: str = ""
    model_used: str = ""
    tier: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "agent_name": self.agent_name,
            "task": self.task,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "tool_calls": self.tool_calls,
            "messages": self.messages[-10:],   # keep payload bounded
            "result": (self.result or "")[:4000],
            "error": self.error,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": round(self.cost_usd, 6),
            "tfy_trace_id": self.tfy_trace_id,
            "model_used": self.model_used,
            "tier": self.tier,
        }


class ActivityLedger:
    """In-memory ring buffer of recent agent activity (newest first)."""

    def __init__(self, capacity: int = 500) -> None:
        self._items: list[AgentActivity] = []
        self._capacity = capacity
        self._lock = asyncio.Lock()

    async def record(self, activity: AgentActivity) -> None:
        async with self._lock:
            self._items.insert(0, activity)
            del self._items[self._capacity:]

    def snapshot(self, agent: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        items = self._items if agent is None else [a for a in self._items if a.agent_name == agent]
        return [a.to_dict() for a in items[:limit]]


_LEDGER = ActivityLedger()


def get_activity_ledger() -> ActivityLedger:
    return _LEDGER


# ---------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            self._tools[name] = Tool(name, description, parameters, fn)
            return fn

        return deco

    def add(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def openai_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)


# ---------------------------------------------------------------------
# Hermes runtime
# ---------------------------------------------------------------------


class HermesAgentRuntime:
    """Wraps Nous Research's `AIAgent`, routed through configured inference.

    Each ForgeMind specialist (Monitoring, RCA, PdM, Optimization,
    Reporting, ChatOps) is one instance of this runtime with its own
    system prompt and tool registry. Tool calls are dispatched locally
    so they can hit our Postgres, NATS, and HTTP services directly.

    Why not just use OpenAI SDK? Because Hermes gives us:
      * sub-agent delegation (one agent can spawn another)
      * skill memory (agents accumulate operational know-how)
      * trajectory capture (we can later fine-tune on real factory ops)
      * a uniform context-files loader (`AGENTS.md`)

    Why use a gateway provider? Because it gives us:
      * provider abstraction (OpenAI/Anthropic/Ollama via one URL)
      * cost-aware routing (cheap tier for summaries, powerful for RCA)
      * automatic fallback to local Ollama when upstream errors
      * per-request token + cost accounting, exposed as Prom metrics
      * one place to enforce rate limits, quotas, audit logs
    """

    def __init__(
        self,
        agent_name: str,
        system_prompt: str,
        *,
        tools: ToolRegistry | None = None,
        tier: ModelTier = ModelTier.POWERFUL,
        max_iterations: int = 12,
    ) -> None:
        self.agent_name = agent_name
        self.system_prompt = system_prompt
        self.tools = tools or ToolRegistry()
        self.tier = tier
        self.max_iterations = max_iterations
        self._settings = get_settings()
        self._gateway = get_gateway(agent_name)
        self._backend_signature: tuple[str, str, str, str, bool] | None = None
        self._hermes: Any | None = None
        self._configure_backend()

    def _configure_backend(self) -> None:
        """Refresh gateway/Hermes wiring from runtime config if it changed."""
        self._gateway = get_gateway(self.agent_name)
        signature = self._gateway.backend_signature(self.tier)
        if signature == self._backend_signature:
            return
        self._backend_signature = signature
        self._hermes = None
        if not self._gateway.enabled:
            log.warning("hermes.disabled agent=%s provider=%s", self.agent_name, self._gateway.provider)
            return
        if HERMES_AVAILABLE and _HermesAIAgent is not None:
            try:
                self._hermes = _HermesAIAgent(
                    model=self._gateway.model_for(self.tier),
                    quiet_mode=True,
                    ephemeral_system_prompt=self.system_prompt,
                    skip_context_files=False,
                    skip_memory=False,
                    max_iterations=self.max_iterations,
                    base_url=self._gateway.openai_base_url(),
                    api_key=self._gateway.api_key,
                    platform="forgemind",
                )
                log.info(
                    "hermes.ready agent=%s provider=%s model=%s",
                    self.agent_name,
                    self._gateway.provider,
                    self._gateway.model_for(self.tier),
                )
            except Exception:  # noqa: BLE001
                log.exception("hermes.init_failed agent=%s; falling back to LiteAgent", self.agent_name)
                self._hermes = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        task: str,
        *,
        history: list[dict[str, Any]] | None = None,
        task_id: str | None = None,
    ) -> AgentActivity:
        self._configure_backend()
        activity = AgentActivity(
            agent_name=self.agent_name,
            task=task,
            tier=self.tier.value,
        )
        t0 = time.perf_counter()
        try:
            if self._hermes is not None:
                await self._run_hermes(task, history or [], task_id, activity)
            else:
                await self._run_lite(task, history or [], activity)
            activity.status = "completed"
        except Exception as exc:  # noqa: BLE001
            activity.status = "error"
            activity.error = repr(exc)
            log.exception("hermes.run_failed agent=%s", self.agent_name)
        finally:
            activity.ended_at = datetime.now(timezone.utc)
            await _LEDGER.record(activity)
            log.info(
                "hermes.run_done agent=%s status=%s ms=%d",
                self.agent_name,
                activity.status,
                int((time.perf_counter() - t0) * 1000),
            )
        return activity

    # ------------------------------------------------------------------
    # Backends
    # ------------------------------------------------------------------

    async def _run_hermes(
        self,
        task: str,
        history: list[dict[str, Any]],
        task_id: str | None,
        activity: AgentActivity,
    ) -> None:
        """Real Hermes path. Hermes drives the tool loop itself."""
        assert self._hermes is not None
        # Hermes is blocking; run in executor.
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._hermes.run_conversation(
                user_message=task,
                conversation_history=history or None,
                task_id=task_id or activity.activity_id,
            ),
        )
        activity.result = result.get("final_response") or ""
        activity.messages = result.get("messages") or []
        # Hermes doesn't expose token usage uniformly; we approximate
        # from message lengths so the UI has something useful.
        activity.tokens_in = sum(len(str(m.get("content", ""))) for m in activity.messages if m.get("role") == "user") // 4
        activity.tokens_out = len(activity.result) // 4
        activity.model_used = self._gateway.model_for(self.tier)

    async def _run_lite(
        self,
        task: str,
        history: list[dict[str, Any]],
        activity: AgentActivity,
    ) -> None:
        """Fallback agent loop using TrueFoundryGateway directly.

        Used when the Hermes package isn't installed. Implements a basic
        tool-calling ReAct loop so behavior is comparable.
        """
        messages: list[dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": task})

        tool_schemas = self.tools.openai_schema() if self.tools else None

        for _ in range(self.max_iterations):
            try:
                resp = await self._gateway.chat(
                    messages=messages,
                    tier=self.tier,
                    tools=tool_schemas,
                    temperature=0.2,
                    max_tokens=1024,
                )
            except GatewayError as exc:
                activity.error = f"gateway: {exc}"
                raise

            activity.tokens_in += resp.usage.prompt_tokens
            activity.tokens_out += resp.usage.completion_tokens
            activity.cost_usd += resp.usage.cost_usd
            activity.tfy_trace_id = resp.usage.trace_id or activity.tfy_trace_id
            activity.model_used = resp.usage.model

            if not resp.tool_calls:
                activity.result = resp.content
                messages.append({"role": "assistant", "content": resp.content})
                activity.messages = messages
                return

            messages.append({"role": "assistant", "content": resp.content, "tool_calls": resp.tool_calls})
            for tc in resp.tool_calls:
                name = tc.get("function", {}).get("name", "")
                raw_args = tc.get("function", {}).get("arguments", "{}")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                except json.JSONDecodeError:
                    args = {}
                tool = self.tools.get(name)
                if tool is None:
                    result = f"ERROR: unknown tool {name}"
                else:
                    try:
                        out = tool.handler(**args)
                        if asyncio.iscoroutine(out):
                            out = await out
                        result = out if isinstance(out, str) else json.dumps(out, default=str)
                    except Exception as exc:  # noqa: BLE001
                        result = f"ERROR: {exc!r}"
                activity.tool_calls.append({"tool": name, "args": args, "result_preview": result[:300]})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "name": name,
                    "content": result,
                })

        activity.result = "[max iterations reached]"
        activity.messages = messages


# ---------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------


def new_runtime(
    agent_name: str,
    system_prompt: str,
    *,
    tier: ModelTier = ModelTier.POWERFUL,
    tools: ToolRegistry | None = None,
    max_iterations: int = 12,
) -> HermesAgentRuntime:
    return HermesAgentRuntime(
        agent_name=agent_name,
        system_prompt=system_prompt,
        tier=tier,
        tools=tools,
        max_iterations=max_iterations,
    )
