"""Conversation graph (C1): one thread per client conversation.

    load -> (no new client message: END)
         -> intent -> [interview_request: slots] -> reply -> compliance -> preview (dry_run) -> approval: interrupt()
              approve/edit -> send (+ tentative calendar hold if a slot was offered) -> END
              reject -> END
"""
from __future__ import annotations

import hashlib

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent.graphs.common import guarded, halted
from agent.handoffs import ApprovalDecision
from agent.nodes.client_liaison import (
    make_intent_node,
    make_load_node,
    make_reply_node,
    make_slots_node,
)
from agent.nodes.common import Deps, step, tool_json
from agent.nodes.compliance import check as compliance_check
from agent.state import ConversationState


def _key(prefix: str, state: dict) -> str:
    base = f"{state['marketplace_thread_id']}:{state.get('last_seen_message_id')}"
    return f"{prefix}:{hashlib.sha1(base.encode()).hexdigest()[:20]}"


def make_reply_compliance(deps: Deps):
    async def reply_compliance(state: dict) -> dict:
        v = compliance_check(state["reply_draft"]["text"], deps.profile)
        upd = {"compliance": v.model_dump(), "trace": [step("compliance", "allowed" if v.allowed else f"BLOCKED: {v.blocked_reason}")]}
        if v.allowed and v.redacted_text:
            upd["reply_draft"] = {**state["reply_draft"], "text": v.redacted_text}
        if not v.allowed:
            upd["status"] = "blocked"
        return upd
    return reply_compliance


def make_msg_preview(deps: Deps):
    async def preview(state: dict) -> dict:
        res = tool_json(await deps.toolbox.call("executor", "send_message", {
            "thread_id": state["marketplace_thread_id"], "text": state["reply_draft"]["text"],
            "idempotency_key": _key("msg", state), "dry_run": True}))
        return {"status": "waiting_approval", "trace": [step("preview", "dry run of message")],
                "reply_draft": {**state["reply_draft"], "dry_run": res.get("preview") if isinstance(res, dict) else res}}
    return preview


def make_msg_approval(deps: Deps):
    async def approval(state: dict) -> dict:
        raw = interrupt({"kind": "message_approval", "reply_draft": state["reply_draft"], "intent": state.get("intent"),
                         "slots": state.get("slots"), "compliance": state.get("compliance"),
                         "conversation": state.get("messages", [])[-6:], "actions": ["approve", "edit", "reject"]})
        d = ApprovalDecision.model_validate(raw)
        if d.action == "reject":
            return {"approval": d.model_dump(), "status": "rejected", "trace": [step("approval", f"REJECTED: {d.reason}")]}
        draft = dict(state["reply_draft"])
        if d.action == "edit" and d.edited_cover_letter:
            v = compliance_check(d.edited_cover_letter, deps.profile)
            if not v.allowed:
                return {"compliance": v.model_dump(), "status": "waiting_approval",
                        "trace": [step("approval", f"EDIT blocked: {v.blocked_reason}")]}
            draft["text"] = v.redacted_text or d.edited_cover_letter
        return {"approval": d.model_dump(), "reply_draft": draft, "status": "approved",
                "trace": [step("approval", "APPROVED" if d.action == "approve" else "EDITED and approved")]}
    return approval


def make_send(deps: Deps):
    async def send(state: dict) -> dict:
        r = tool_json(await deps.toolbox.call("executor", "send_message", {
            "thread_id": state["marketplace_thread_id"], "text": state["reply_draft"]["text"],
            "idempotency_key": _key("msg", state)}))
        hold = None
        starts = state["reply_draft"].get("proposed_slot_starts") or []
        if state.get("intent") == "interview_request" and starts:
            hold = tool_json(await deps.toolbox.call("executor", "create_interview_hold", {
                "start": starts[0], "duration_minutes": 30, "title": "Interview (tentative)",
                "thread_id": state["marketplace_thread_id"], "idempotency_key": _key("hold", state)}))
        return {"sent": {"message": r.get("message") if isinstance(r, dict) else r, "hold": hold}, "status": "sent",
                "trace": [step("send", "message sent" + (" + tentative hold" if hold else ""))]}
    return send


def build_conversation_graph(deps: Deps, checkpointer=None, store=None):
    g = StateGraph(ConversationState)
    for name, fn in {"load": make_load_node(deps), "intent": make_intent_node(deps), "slots": make_slots_node(deps),
                     "reply": make_reply_node(deps), "compliance": make_reply_compliance(deps),
                     "preview": make_msg_preview(deps), "send": make_send(deps)}.items():
        g.add_node(name, guarded(name, fn, attempts=1 if name == "send" else 2))
    g.add_node("approval", make_msg_approval(deps))
    g.add_edge(START, "load")
    g.add_conditional_edges("load", lambda s: END if halted(s) else "intent", ["intent", END])
    g.add_conditional_edges("intent", lambda s: END if halted(s) else ("slots" if s.get("intent") == "interview_request"
                                                                      else "reply"), ["slots", "reply", END])
    g.add_conditional_edges("slots", lambda s: END if halted(s) else "reply", ["reply", END])
    g.add_conditional_edges("reply", lambda s: END if halted(s) else "compliance", ["compliance", END])
    g.add_conditional_edges("compliance", lambda s: END if halted(s) else "preview", ["preview", END])
    g.add_edge("preview", "approval")
    g.add_conditional_edges("approval", lambda s: {"approved": "send", "waiting_approval": "approval"}.get(s["status"], END),
                            ["send", "approval", END])
    g.add_edge("send", END)
    return g.compile(checkpointer=checkpointer, store=store, name="conversation_graph")
