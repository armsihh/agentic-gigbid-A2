"""Client Liaison nodes for the conversation graph: read new client messages, classify intent, find interview
slots, draft a reply. Writes (send / calendar hold) happen only in the executor after approval."""
from __future__ import annotations

import datetime as dt
import re
from typing import Literal

from pydantic import BaseModel, Field

from agent.guardrails.injection import scan, wrap_untrusted
from agent.nodes.common import Deps, config, step, structured, tool_json
from agent.nodes.writer import render_evidence
from agent.prompts import load_prompt

Intent = Literal["question", "negotiation", "interview_request", "scam_signal", "other"]


class IntentResult(BaseModel):
    intent: Intent
    reason: str = ""


class ReplyDraft(BaseModel):
    text: str = Field(description="The reply, under 120 words")
    proposed_slot_starts: list[str] = Field(default_factory=list, description="ISO starts of slots offered, if any")


def scam_signal(text: str) -> str | None:
    low = scan(text).sanitized.lower()
    for kind in ("off_platform", "upfront_payment", "pii_request", "account_sharing", "crypto_payment"):
        for p in config()["risk"]["patterns"][kind]:
            if re.search(p, low):
                return kind
    if re.search(r"\b(telegram|whats ?app|skype)\b", low) and re.search(r"\b(add|send|contact|continue|move)\b", low):
        return "off_platform"
    return None


def make_load_node(deps: Deps):
    async def load(state: dict) -> dict:
        res = tool_json(await deps.toolbox.call("client_liaison", "list_messages",
                                                {"thread_id": state["marketplace_thread_id"]}))
        thread = (res.get("threads") or [{}])[0]
        msgs = thread.get("messages", [])
        new = [m for m in msgs if m["sender"] == "client"]
        last = new[-1] if new else None
        status = "running" if last and last["message_id"] != state.get("last_seen_message_id") else "skipped"
        return {"messages": msgs, "status": status, "last_seen_message_id": last["message_id"] if last else None,
                "trace": [step("load", f"{len(msgs)} messages; new client message: {status == 'running'}")]}
    return load


def make_intent_node(deps: Deps):
    async def intent(state: dict) -> dict:
        last = next(m for m in reversed(state["messages"]) if m["sender"] == "client")
        hard = scam_signal(last["text"])
        if hard:  # deterministic override: never let a model talk us into an off-platform move
            return {"intent": "scam_signal", "trace": [step("intent", f"scam_signal ({hard}) by rule")]}
        convo = "\n".join(f"{m['sender']}: {m['text']}" for m in state["messages"][-6:])
        res, usage = await structured(deps, "intent", IntentResult, load_prompt("intent").render(),
                                      wrap_untrusted("client_message", convo))
        return {"intent": res.intent, "tokens_used": usage["tokens"],
                "trace": [step("intent", f"{res.intent}: {res.reason}", **{k: v for k, v in usage.items() if k != "tokens"})]}
    return intent


def make_slots_node(deps: Deps):
    async def slots(state: dict) -> dict:
        today = dt.date.today()
        res = tool_json(await deps.toolbox.call("client_liaison", "get_free_slots", {
            "start_date": str(today + dt.timedelta(days=1)), "end_date": str(today + dt.timedelta(days=7)),
            "duration_minutes": 30, "max_slots": 3}))
        s = res.get("slots", []) if isinstance(res, dict) else []
        return {"slots": s, "trace": [step("slots", f"{len(s)} free slots found")]}
    return slots


def make_reply_node(deps: Deps):
    async def reply(state: dict) -> dict:
        last = next(m for m in reversed(state["messages"]) if m["sender"] == "client")
        evidence = []
        if state.get("intent") == "question":
            res = tool_json(await deps.toolbox.call("client_liaison", "search_evidence",
                                                    {"requirement": scan(last["text"]).sanitized[:300], "k": 3}))
            evidence = res.get("items", []) if isinstance(res, dict) else []
        slots = state.get("slots") or []
        floor = deps.profile.get("hourly_rate")
        ctx = (f"Intent: {state.get('intent')}\nFreelancer floor rate: ${floor}/h, minimum fixed "
               f"${deps.profile.get('min_fixed_budget')}\n"
               + ("Available slots:\n" + "\n".join(f"- {s['start']} ({s['timezone']})" for s in slots) + "\n" if slots else "")
               + (f"Evidence:\n{render_evidence(evidence, 3)}" if evidence else ""))
        convo = "\n".join(f"{m['sender']}: {m['text']}" for m in state["messages"][-8:])
        draft, usage = await structured(deps, "client_liaison", ReplyDraft, load_prompt("client_liaison").render(context=ctx),
                                        wrap_untrusted("client_message", convo))
        return {"reply_draft": draft.model_dump() | {"evidence": evidence}, "tokens_used": usage["tokens"],
                "trace": [step("client_liaison", f"reply drafted ({len(draft.text.split())} words)",
                               **{k: v for k, v in usage.items() if k != "tokens"})]}
    return reply
