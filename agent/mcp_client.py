"""MultiServerMCPClient setup + per-agent tool allowlists + client discipline (A6).

    toolbox = Toolbox.from_config()
    tools = await toolbox.tools_for("fit_matcher")   # only search_evidence, get_case_study, list_skills

Client discipline, implemented as a tool-call interceptor:
  * per-call timeout, bounded retries with exponential backoff + jitter for retryable failures
    (transport errors, or server errors tagged "[... retryable]")
  * the current trace id is sent as `x-trace-id` on every HTTP call (E3)
  * a health registry records each server's state; when the marketplace is down, calls raise
    `ServiceDegraded`, which the graph turns into a queued "waiting for marketplace" state and the
    UI shows as a banner. A later successful call marks it healthy again (recovery).
"""
from __future__ import annotations

import asyncio
import contextvars
import os
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from mcp.types import CallToolResult

ROOT = Path(__file__).resolve().parents[1]
current_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)


class ServiceDegraded(RuntimeError):
    """A required MCP server is unreachable after bounded retries. Work should be queued, not failed."""

    def __init__(self, server: str, reason: str):
        super().__init__(f"{server} unavailable: {reason}")
        self.server, self.reason = server, reason


@dataclass
class ServerHealth:
    status: str = "unknown"          # ok | degraded | unknown
    last_error: str | None = None
    since: float = field(default_factory=time.time)
    consecutive_failures: int = 0


class HealthRegistry:
    def __init__(self) -> None:
        self.servers: dict[str, ServerHealth] = {}

    def ok(self, server: str) -> None:
        h = self.servers.setdefault(server, ServerHealth())
        if h.status != "ok":
            h.status, h.since, h.last_error = "ok", time.time(), None
        h.consecutive_failures = 0

    def fail(self, server: str, err: str) -> None:
        h = self.servers.setdefault(server, ServerHealth())
        h.consecutive_failures += 1
        h.last_error = err
        if h.status != "degraded":
            h.status, h.since = "degraded", time.time()

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {k: vars(v).copy() for k, v in self.servers.items()}


health = HealthRegistry()


def _result_text(r: Any) -> str:
    if isinstance(r, CallToolResult):
        return " ".join(getattr(c, "text", "") for c in r.content)
    return str(getattr(r, "content", r))


class ResilienceInterceptor:
    def __init__(self, timeout_s: float = 20, max_attempts: int = 3, backoff_base_s: float = 0.5):
        self.timeout_s, self.max_attempts, self.backoff_base_s = timeout_s, max_attempts, backoff_base_s

    async def __call__(self, request: MCPToolCallRequest, handler):
        trace = current_trace_id.get()
        if trace:
            request = request.override(headers={**(request.headers or {}), "x-trace-id": trace})
        last_err = "unknown"
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = await asyncio.wait_for(handler(request), timeout=self.timeout_s)
            except (TimeoutError, OSError, ConnectionError) as e:
                last_err = f"{type(e).__name__}"
            except Exception as e:
                if "retryable" in str(e) or _looks_like_transport(e):
                    last_err = f"{type(e).__name__}: {str(e)[:120]}"
                else:
                    raise
            else:
                text = _result_text(result)
                is_error = isinstance(result, CallToolResult) and result.isError
                if is_error and "retryable" in text:
                    last_err = text[:200]
                    if "marketplace_unavailable" not in text:  # e.g. rate limit: server is up
                        health.ok(request.server_name)
                else:
                    health.ok(request.server_name)
                    return result
            if attempt < self.max_attempts:
                await asyncio.sleep(random.uniform(0, self.backoff_base_s * 2 ** (attempt - 1)))
        health.fail(request.server_name, last_err)
        raise ServiceDegraded(request.server_name, last_err)


def _looks_like_transport(e: BaseException) -> bool:
    names = {type(x).__name__ for x in _walk(e)}
    return bool(names & {"ConnectError", "ReadTimeout", "ConnectTimeout", "RemoteProtocolError", "ClosedResourceError",
                         "BrokenResourceError", "McpError", "EndOfStream"})


def _walk(e: BaseException):
    yield e
    for sub in getattr(e, "exceptions", []) or []:
        yield from _walk(sub)
    if e.__cause__:
        yield from _walk(e.__cause__)


def load_config() -> dict:
    return yaml.safe_load((ROOT / "agent" / "config.yaml").read_text())


def build_connections(cfg: dict, servers: list[str] | None = None, env: dict[str, str] | None = None) -> dict:
    """stdio by default (spawned with this interpreter); streamable_http when <NAME>_MCP_URL is set."""
    env = {**os.environ, **(env or {})}
    conns: dict[str, dict] = {}
    for name, sc in cfg["mcp_servers"].items():
        if servers is not None and name not in servers:
            continue
        url = env.get(sc.get("url_env", ""), "") or sc.get("url")
        if sc.get("transport") == "streamable_http" or url:
            if not url:
                continue
            headers = {}
            token = env.get(sc.get("token_env", ""), "") or env.get(f"{name.upper()}_MCP_TOKEN", "")
            if token:
                headers["Authorization"] = f"Bearer {token}"
            elif sc.get("optional"):
                continue  # third-party server without credentials configured: skip
            conns[name] = {"transport": "streamable_http", "url": url, "headers": headers or None}
        else:
            conns[name] = {"transport": "stdio", "command": sys.executable if sc["command"] == "python" else sc["command"],
                           "args": sc["args"], "cwd": str(ROOT), "env": {**env, "PYTHONPATH": str(ROOT)}}
    return conns


class Toolbox:
    def __init__(self, client: MultiServerMCPClient, allowlists: dict[str, dict[str, list[str]]]):
        self.client, self.allowlists = client, allowlists
        self._cache: dict[str, list[BaseTool]] = {}

    @classmethod
    def from_config(cls, cfg: dict | None = None, connections: dict | None = None) -> Toolbox:
        cfg = cfg or load_config()
        mc = cfg.get("mcp_client", {})
        client = MultiServerMCPClient(
            connections if connections is not None else build_connections(cfg),
            tool_interceptors=[ResilienceInterceptor(mc.get("timeout_s", 20), mc.get("max_attempts", 3),
                                                     mc.get("backoff_base_s", 0.5))],
        )
        return cls(client, cfg["tool_allowlists"])

    async def _server_tools(self, server: str) -> list[BaseTool]:
        if server not in self._cache:
            try:
                self._cache[server] = await self.client.get_tools(server_name=server)
                health.ok(server)
            except Exception as e:
                health.fail(server, type(e).__name__)
                raise ServiceDegraded(server, f"cannot list tools: {type(e).__name__}") from e
        return self._cache[server]

    async def tools_for(self, agent: str) -> list[BaseTool]:
        """Only the tools on this agent's allowlist, by exact name. Unknown agents get nothing."""
        allowed = self.allowlists.get(agent) or {}
        out: list[BaseTool] = []
        for server, names in allowed.items():
            if server not in self.client.connections:
                continue
            tools = {t.name: t for t in await self._server_tools(server)}
            missing = [n for n in names if n not in tools]
            if missing:
                raise KeyError(f"allowlist for {agent!r} names unknown {server} tools: {missing}")
            out.extend(tools[n] for n in names)
        return out

    async def call(self, agent: str, tool: str, args: dict[str, Any]) -> Any:
        """Call one allowlisted tool directly (deterministic nodes like Scout and the executor)."""
        tools = {t.name: t for t in await self.tools_for(agent)}
        if tool not in tools:
            raise PermissionError(f"agent {agent!r} is not allowed to call {tool!r}")
        return await tools[tool].ainvoke(args)
