"""GigSim adapter behaviour (retries, error mapping) and the port contract both adapters satisfy."""
from __future__ import annotations

import httpx
import pytest

from agent.marketplace_port import (
    MarketplacePort,
    NotFound,
    PolicyViolation,
    ProposalDraftRequest,
    RateLimited,
)
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
from mcp_servers.marketplace.adapters.upwork_live import UpworkLiveAdapter, _job_summary, _proposal


async def test_gigsim_adapter_survives_transient_errors(adapter_factory, gigsim):
    gigsim.cfg["faults"]["error_rate"] = 0.4
    a = adapter_factory(max_attempts=8)
    pages = [await a.search_jobs(category="web_dev", limit=3) for _ in range(10)]
    assert all(p.total > 0 for p in pages)


async def test_gigsim_adapter_maps_errors(adapter_factory):
    a = adapter_factory()
    with pytest.raises(NotFound):
        await a.get_job("does-not-exist")
    page = await a.search_jobs(category="ai_ml", limit=1)
    with pytest.raises(PolicyViolation):
        await a.create_proposal_draft(ProposalDraftRequest(job_id=page.items[0].job_id, bid_amount=10,
                                      cover_letter="x" * 120 + " contact me at a@b.co"), "idem-key-1")


async def test_rate_limit_respected_then_surfaces(gigsim):
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": {"code": "rate_limited", "message": "slow"}})
    a = GigSimAdapter(base_url="http://x", transport=httpx.MockTransport(handler), max_attempts=3, backoff_base_s=0.001)
    with pytest.raises(RateLimited):
        await a.get_connects_balance()
    assert calls["n"] == 3  # bounded


def test_both_adapters_implement_the_port():
    assert isinstance(GigSimAdapter(base_url="http://x"), MarketplacePort)
    assert isinstance(UpworkLiveAdapter(client=object()), MarketplacePort)


def test_upwork_mapping_is_tolerant_to_field_names():
    j = _job_summary({"id": "~01ab", "title": "Build a RAG bot", "description": "x" * 500,
                      "hourlyBudget": {"min": 30, "max": 60}, "skills": [{"prettyName": "Python"}],
                      "connectPrice": 16, "client": {"id": "c1"}})
    assert j.payment_type == "hourly" and j.hourly_high == 60 and j.skills == ["Python"] and j.connects_cost == 16
    assert j.client_id == "c1" and len(j.snippet) == 280
    assert _proposal({"id": "p1", "status": "Archived", "coverLetter": "hi", "amount": 50}).status == "lost"


async def test_upwork_submit_never_auto_confirms():
    class FakeSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def list_tools(self):
            from mcp.types import ListToolsResult, Tool
            return ListToolsResult(tools=[Tool(name="get_proposal", inputSchema={"type": "object"})])
        async def call_tool(self, name, args):
            from mcp.types import CallToolResult
            assert name == "get_proposal"
            return CallToolResult(content=[], structuredContent={"id": "p1", "status": "draft", "coverLetter": "hi",
                                                                 "amount": 40})

    class FakeClient:
        def session(self, _name): return FakeSession()

    a = UpworkLiveAdapter(client=FakeClient())
    prev = await a.submit_proposal("p1", "key-12345678", dry_run=True)
    assert "upwork.com" in prev.would_send["note"]
    p = await a.submit_proposal("p1", "key-12345678")
    assert p.status == "draft"  # still a draft: the human confirms on upwork.com
