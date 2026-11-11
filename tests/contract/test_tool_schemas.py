"""MCP tool-schema snapshots (A7). Fails when any tool's name, description, input/output schema or
annotations change without the snapshot being regenerated on purpose:

    UPDATE_SNAPSHOTS=1 uv run pytest tests/contract    # then review and commit the snapshot diff
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from mcp_servers.marketplace.server import build_server as build_marketplace
from mcp_servers.portfolio.server import build_server as build_portfolio
from mcp_servers.portfolio.tools import PortfolioStore
from mcp_servers.workspace.server import WorkspaceStore
from mcp_servers.workspace.server import build_server as build_workspace

SNAP_DIR = Path(__file__).parent / "snapshots"


def _servers(tmp_path, adapter_factory):
    return {
        "marketplace": build_marketplace(adapter_factory, audit_path=str(tmp_path / "a.jsonl")),
        "portfolio": build_portfolio(PortfolioStore(variant="bm25")),
        "workspace": build_workspace(WorkspaceStore(tmp_path / "ws")),
    }


async def _surface(server) -> dict:
    async with connect(server._mcp_server) as s:
        tools = (await s.list_tools()).tools
        templates = (await s.list_resource_templates()).resourceTemplates
        resources = (await s.list_resources()).resources
        prompts = (await s.list_prompts()).prompts
    return {
        "tools": {t.name: {"description": t.description, "inputSchema": t.inputSchema, "outputSchema": t.outputSchema,
                           "annotations": t.annotations.model_dump(exclude_none=True) if t.annotations else None}
                  for t in sorted(tools, key=lambda t: t.name)},
        "resource_templates": sorted(r.uriTemplate for r in templates),
        "resources": sorted(str(r.uri) for r in resources),
        "prompts": {p.name: [a.name for a in (p.arguments or [])] for p in sorted(prompts, key=lambda p: p.name)},
    }


@pytest.mark.parametrize("name", ["marketplace", "portfolio", "workspace"])
async def test_tool_schemas_match_snapshot(name, tmp_path, adapter_factory, audit_dir):
    surface = await _surface(_servers(tmp_path, adapter_factory)[name])
    snap = SNAP_DIR / f"{name}.json"
    text = json.dumps(surface, indent=2, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_SNAPSHOTS") == "1" or not snap.exists():
        SNAP_DIR.mkdir(exist_ok=True)
        snap.write_text(text, encoding="utf-8")
        if os.environ.get("UPDATE_SNAPSHOTS") != "1":
            pytest.fail(f"snapshot {snap.name} did not exist; created it. Review and commit it, then re-run.")
        return
    expected = json.loads(snap.read_text(encoding="utf-8"))
    if expected != surface:
        changed = sorted(set(expected["tools"]) ^ set(surface["tools"])) or [
            n for n in surface["tools"] if expected["tools"].get(n) != surface["tools"][n]]
        pytest.fail(f"MCP surface of '{name}' changed (tools: {changed}). If intended, run "
                    f"UPDATE_SNAPSHOTS=1 uv run pytest tests/contract and commit the snapshot.")
