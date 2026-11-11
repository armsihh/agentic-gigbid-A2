"""Agent run viewer: run list/detail and live node-by-node progress over Server-Sent Events."""
from __future__ import annotations

import json
import os

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from apps.api.auth.users import CurrentUser
from apps.api.db import RunRecord, User, session
from apps.api.runs import TERMINAL_RUN, bus
from apps.api.schemas import RunOut

router = APIRouter(tags=["runs"])


def trace_url(trace_id: str) -> str | None:
    base = os.environ.get("TRACE_UI_URL")  # e.g. Langfuse / LangSmith project URL
    return f"{base.rstrip('/')}/{trace_id}" if base else None


def out(r: RunRecord) -> RunOut:
    return RunOut(id=r.id, thread_id=r.thread_id, kind=r.kind, status=r.status, trace_id=r.trace_id,
                  started_at=r.started_at.isoformat(), finished_at=r.finished_at.isoformat() if r.finished_at else None,
                  latency_s=r.latency_s, tokens=r.tokens or 0, cost_usd=r.cost_usd or 0.0, events=r.events or [],
                  error=r.error, trace_url=trace_url(r.trace_id))


def _get(run_id: str, user: User) -> RunRecord:
    with session() as s:
        r = s.get(RunRecord, run_id)
    if not r or r.user_id != user.id:
        raise HTTPException(404, "run not found")
    return r


@router.get("/runs", response_model=list[RunOut])
def runs(user: User = CurrentUser, thread_id: str | None = None, limit: int = 50):
    with session() as s:
        q = s.query(RunRecord).filter(RunRecord.user_id == user.id)
        if thread_id:
            q = q.filter(RunRecord.thread_id == thread_id)
        rows = q.order_by(RunRecord.started_at.desc()).limit(limit).all()
    return [out(r) for r in rows]


@router.get("/runs/{run_id}", response_model=RunOut)
def run(run_id: str, user: User = CurrentUser):
    return out(_get(run_id, user))


@router.get("/runs/{run_id}/stream")
async def stream(run_id: str, user: User = CurrentUser):
    """SSE: first replays events already recorded (refresh-safe), then streams live ones until the run ends."""
    r = _get(run_id, user)

    async def gen():
        sub = bus.subscribe(run_id)        # subscribe before replay so nothing is missed in between
        seen = 0
        for ev in r.events or []:
            seen = ev["seq"]
            yield {"event": ev["type"], "data": json.dumps(ev)}
        if r.status in TERMINAL_RUN:
            return
        async for ev in sub:
            if ev["seq"] <= seen:
                continue
            yield {"event": ev["type"], "data": json.dumps(ev)}
            if ev["type"] == "run" and ev.get("status") in TERMINAL_RUN:
                return

    return EventSourceResponse(gen(), ping=15)
