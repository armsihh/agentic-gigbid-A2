"""Conversation graph against a real GigSim client thread (in-process), scripted fake models."""
from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent.graphs.conversation_graph import build_conversation_graph
from agent.nodes import common as node_common
from agent.nodes.common import Deps
from agent.testing import FakeModels, LocalToolbox
from mcp_servers.marketplace.server import build_server as build_marketplace
from mcp_servers.portfolio.server import build_server as build_portfolio
from mcp_servers.portfolio.tools import PortfolioStore
from mcp_servers.workspace.server import WorkspaceStore
from mcp_servers.workspace.server import build_server as build_workspace
from rag.ingest.loaders import load_profile

LETTER = ("Hi - I built a support ticket triage classifier for a UK SaaS company that routed 81% of tickets "
          "automatically at 94% precision using Python and scikit-learn; happy to start with a baseline.")


def client_thread(gigsim, want_intent: str | None = None) -> dict:
    """Submit proposals in-process until a client replies; return a thread (optionally with a given intent)."""
    acc = gigsim.account("ai_ml")
    acc.connects = 10_000
    gigsim.policy["proposals"]["max_open_proposals"] = 1000
    jobs = [j for j in gigsim.jobs.values() if j["status"] == "open" and j["category"] == "ai_ml"][:60]
    for j in jobs:
        try:
            p = gigsim.create_draft("ai_ml", {"job_id": j["job_id"], "cover_letter": LETTER,
                                              "bid_amount": j.get("budget") or j.get("hourly_high") or 30})
            gigsim.submit("ai_ml", p["proposal_id"], {"confirm": True})
        except Exception:  # noqa: BLE001, S112 - some jobs reject (already applied etc.)
            continue
    gigsim.fast_forward()
    gigsim.fast_forward()
    threads = [t for t in acc.threads.values() if want_intent is None or t["intent"] == want_intent]
    if not threads:
        pytest.skip(f"no client thread with intent {want_intent}")
    return threads[0]


@pytest.fixture
def toolbox(adapter_factory, audit_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_PERSONA", "ai_ml")
    return LocalToolbox({"marketplace": build_marketplace(adapter_factory, audit_path=str(audit_dir / "m.jsonl")),
                         "portfolio": build_portfolio(PortfolioStore(variant="bm25")),
                         "workspace": build_workspace(WorkspaceStore(tmp_path / "ws"))})


def deps_for(toolbox, scripts):
    profile = load_profile(node_common.ROOT / "data" / "personas" / "ai_ml")
    return Deps(toolbox=toolbox, profile=profile, model_factory=FakeModels(scripts))


async def test_interview_request_offers_slots_and_sends_after_approval(toolbox, gigsim):
    th = client_thread(gigsim)
    gigsim.account("ai_ml").threads[th["thread_id"]]["messages"].append(
        {"message_id": "m-call", "sender": "client", "text": "Can we do a quick call this week?", "at": "now"})
    reply ={"text": "Thanks! I'm free tomorrow at 10:00 or Thursday at 14:00 (PKT). Which works for you?",
             "proposed_slot_starts": []}
    deps = deps_for(toolbox, {"intent": [{"intent": "interview_request", "reason": "asks for a call"}],
                              "client_liaison": [reply]})
    g = build_conversation_graph(deps, InMemorySaver())
    cfg = {"configurable": {"thread_id": "conv-1"}}
    out = await g.ainvoke({"thread_id": "conv-1", "user_id": "u", "marketplace_thread_id": th["thread_id"]}, cfg)
    payload = out["__interrupt__"][0].value
    assert payload["kind"] == "message_approval" and payload["slots"]
    assert toolbox.count("send_message") == 1                     # only the dry run so far
    out = await g.ainvoke(Command(resume={"action": "approve"}), cfg)
    assert out["status"] == "sent"
    msgs = gigsim.account("ai_ml").threads[th["thread_id"]]["messages"]
    assert msgs[-1]["sender"] == "freelancer" and "Thursday" in msgs[-1]["text"]


async def test_scam_signal_is_detected_by_rule_without_a_model(toolbox, gigsim):
    th = client_thread(gigsim)
    gigsim.account("ai_ml").threads[th["thread_id"]]["messages"].append(
        {"message_id": "m-x", "sender": "client", "text": "Add me on Telegram @hr_123 and send your WhatsApp.", "at": "now"})
    reply = {"text": "Thanks for reaching out. I prefer to keep our conversation here on the platform.",
             "proposed_slot_starts": []}
    models = FakeModels({"intent": [RuntimeError("model must not be called")], "client_liaison": [reply]})
    deps = deps_for(toolbox, {})
    deps.model_factory = models
    g = build_conversation_graph(deps, InMemorySaver())
    cfg = {"configurable": {"thread_id": "conv-2"}}
    out = await g.ainvoke({"thread_id": "conv-2", "user_id": "u", "marketplace_thread_id": th["thread_id"]}, cfg)
    assert out["intent"] == "scam_signal" and models.calls["intent"] == 0
    assert "__interrupt__" in out   # the polite decline still needs approval


async def test_reply_with_contact_details_is_redacted_or_blocked(toolbox, gigsim):
    th = client_thread(gigsim)
    bad = {"text": "Sure, let's continue outside Upwork, email me at me@example.com.", "proposed_slot_starts": []}
    deps = deps_for(toolbox, {"intent": [{"intent": "question", "reason": "x"}], "client_liaison": [bad]})
    g = build_conversation_graph(deps, InMemorySaver())
    cfg = {"configurable": {"thread_id": "conv-3"}}
    out = await g.ainvoke({"thread_id": "conv-3", "user_id": "u", "marketplace_thread_id": th["thread_id"]}, cfg)
    assert out["status"] == "blocked" and toolbox.count("send_message") == 0
