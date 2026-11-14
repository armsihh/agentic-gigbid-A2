"""Bid graph (C1): one thread per job.

    ingest -> [analyst | risk_assessor | fit_matcher] (parallel, Send) -> decide
      -> skip / watch: END (reason recorded)
      -> bid: pricing -> writer -> verify -> critic --(revise, max 2)--> writer
                                                   --> compliance --(blocked)--> END (reason shown in UI)
                                                                  --> preview (dry_run) -> approval: interrupt()
                                                                        approve -> submit -> END
                                                                        edit    -> re-check compliance -> preview / submit
                                                                        reject  -> END (reason recorded)
Any node can halt the thread (budget -> needs_attention, marketplace down -> queued, repeated failure -> dead letter).
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from agent.graphs.common import guarded, halted
from agent.handoffs import ApprovalDecision, ScreeningAnswer
from agent.nodes.analyst import make_analyst_node
from agent.nodes.common import Deps, config, step
from agent.nodes.compliance import check as compliance_check
from agent.nodes.compliance import make_compliance_node
from agent.nodes.critic import make_critic_node, make_verify_node
from agent.nodes.decision import make_decision_node
from agent.nodes.executor import make_preview_node, make_submit_node
from agent.nodes.fit_matcher import make_fit_node
from agent.nodes.pricing import make_pricing_node
from agent.nodes.risk_assessor import make_risk_node
from agent.nodes.scout import make_ingest_node
from agent.nodes.writer import make_writer_node
from agent.state import BidState


def approval_payload(state: dict) -> dict:
    """Everything the human needs to decide: draft, evidence behind every claim, risk, price rationale, dry run."""
    ev = {e["evidence_id"]: e for e in state.get("evidence") or []}
    draft = state["draft"]
    return {
        "kind": "proposal_approval", "job": {k: state["job"].get(k) for k in ("job_id", "title", "payment_type",
                                                                                "budget", "hourly_low", "hourly_high")},
        "draft": draft,
        "claims": [{"text": c["text"], "evidence": [ev[i] for i in c.get("evidence_ids", []) if i in ev]}
                   for c in draft.get("claims", [])],
        "verification": state.get("verification"), "critique": (state.get("critiques") or [None])[-1],
        "compliance": state.get("compliance"), "risk_report": state.get("risk_report"),
        "fit_report": state.get("fit_report"), "price": state.get("price"),
        "dry_run_preview": state.get("dry_run_preview"),
        "actions": ["approve", "edit", "reject"],
    }


def make_approval_node(deps: Deps):
    async def approval(state: dict) -> dict:
        raw = interrupt(approval_payload(state))           # pauses here; resumed by the UI with Command(resume=...)
        d = ApprovalDecision.model_validate(raw)
        draft = state["draft"]
        if d.action == "reject":
            return {"approval": d.model_dump(), "status": "rejected",
                    "trace": [step("approval", f"REJECTED by {d.approver or 'user'}: {d.reason}")]}
        if d.action == "edit":
            edited = {**draft, "cover_letter": d.edited_cover_letter or draft["cover_letter"]}
            if d.edited_screening_answers is not None:
                edited["screening_answers"] = [a.model_dump() if isinstance(a, ScreeningAnswer) else a
                                               for a in d.edited_screening_answers]
            if deps.memory:  # style memory learns from the diff (promotion rules decide what sticks)
                deps.memory.record_edit(state.get("user_id", "local"), state["thread_id"], draft["cover_letter"],
                                        edited["cover_letter"], set(deps.profile.get("skills", [])))
            v = compliance_check(edited["cover_letter"], deps.profile)
            if not v.allowed:  # edited text breaks policy: back to the human with the reason
                return {"draft": edited, "compliance": v.model_dump(), "approval": d.model_dump(),
                        "status": "waiting_approval",
                        "trace": [step("approval", f"EDIT blocked by compliance: {v.blocked_reason}")]}
            if v.redacted_text:  # contact details / guarantees removed from the human's edit; send the clean text
                edited["cover_letter"] = v.redacted_text
            return {"draft": edited, "compliance": v.model_dump(), "approval": d.model_dump(), "status": "approved",
                    "trace": [step("approval", "EDITED and approved; edit recorded for style memory")]}
        return {"approval": d.model_dump(), "status": "approved", "trace": [step("approval", "APPROVED")]}
    return approval


def build_bid_graph(deps: Deps, checkpointer=None, store=None):
    g = StateGraph(BidState)
    nodes = {
        "ingest": make_ingest_node(deps), "analyst": make_analyst_node(deps), "risk_assessor": make_risk_node(deps),
        "fit_matcher": make_fit_node(deps), "decide": make_decision_node(deps), "pricing": make_pricing_node(deps),
        "writer": make_writer_node(deps), "verify": make_verify_node(deps), "critic": make_critic_node(deps),
        "compliance": make_compliance_node(deps), "preview": make_preview_node(deps),
        "submit": make_submit_node(deps),
    }
    for name, fn in nodes.items():
        g.add_node(name, guarded(name, fn, attempts=1 if name == "submit" else 2))
    g.add_node("approval", make_approval_node(deps))  # not wrapped: interrupt() must propagate untouched

    def nxt(target):
        return lambda s: END if halted(s) else target

    g.add_edge(START, "ingest")
    g.add_conditional_edges("ingest", lambda s: END if halted(s) else
                            [Send("analyst", s), Send("risk_assessor", s), Send("fit_matcher", s)],
                            ["analyst", "risk_assessor", "fit_matcher", END])
    for b in ("analyst", "risk_assessor", "fit_matcher"):
        g.add_edge(b, "decide")
    g.add_conditional_edges("decide", lambda s: END if halted(s) or s["decision"]["action"] != "bid" else "pricing",
                            ["pricing", END])
    g.add_conditional_edges("pricing", nxt("writer"), ["writer", END])
    g.add_conditional_edges("writer", nxt("verify"), ["verify", END])
    g.add_conditional_edges("verify", nxt("critic"), ["critic", END])

    def after_critic(s):
        if halted(s):
            return END
        last = s["critiques"][-1]
        if not last["approve"] and s.get("revisions", 0) > last["revision_number"]:
            return "writer"  # bounded: critic only increments revisions while < max_revisions
        return "compliance"
    g.add_conditional_edges("critic", after_critic, ["writer", "compliance", END])
    g.add_conditional_edges("compliance", nxt("preview"), ["preview", END])
    g.add_edge("preview", "approval")
    # a blocked edit goes straight back to the human (with the compliance reason); it is never sent anywhere,
    # not even as a dry run
    g.add_conditional_edges("approval", lambda s: {"approved": "submit", "waiting_approval": "approval"}.get(s["status"], END),
                            ["submit", "approval", END])
    g.add_edge("submit", END)
    return g.compile(checkpointer=checkpointer, store=store, name="bid_graph")


def initial_state(job: dict, thread_id: str, user_id: str, persona: str, trace_id: str | None = None) -> dict:
    return {"job": job, "thread_id": thread_id, "user_id": user_id, "persona": persona,
            "trace_id": trace_id or thread_id, "status": "running", "revisions": 0,
            "halt": "clear"}  # a re-run after a failure starts clean


__all__ = ["approval_payload", "build_bid_graph", "config", "initial_state"]
