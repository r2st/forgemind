"""TrueFoundry MCP Gateway client.

Companion to `tfy_gateway.py`. Where the AI Gateway centralises *LLM*
calls, the MCP Gateway centralises *tool* calls — every Model Context
Protocol server (GitHub, Sentry, Atlassian, web search, code exec,
DeepWiki, etc.) is proxied behind one URL with one auth scheme.

This module exposes a `TrueFoundryMCPGateway` that:

  * Lists the MCP servers registered in the workspace.
  * Lists the tools each server exposes.
  * Calls a tool by (server, tool_name, args).
  * Builds a `ToolRegistry` compatible with the existing Hermes runtime,
    so any agent can be given "real-world" tools (web search, Github
    issue search, Sentry events) alongside the ForgeMind-internal ones.

URL pattern discovered from the live workspace:
    https://gateway.truefoundry.ai/truefoundry/mcp/{server_id}/server

Auth: a Bearer Personal Access Token. Per-server passthrough headers
(GitHub PAT, Slack token, etc.) can be supplied via the `x-tfy-mcp-headers`
header — the gateway forwards them to the upstream MCP server.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx

from .config import get_settings
from .hermes_runtime import Tool, ToolRegistry

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Registry / discovery
# ---------------------------------------------------------------------


@dataclass
class MCPServerInfo:
    server_id: str
    name: str
    description: str
    url: str
    auth_type: str            # "none" | "bearer" | "oauth2" | "passthrough"
    server_type: str          # "remote" | "stdio" | "virtual" | "chained"


class TrueFoundryMCPGateway:
    """Tiny client for the TrueFoundry MCP Gateway.

    Most ForgeMind code only needs `build_tool_registry()` — that yields
    a ToolRegistry the Hermes runtime can consume directly.
    """

    def __init__(
        self,
        control_plane_url: str | None = None,
        gateway_url: str | None = None,
        api_key: str | None = None,
        workspace: str | None = None,
    ) -> None:
        s = get_settings()
        self.control_plane_url = (
            control_plane_url or s.tfy_control_plane_url
        ).rstrip("/")
        self.gateway_url = (gateway_url or s.tfy_gateway_base_url).rstrip("/")
        self.api_key = api_key or s.tfy_gateway_api_key
        # TrueFoundry MCP gateway always namespaces under the tenant/account
        # name. For the hosted product this is `truefoundry`.
        self.workspace = workspace or s.tfy_mcp_namespace
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Discovery (control plane)
    # ------------------------------------------------------------------

    async def list_servers(self) -> list[MCPServerInfo]:
        """List MCP servers visible to this PAT."""
        url = f"{self.control_plane_url}/api/svc/v1/llm-gateway/mcp-servers"
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url, headers={"Authorization": f"Bearer {self.api_key}"})
            r.raise_for_status()
        out: list[MCPServerInfo] = []
        for s in r.json().get("servers", []):
            m = s.get("manifest", {}) or {}
            stype_raw = m.get("type", "")
            stype = stype_raw.replace("mcp-server/", "")
            auth = ((m.get("auth_data") or {}).get("type") or "none").lower()
            out.append(
                MCPServerInfo(
                    server_id=s.get("name") or s.get("id"),
                    name=s.get("name") or "",
                    description=(m.get("description") or "")[:200],
                    url=self.server_url(s.get("name") or s.get("id")),
                    auth_type=auth,
                    server_type=stype,
                )
            )
        return out

    def server_url(self, server_id: str) -> str:
        return f"{self.gateway_url}/{self.workspace}/mcp/{server_id}/server"

    # ------------------------------------------------------------------
    # Per-server tool listing + invocation
    # ------------------------------------------------------------------

    async def list_tools(self, server_id: str) -> list[dict[str, Any]]:
        """Return the tools that `server_id` exposes."""
        # Lazy-import fastmcp to keep it optional.
        from fastmcp import Client
        from fastmcp.client.transports import StreamableHttpTransport

        transport = StreamableHttpTransport(
            url=self.server_url(server_id), auth=self.api_key
        )
        async with Client(transport=transport) as client:
            tools = await client.list_tools()
        return [
            {
                "name": t.name,
                "description": (t.description or "").strip(),
                "parameters": getattr(t, "inputSchema", {}) or {"type": "object", "properties": {}},
            }
            for t in tools
        ]

    async def call_tool(
        self,
        server_id: str,
        tool_name: str,
        args: dict[str, Any] | None = None,
        passthrough_headers: dict[str, str] | None = None,
    ) -> Any:
        """Invoke a tool on a remote MCP server through the gateway."""
        from fastmcp import Client
        from fastmcp.client.transports import StreamableHttpTransport

        headers: dict[str, str] = {}
        if passthrough_headers:
            headers["x-tfy-mcp-headers"] = json.dumps(passthrough_headers)
        transport = StreamableHttpTransport(
            url=self.server_url(server_id),
            auth=self.api_key,
            headers=headers or None,
        )
        async with Client(transport=transport) as client:
            return await client.call_tool(tool_name, args or {})

    # ------------------------------------------------------------------
    # Tool-registry bridge
    # ------------------------------------------------------------------

    async def build_tool_registry(
        self,
        servers: list[str] | None = None,
        *,
        prefix_with_server: bool = True,
    ) -> ToolRegistry:
        """Discover tools across servers and wrap them as Hermes tools.

        Useful in agent constructors:

            mcp = get_mcp_gateway()
            tools = await mcp.build_tool_registry(servers=["common-tools", "deepwiki0"])
            agent = new_runtime("research-agent", PROMPT, tools=tools)

        With `prefix_with_server=True` each tool name becomes
        `<server>__<tool>` so collisions across servers don't clash.
        """
        reg = ToolRegistry()
        wanted = servers or [s.server_id for s in await self.list_servers()]
        for sid in wanted:
            try:
                tool_specs = await self.list_tools(sid)
            except Exception as exc:  # noqa: BLE001
                log.warning("mcp_gateway.list_tools_failed server=%s err=%s", sid, exc)
                continue
            for spec in tool_specs:
                hermes_name = f"{sid}__{spec['name']}" if prefix_with_server else spec["name"]
                reg.add(
                    Tool(
                        name=hermes_name,
                        description=f"[via TFY MCP/{sid}] {spec['description']}",
                        parameters=spec["parameters"],
                        handler=self._make_handler(sid, spec["name"]),
                    )
                )
        return reg

    def _make_handler(self, server_id: str, tool_name: str):
        async def _h(**kwargs: Any) -> Any:
            try:
                return await self.call_tool(server_id, tool_name, kwargs)
            except Exception as exc:  # noqa: BLE001
                return {"error": str(exc), "server": server_id, "tool": tool_name}

        return _h


@lru_cache(maxsize=1)
def get_mcp_gateway() -> TrueFoundryMCPGateway:
    """Process-wide singleton MCP gateway client."""
    return TrueFoundryMCPGateway()
