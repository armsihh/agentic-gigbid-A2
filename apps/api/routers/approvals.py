"""Approvals: list pending interrupts (they survive refreshes and restarts: they live in the checkpointer) and
resume the paused graph thread with the human's decision."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from apps.api.auth.users import CurrentUser
from apps.api.db import JobRecord, User, session
from apps.api.runtime import runtime
from apps.api.schemas import ApprovalIn, PendingApproval, RunStarted

router = APIRouter(tags=["approvals"])


@router.get("/approvals", response_model=list[PendingApproval])
async def pending(user: User = CurrentUser):
    with session() as s:
        rows = s.query(JobRecord).filter_by(user_id=user.id, status="waiting_approval").all()
    out = []
    for r in rows:
        snap = await runtime.graph(user, "bid").aget_state({"configurable": {"thread_id": r.thread_id}})
        if snap.tasks and any(t.interrupts for t in snap.tasks):   # source of truth: the checkpoint
            out.append(PendingApproval(thread_id=r.thread_id, kind="proposal", title=r.title,
                                       created_at=r.updated_at.isoformat()))
    return out


@router.get("/approvals/{thread_id}")
async def payload(thread_id: str, user: User = CurrentUser):
    if not thread_id.startswith(user.id + ":"):
        raise HTTPException(404, "not found")                     # tenant isolation
    kind = "conversation" if ":conv:" in thread_id else "bid"
    snap = await runtime.graph(user, kind).aget_state({"configurable": {"thread_id": thread_id}})
    for t in snap.tasks or []:
        for i in t.interrupts:
            return i.value
    raise HTTPException(404, "nothing waiting for approval")


@router.post("/approvals/{thread_id}", response_model=RunStarted)
async def decide(thread_id: str, body: ApprovalIn, request: Request, user: User = CurrentUser):
    if not thread_id.startswith(user.id + ":"):
        raise HTTPException(404, "not found")
    if body.action == "reject" and not body.reason:
        raise HTTPException(422, "a reason is required to reject")
    if body.action == "edit" and not body.edited_cover_letter:
        raise HTTPException(422, "edited text is required")
    kind = "conversation" if ":conv:" in thread_id else "bid"
    snap = await runtime.graph(user, kind).aget_state({"configurable": {"thread_id": thread_id}})
    if not (snap.tasks and any(t.interrupts for t in snap.tasks)):
        raise HTTPException(409, "this thread is not waiting for approval (already decided?)")
    decision = body.model_dump(exclude_none=True) | {"approver": user.email}
    run_id = await request.app.state.runs.resume(user, thread_id, decision)
    with session() as s:
        r = s.query(JobRecord).filter_by(user_id=user.id, thread_id=thread_id).first()
        if r:
            r.status = "resuming"
            s.commit()
    return RunStarted(run_id=run_id, thread_id=thread_id)
