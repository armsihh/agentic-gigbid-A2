"""Analytics + health (degraded-mode banner)."""
from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np
from fastapi import APIRouter

from agent.mcp_client import health as mcp_health
from apps.api.auth.users import CurrentUser
from apps.api.db import JobRecord, Outcome, Rejection, RunRecord, User, session
from apps.api.runtime import runtime
from apps.api.schemas import Analytics, Health

router = APIRouter(tags=["analytics"])


@router.get("/analytics", response_model=Analytics)
def analytics(user: User = CurrentUser):
    with session() as s:
        jobs = s.query(JobRecord).filter_by(user_id=user.id).all()
        outcomes = s.query(Outcome).filter_by(user_id=user.id).all()
        rejections = s.query(Rejection).filter_by(user_id=user.id).all()
        runs = s.query(RunRecord).filter_by(user_id=user.id).all()
    submitted = [j for j in jobs if j.proposal_id]
    by_cat: dict[str, dict] = defaultdict(lambda: {"submitted": 0, "replied": 0, "hired": 0})
    for j in submitted:
        c = by_cat[j.category or "other"]
        c["submitted"] += 1
        c["replied"] += j.stage in ("replied", "interview", "hired")
        c["hired"] += j.stage == "hired"
    cats = [{"category": k, **v, "reply_rate": round(v["replied"] / v["submitted"], 3) if v["submitted"] else None,
             "hire_rate": round(v["hired"] / v["submitted"], 3) if v["submitted"] else None} for k, v in by_cat.items()]
    spent = sum(j.connects_cost or 0 for j in submitted)
    replies = sum(1 for j in submitted if j.stage in ("replied", "interview", "hired"))
    bid_runs = [r for r in runs if r.kind == "bid" and r.latency_s is not None]
    lat = [r.latency_s for r in bid_runs]
    reasons = Counter((r.reason or "").strip().lower()[:80] for r in rejections)
    stages = Counter(j.stage for j in jobs)
    return Analytics(
        by_category=cats,
        connects={"spent": spent, "replies": replies, "hires": stages.get("hired", 0),
                  "connects_per_reply": round(spent / replies, 1) if replies else None},
        cost_latency={"runs": len(bid_runs), "p50_latency_s": float(np.percentile(lat, 50)) if lat else None,
                      "p95_latency_s": float(np.percentile(lat, 95)) if lat else None,
                      "cost_usd_total": round(sum(r.cost_usd or 0 for r in runs), 4),
                      "cost_usd_per_proposal": round(sum(r.cost_usd or 0 for r in runs) / len(submitted), 4)
                      if submitted else None,
                      "outcomes_recorded": len(outcomes)},
        top_rejection_reasons=[{"reason": k, "count": v} for k, v in reasons.most_common(5) if k],
        funnel={"analysed": len(jobs), "bid": sum(1 for j in jobs if j.action == "bid"),
                "submitted": len(submitted), "replied": replies, "hired": stages.get("hired", 0)})


@router.get("/health", response_model=Health)
async def health():
    """No auth: the UI polls this for the 'marketplace unavailable' banner."""
    status, detail = "ok", None
    try:
        if runtime.mode == "inproc":
            ad = runtime._inproc()["marketplace"]
            await ad.call_tool("get_policy", {})
        else:
            snap = mcp_health.snapshot().get("marketplace") or {}
            status = snap.get("status", "unknown")
            detail = snap.get("last_error")
    except Exception as e:  # noqa: BLE001
        status, detail = "degraded", str(e)[:200]
    snap = mcp_health.snapshot()
    if (snap.get("marketplace") or {}).get("status") == "degraded":
        status, detail = "degraded", snap["marketplace"].get("last_error")
    return Health(api="ok", marketplace=status, marketplace_detail=detail, mode=runtime.mode, servers=snap)
