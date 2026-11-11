"""Marketplace MCP server through an in-memory MCP client session (A7).

Sessions are opened inside each test (`async with`), not in a yield fixture: the in-memory transport
uses anyio cancel scopes that must be entered and exited in the same task.
"""
from __future__ import annotations

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from mcp_servers.common import AuditLog
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
from mcp_servers.marketplace.server import build_server

LETTER = ("Hi - you need a reliable classifier. I built a support ticket triage model for a UK SaaS company that "
          "routed 81% of tickets automatically at 94% precision, with a fallback for low-confidence cases.")


@pytest.fixture
def server(adapter_factory, audit_dir):
    return build_server(adapter_factory, audit_path=str(audit_dir / "m.jsonl"))._mcp_server


async def first_fixed_job(s):
    r = await s.call_tool("search_jobs", {"category": "ai_ml", "payment_type": "fixed", "limit": 50})
    for j in r.structuredContent["items"]:
        if j["budget"] and not j["client_id"].startswith("cl-syn"):
            return j
    raise AssertionError("no fixed job")


async def test_tools_have_schemas_and_correct_annotations(server):
    async with connect(server) as s:
        tools = {t.name: t for t in (await s.list_tools()).tools}
    for n in ["search_jobs", "get_job", "get_client_history", "get_connects_balance", "list_messages"]:
        assert tools[n].annotations.readOnlyHint is True and tools[n].outputSchema
    for n in ["create_proposal_draft", "submit_proposal", "send_message"]:
        t = tools[n]
        assert t.annotations.readOnlyHint is False and t.annotations.idempotentHint is True
        assert "idempotency_key" in t.inputSchema["required"] and "dry_run" in t.inputSchema["properties"]
    assert tools["submit_proposal"].annotations.destructiveHint is True
    assert tools["create_proposal_draft"].annotations.destructiveHint is False


async def test_input_constraints_are_enforced(server):
    async with connect(server) as s:
        r = await s.call_tool("create_proposal_draft", {"job_id": "x", "cover_letter": "too short",
                                                        "bid_amount": -5, "idempotency_key": "k"})
    assert r.isError and "validation error" in r.content[0].text


async def test_dry_run_shows_cost_and_changes_nothing(server):
    async with connect(server) as s:
        j = await first_fixed_job(s)
        args = {"job_id": j["job_id"], "cover_letter": LETTER, "bid_amount": j["budget"],
                "idempotency_key": "draft-0001", "dry_run": True}
        prev = (await s.call_tool("create_proposal_draft", args)).structuredContent["preview"]
        props = (await s.call_tool("list_proposals", {})).structuredContent["proposals"]
    assert prev["connects_cost"] == j["connects_cost"] and prev["would_send"]["cover_letter"] == LETTER
    assert props == []


async def test_retried_submit_spends_connects_exactly_once(server):
    async with connect(server) as s:
        j = await first_fixed_job(s)
        bal0 = (await s.call_tool("get_connects_balance", {})).structuredContent["balance"]
        d = await s.call_tool("create_proposal_draft", {"job_id": j["job_id"], "cover_letter": LETTER,
                                                        "bid_amount": j["budget"], "idempotency_key": "draft-0002"})
        pid = d.structuredContent["proposal"]["proposal_id"]
        results = [await s.call_tool("submit_proposal", {"proposal_id": pid, "idempotency_key": "submit-0002"})
                   for _ in range(3)]
        bal1 = (await s.call_tool("get_connects_balance", {})).structuredContent["balance"]
    assert all(not r.isError for r in results)
    assert {r.structuredContent["proposal"]["status"] for r in results} == {"submitted"}
    assert bal0 - bal1 == j["connects_cost"]


async def test_marketplace_policy_violation_is_a_typed_error(server):
    async with connect(server) as s:
        j = await first_fixed_job(s)
        r = await s.call_tool("create_proposal_draft", {
            "job_id": j["job_id"], "cover_letter": LETTER + " WhatsApp me on +92 300 1234567.", "bid_amount": 100,
            "idempotency_key": "draft-0003"})
    assert r.isError and "[policy_violation]" in r.content[0].text


async def test_audit_log_records_every_call_with_trace_and_masks_pii(server, audit_dir):
    async with connect(server) as s:
        j = await first_fixed_job(s)
        await s.call_tool("create_proposal_draft", {
            "job_id": j["job_id"], "cover_letter": LETTER + " email: me@example.com", "bid_amount": 100,
            "idempotency_key": "draft-0004"})
    recs = AuditLog(audit_dir / "m.jsonl").read()
    assert recs and all(r["trace_id"] and r["user"] for r in recs)
    blob = str(recs)
    assert "me@example.com" not in blob and "[EMAIL]" in blob
    assert recs[-1]["tool"] == "create_proposal_draft" and recs[-1]["ok"] is False


async def test_marketplace_down_is_a_retryable_error(audit_dir):
    def dead(_u):
        return GigSimAdapter(base_url="http://127.0.0.1:9", max_attempts=2, backoff_base_s=0.001,
                             transport=httpx.AsyncHTTPTransport(retries=0))
    async with connect(build_server(dead, audit_path=str(audit_dir / "d.jsonl"))._mcp_server) as s:
        r = await s.call_tool("search_jobs", {"limit": 1})
    assert r.isError and "[marketplace_unavailable retryable]" in r.content[0].text
