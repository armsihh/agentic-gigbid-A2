"""Client conversations: threads from the marketplace, suggested replies via the conversation graph."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from agent.nodes.common import tool_json
from agent.state import halt_of
from apps.api.auth.users import CurrentUser
from apps.api.db import User
from apps.api.runs import conv_thread
from apps.api.runtime import runtime
from apps.api.schemas import RunStarted

router = APIRouter(tags=["messages"])


@router.get("/messages/threads")
async def threads(user: User = CurrentUser):
    res = tool_json(await runtime.toolbox(user.id, user.persona).call("client_liaison", "list_messages", {}))
    out = []
    for t in (res.get("threads", []) if isinstance(res, dict) else []):
        snap = await runtime.graph(user, "conversation").aget_state(
            {"configurable": {"thread_id": conv_thread(user.id, t["thread_id"])}})
        v = snap.values or {}
        out.append(t | {"suggestion_status": v.get("status"), "intent": v.get("intent"),
                        "pending_approval": bool(snap.tasks and any(x.interrupts for x in snap.tasks)),
                        "graph_thread_id": conv_thread(user.id, t["thread_id"])})
    return {"threads": out}


@router.get("/messages/threads/{thread_id}")
async def thread(thread_id: str, user: User = CurrentUser):
    res = tool_json(await runtime.toolbox(user.id, user.persona).call("client_liaison", "list_messages",
                                                                      {"thread_id": thread_id}))
    ts = res.get("threads", []) if isinstance(res, dict) else []
    if not ts:
        raise HTTPException(404, "thread not found")
    snap = await runtime.graph(user, "conversation").aget_state(
        {"configurable": {"thread_id": conv_thread(user.id, thread_id)}})
    v = snap.values or {}
    return {"thread": ts[0], "reply_draft": v.get("reply_draft"), "intent": v.get("intent"), "slots": v.get("slots"),
            "compliance": v.get("compliance"), "status": v.get("status"), "halt": halt_of(v),
            "pending_approval": bool(snap.tasks and any(x.interrupts for x in snap.tasks)),
            "graph_thread_id": conv_thread(user.id, thread_id)}


@router.post("/messages/threads/{thread_id}/suggest", response_model=RunStarted)
async def suggest(thread_id: str, request: Request, user: User = CurrentUser):
    run_id = await request.app.state.runs.start_conversation(user, thread_id)
    return RunStarted(run_id=run_id, thread_id=conv_thread(user.id, thread_id))
