"""Test doubles for running the graphs without network or API keys.

LocalToolbox: calls the REAL MCP server tool functions in-process (same schemas, validation, audit, adapters),
              enforcing the same per-agent allowlists as agent/mcp_client.Toolbox.
FakeModels:   scripted structured outputs per node, with fake token usage (deterministic graph tests, CI).
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage
from mcp.server.fastmcp.exceptions import ToolError

from agent.mcp_client import ServiceDegraded, health, load_config


class LocalToolbox:
    def __init__(self, servers: dict[str, Any], allowlists: dict | None = None):
        self.servers = servers                      # name -> FastMCP instance
        self.allowlists = allowlists or load_config()["tool_allowlists"]
        self.calls: list[tuple[str, str, dict]] = []

    async def call(self, agent: str, tool: str, args: dict[str, Any]) -> Any:
        server = next((s for s, names in (self.allowlists.get(agent) or {}).items() if tool in names), None)
        if server is None:
            raise PermissionError(f"agent {agent!r} is not allowed to call {tool!r}")
        self.calls.append((agent, tool, args))
        try:
            res = await self.servers[server].call_tool(tool, args)
        except ToolError as e:
            if "retryable" in str(e) and "unavailable" in str(e):
                health.fail(server, str(e))
                raise ServiceDegraded(server, str(e)) from e
            raise
        health.ok(server)
        return res[1] if isinstance(res, tuple) else res

    def count(self, tool: str) -> int:
        return sum(1 for _, t, _a in self.calls if t == tool)


class _Structured:
    def __init__(self, owner: FakeModels, node: str, schema):
        self.owner, self.node, self.schema = owner, node, schema

    async def ainvoke(self, messages):
        self.owner.prompts[self.node].append(messages)
        script = self.owner.scripts[self.node]
        i = self.owner.calls[self.node]
        self.owner.calls[self.node] += 1
        item = script[min(i, len(script) - 1)]
        if callable(item):
            item = item(messages)
        if isinstance(item, Exception):
            raise item
        parsed = item if isinstance(item, self.schema) else self.schema.model_validate(item)
        return {"raw": AIMessage(content="", usage_metadata={"input_tokens": 400, "output_tokens": 150,
                                                            "total_tokens": 550}),
                "parsed": parsed, "parsing_error": None}


class FakeModels:
    """factory(node) -> fake chat model. scripts[node] = list of outputs (dict / model / callable / Exception);
    the last item repeats."""
    def __init__(self, scripts: dict[str, list[Any]]):
        self.scripts = scripts
        self.calls: dict[str, int] = defaultdict(int)
        self.prompts: dict[str, list] = defaultdict(list)

    def __call__(self, node: str):
        owner = self

        class _M:
            def with_structured_output(self, schema, include_raw=False):
                return _Structured(owner, node, schema)
        return _M()


def fixed(value: Any) -> Callable[[Any], Any]:
    return lambda _m: value
