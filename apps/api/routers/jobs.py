"""Job inbox, job detail, analyse / skip, scout-now, pipeline board."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from agent.nodes.common import tool_json
from agent.state import halt_of
from apps.api.auth.users import CurrentUser
from apps.api.db import JobRecord, User, session
from apps.api.runs import bid_thread
from apps.api.runtime import runtime
from apps.api.schemas import JobDetail, JobRow, RunStarted

router = APIRouter(tags=["jobs"])
STAGES = ["drafted", "submitted", "viewed", "replied", "interview", "hired", "lost"]


def row(r: JobRecord) -> JobRow:
    return JobRow(job_id=r.job_id, thread_id=r.thread_id, title=r.title, category=r.category, status=r.status,
                  stage=r.stage, action=r.action, fit=r.fit, risk=r.risk, risk_level=r.risk_level, price=r.price,
                  connects_cost=r.connects_cost, summary=r.summary or {}, updated_at=r.updated_at.isoformat())


@router.get("/jobs", response_model=list[JobRow])
def inbox(user: User = CurrentUser, action: str | None = None, risk_level: str | None = None,
          category: str | None = None, include_skipped: bool = False, limit: int = Query(100, le=500)):
    with session() as s:
        q = s.query(JobRecord).filter(JobRecord.user_id == user.id)        # tenant-scoped
        if action:
            q = q.filter(JobRecord.action == action)
        if risk_level:
            q = q.filter(JobRecord.risk_level == risk_level)
        if category:
            q = q.filter(JobRecord.category == category)
        if not include_skipped:
            q = q.filter(JobRecord.status != "skipped")
        rows = q.all()
    rows.sort(key=lambda r: (r.status != "waiting_approval", -(r.fit or 0)))   # ranked by fit
    return [row(r) for r in rows[:limit]]


@router.get("/jobs/{job_id}", response_model=JobDetail)
async def job_detail(job_id: str, user: User = CurrentUser):
    graph = runtime.graph(user, "bid")
    snap = await graph.aget_state({"configurable": {"thread_id": bid_thread(user.id, job_id)}})
    v = snap.values or {}
    if not v.get("job"):
        raise HTTPException(404, "job not analysed yet")
    return JobDetail(job=v["job"], status=v.get("status"), halt=halt_of(v), job_spec=v.get("job_spec"),
                     risk_report=v.get("risk_report"), fit_report=v.get("fit_report"), decision=v.get("decision"),
                     price=v.get("price"), evidence=v.get("evidence") or [], trace=v.get("trace") or [],
                     errors=v.get("errors") or [], has_draft=bool(v.get("draft")),
                     pending_approval=bool(snap.tasks and any(t.interrupts for t in snap.tasks)))


@router.post("/jobs/{job_id}/analyze", response_model=RunStarted)
async def analyze(job_id: str, request: Request, user: User = CurrentUser):
    job = tool_json(await runtime.toolbox(user.id, user.persona).call("scout", "get_job", {"job_id": job_id}))
    if not isinstance(job, dict) or "job_id" not in job:
        raise HTTPException(404, "job not found on the marketplace")
    run_id = await request.app.state.runs.start_bid(user, job)
    return RunStarted(run_id=run_id, thread_id=bid_thread(user.id, job_id))


@router.post("/jobs/{job_id}/skip")
def skip(job_id: str, user: User = CurrentUser):
    with session() as s:
        r = s.query(JobRecord).filter_by(user_id=user.id, job_id=job_id).first()
        if not r:
            raise HTTPException(404, "not found")
        r.status, r.action = "skipped", "skip"
        r.summary = {**(r.summary or {}), "reasons": ["skipped by you"]}
        s.commit()
    return {"ok": True}


@router.get("/marketplace/jobs")
async def browse(user: User = CurrentUser, category: str | None = None, query: str | None = None, limit: int = 20):
    """Live marketplace search (read-only), for picking jobs to analyse by hand."""
    res = tool_json(await runtime.toolbox(user.id, user.persona).call(
        "scout", "search_jobs", {k: v for k, v in {"category": category, "query": query, "limit": limit}.items() if v}))
    return res


@router.post("/scout/run")
async def scout_now(request: Request, user: User = CurrentUser):
    n = await request.app.state.scheduler.scout_user(user, force=True)
    return {"queued": n}


@router.get("/pipeline", response_model=dict[str, list[JobRow]])
def pipeline(user: User = CurrentUser):
    with session() as s:
        rows = s.query(JobRecord).filter(JobRecord.user_id == user.id, JobRecord.stage.in_(STAGES)).all()
    out: dict[str, list[JobRow]] = {k: [] for k in STAGES}
    for r in rows:
        out[r.stage].append(row(r))
    return out
