"""Bid graph end to end against in-process GigSim + real MCP tool functions, with scripted fake models (C1-C7).

Covers: parallel analysis -> skip for a scam; full run to interrupt() with a complete approval payload; approve ->
submitted exactly once; critic loop bounded at 2; compliance block; edit -> style memory + compliance re-check;
crash/restart resume from a persistent checkpointer; marketplace outage -> queued; budget -> needs_attention.
"""
from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from agent.graphs.bid_graph import build_bid_graph, initial_state
from agent.memory.store import MemoryManager
from agent.nodes import common as node_common
from agent.nodes.common import Deps
from agent.testing import FakeModels, LocalToolbox
from mcp_servers.marketplace.server import build_server as build_marketplace
from mcp_servers.portfolio.server import build_server as build_portfolio
from mcp_servers.portfolio.tools import PortfolioStore
from rag.ingest.loaders import load_profile
from rag.verify import VerificationReport

GOOD_JOB = "job-a532010879"       # deep learning / NLP, fixed $1000, real client
SCAM_JOB = "job-syn-scam-045"

SPEC = {"job_id": "x", "title": "x", "summary": "Add NLP features to a deep learning model",
        "requirements": [{"text": "deep learning NLP model features", "skills": ["Deep Learning", "NLP"]}],
        "screening_questions": [{"question": "Describe a similar NLP project."}]}
LETTER = ("Hi - you need new NLP features on a deep learning model. For a UK SaaS helpdesk company I fine-tuned a "
          "DistilBERT classifier on 38k historical tickets that routed 81% of tickets automatically at 94% precision. "
          "I would start by reviewing your current model and data, agree the first feature with you, and ship it "
          "behind an evaluation set so every change is measured before release. I am comfortable with Python, "
          "PyTorch and the usual NLP tooling, and I document everything for handover. Could you share a sample of the "
          "data and the feature you want first? Happy to outline a short plan with milestones once I have seen it.")
WRITER = {"cover_letter": LETTER,
          "screening_answers": [{"question": "Describe a similar NLP project.",
                                 "answer": "I built a support ticket triage classifier for a UK SaaS company.",
                                 "evidence_ids": ["ai_ml-cs-ticket-triage#2"]}],
          "claims": [{"text": "fine-tuned a DistilBERT classifier", "evidence_ids": ["ai_ml-cs-ticket-triage#2"]}]}
APPROVE = {"approve": True, "grounding": 5, "personalisation": 4, "length_ok": True}
REVISE = {"approve": False, "grounding": 3, "personalisation": 3, "length_ok": True,
          "issues": ["generic"], "revision_instructions": "Name the client's dataset."}


class PassVerifier:
    """Claim verification stub (the real verifier is unit-tested in tests/unit/test_verify.py)."""
    def verify(self, draft, evidence):
        return VerificationReport(claims=[], unsupported_rate=0.0, cleaned_draft=draft, removed=[])


@pytest.fixture
def world(adapter_factory, audit_dir, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_PERSONA", "ai_ml")
    servers = {"marketplace": build_marketplace(adapter_factory, audit_path=str(audit_dir / "m.jsonl")),
               "portfolio": build_portfolio(PortfolioStore(variant="bm25"))}
    return LocalToolbox(servers)


def make(world, scripts=None, memory=None):
    models = FakeModels(scripts or {"analyst": [SPEC], "writer": [WRITER], "critic": [APPROVE]})
    profile = load_profile(node_common.ROOT / "data" / "personas" / "ai_ml") | {"name": "Sana"}
    deps = Deps(toolbox=world, memory=memory, verifier=PassVerifier(), profile=profile, model_factory=models)
    return deps, models


async def job(world, job_id):
    return (await world.servers["marketplace"].call_tool("get_job", {"job_id": job_id}))[1]


def cfg(tid):
    return {"configurable": {"thread_id": tid}}


async def test_scam_is_skipped_after_parallel_analysis(world):
    deps, models = make(world)
    g = build_bid_graph(deps, InMemorySaver())
    out = await g.ainvoke(initial_state(await job(world, SCAM_JOB), "t-scam", "u", "ai_ml"), cfg("t-scam"))
    assert out["decision"]["action"] == "skip" and out["status"] == "skipped"
    assert {"analyst", "risk_assessor", "fit_matcher"} <= {s["node"] for s in out["trace"]}  # all three ran
    assert models.calls["writer"] == 0                                                      # no wasted tokens
    assert any("risk" in r for r in out["decision"]["reasons"])


async def test_full_run_interrupts_then_submits_exactly_once(world, gigsim):
    deps, _ = make(world)
    g = build_bid_graph(deps, InMemorySaver())
    s0 = initial_state(await job(world, GOOD_JOB), "t-good", "u", "ai_ml")
    out = await g.ainvoke(s0, cfg("t-good"))
    payload = out["__interrupt__"][0].value
    assert payload["kind"] == "proposal_approval"
    for key in ("draft", "claims", "risk_report", "price", "dry_run_preview"):
        assert payload[key], key
    assert payload["dry_run_preview"]["connects_cost"] == 8
    assert world.count("submit_proposal") == 0          # nothing sent before approval
    out = await g.ainvoke(Command(resume={"action": "approve"}), cfg("t-good"))
    assert out["status"] == "submitted" and out["submission"]["status"] == "submitted"
    props = [p for p in gigsim.account("ai_ml").proposals.values() if p["status"] != "draft"]
    assert len(props) == 1 and gigsim.account("ai_ml").connects == 80 - 8


async def test_critic_loop_is_bounded_at_two(world):
    deps, models = make(world, {"analyst": [SPEC], "writer": [WRITER], "critic": [REVISE]})
    g = build_bid_graph(deps, InMemorySaver())
    out = await g.ainvoke(initial_state(await job(world, GOOD_JOB), "t-crit", "u", "ai_ml"), cfg("t-crit"))
    assert models.calls["writer"] == 3 and models.calls["critic"] == 3   # 1 draft + 2 revisions
    assert "__interrupt__" in out                                           # then goes on to the human
    assert out["revisions"] == 2 and len(out["critiques"]) == 3


async def test_compliance_blocks_off_platform_draft(world):
    bad = dict(WRITER, cover_letter=LETTER + " We can continue outside Upwork and you can pay me directly.")
    deps, _ = make(world, {"analyst": [SPEC], "writer": [bad], "critic": [APPROVE]})
    g = build_bid_graph(deps, InMemorySaver())
    out = await g.ainvoke(initial_state(await job(world, GOOD_JOB), "t-blk", "u", "ai_ml"), cfg("t-blk"))
    assert out["status"] == "blocked" and "no_off_platform" in out["compliance"]["blocked_reason"]
    assert "__interrupt__" not in out


async def test_edit_feeds_style_memory_and_is_rechecked(world):
    mem = MemoryManager(InMemoryStore())
    deps, _ = make(world, memory=mem)
    g = build_bid_graph(deps, InMemorySaver())
    await g.ainvoke(initial_state(await job(world, GOOD_JOB), "t-edit", "u", "ai_ml"), cfg("t-edit"))
    bad_edit = LETTER + " Email me at me@example.com and pay me directly outside Upwork."
    out = await g.ainvoke(Command(resume={"action": "edit", "edited_cover_letter": bad_edit}), cfg("t-edit"))
    assert "__interrupt__" in out                                # blocked edit goes back to the human
    out = await g.ainvoke(Command(resume={"action": "edit", "edited_cover_letter": LETTER.replace("Hi - y", "Y")}),
                          cfg("t-edit"))
    assert out["status"] == "submitted"
    cands = list(mem.store.search(("memory", "u", "style_candidates")))
    assert cands  # the diff was observed (promotion needs 3 threads)


async def test_reject_records_reason(world):
    deps, _ = make(world)
    g = build_bid_graph(deps, InMemorySaver())
    await g.ainvoke(initial_state(await job(world, GOOD_JOB), "t-rej", "u", "ai_ml"), cfg("t-rej"))
    out = await g.ainvoke(Command(resume={"action": "reject", "reason": "client too far in scope"}), cfg("t-rej"))
    assert out["status"] == "rejected" and out["approval"]["reason"] == "client too far in scope"
    assert world.count("submit_proposal") == 0


async def test_crash_while_waiting_then_resume_on_new_process(world, gigsim):
    saver = InMemorySaver()   # stands in for Postgres: survives the "process" (graph object) being discarded
    deps, _ = make(world)
    g1 = build_bid_graph(deps, saver)
    await g1.ainvoke(initial_state(await job(world, GOOD_JOB), "t-crash", "u", "ai_ml"), cfg("t-crash"))
    del g1                                                          # API killed while waiting for approval
    g2 = build_bid_graph(make(world)[0], saver)                    # restarted process, same checkpointer
    snap = await g2.aget_state(cfg("t-crash"))
    assert snap.next == ("approval",) and snap.tasks[0].interrupts  # the pending approval survived
    out = await g2.ainvoke(Command(resume={"action": "approve"}), cfg("t-crash"))
    assert out["status"] == "submitted"
    # replay the submit node from its checkpoint (e.g. worker crashed after sending, before saving)
    hist = [h async for h in g2.aget_state_history(cfg("t-crash"))]
    before_submit = next(h for h in hist if h.next == ("submit",))
    await g2.ainvoke(None, before_submit.config)
    sent = [p for p in gigsim.account("ai_ml").proposals.values() if p["status"] != "draft"]
    assert len(sent) == 1 and gigsim.account("ai_ml").connects == 80 - 8   # still exactly once


async def test_marketplace_down_queues_the_thread(world, gigsim):
    deps, _ = make(world)
    g = build_bid_graph(deps, InMemorySaver())
    j = await job(world, GOOD_JOB)
    gigsim.cfg["faults"]["error_rate"] = 1.0                      # every marketplace call fails
    out = await g.ainvoke(initial_state(j, "t-down", "u", "ai_ml"), cfg("t-down"))
    assert out["halt"] == "queued_marketplace_down"
    assert any("unavailable" in e for e in out["errors"])


async def test_step_budget_moves_thread_to_needs_attention(world, monkeypatch):
    c = node_common.config()
    monkeypatch.setitem(c["budgets"], "max_graph_steps", 3)
    deps, _ = make(world)
    g = build_bid_graph(deps, InMemorySaver())
    out = await g.ainvoke(initial_state(await job(world, GOOD_JOB), "t-bud", "u", "ai_ml"), cfg("t-bud"))
    assert out["halt"] == "needs_attention"
