"""Bearer-token auth on the Streamable HTTP endpoint (A2): no token -> 401, read-only token cannot write."""
from __future__ import annotations

import socket
import threading
import time

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from mcp_servers.marketplace.server import build_server


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def http_server(adapter_factory, audit_dir):
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    srv = build_server(adapter_factory, audit_path=str(audit_dir / "h.jsonl"), http_url=url,
                       token_spec="reader-tok:alice:marketplace:read,writer-tok:bob:marketplace:read+marketplace:write")
    server = uvicorn.Server(uvicorn.Config(srv.streamable_http_app(), host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield url + "/mcp"
    server.should_exit = True
    t.join(timeout=5)


def test_no_token_is_rejected(http_server):
    r = httpx.post(http_server, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                   headers={"Accept": "application/json, text/event-stream"})
    assert r.status_code == 401


async def _call(url: str, token: str, tool: str, args: dict):
    headers = {"Authorization": f"Bearer {token}", "x-trace-id": "tr-test-123"}
    async with streamablehttp_client(url, headers=headers) as (r, w, _), ClientSession(r, w) as s:
        await s.initialize()
        return await s.call_tool(tool, args)


async def test_scopes_enforced_per_token(http_server, audit_dir):
    ok = await _call(http_server, "reader-tok", "get_connects_balance", {})
    assert not ok.isError
    denied = await _call(http_server, "reader-tok", "submit_proposal", {"proposal_id": "p", "idempotency_key": "key-00000001"})
    assert denied.isError and "forbidden" in denied.content[0].text
    from mcp_servers.common import AuditLog
    recs = AuditLog(audit_dir / "h.jsonl").read()
    assert {r["user"] for r in recs} == {"alice"}
    assert all(r["trace_id"] == "tr-test-123" for r in recs)  # trace id propagated from the HTTP header
