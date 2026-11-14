"""Signature extension X1, agency mode: a team of freelancers (the three personas) shares one inbox; GigBid routes
each job to the best-fit member and the bid graph then drafts in that member's voice (their profile, portfolio,
rates and style memory). Routing is deterministic: the Fit Matcher runs once per member, against that member's
portfolio only (tenant-scoped Portfolio MCP), and the member with the best (fit, covered requirements, rate fit)
wins. No member is chosen when nobody clears the decision rules' fit threshold.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from agent.nodes.common import config
from agent.nodes.fit_matcher import make_fit_node


class MemberFit(BaseModel):
    member: str
    fit: float
    covered: int
    rate_ok: bool
    evidence_ids: list[str] = Field(default_factory=list)


class Routing(BaseModel):
    job_id: str
    chosen: str | None
    reason: str
    candidates: list[MemberFit]


def _rate_ok(job: dict, profile: dict) -> bool:
    d = config()["decision"]
    if job.get("payment_type") == "hourly" and job.get("hourly_high"):
        return job["hourly_high"] >= d["hourly_min_ratio_of_rate"] * float(profile.get("hourly_rate") or 0)
    if job.get("budget"):
        return job["budget"] >= float(profile.get("min_fixed_budget") or 0)
    return True


async def route(job: dict, team: dict[str, object]) -> Routing:
    """team: member id -> Deps (each with its own persona-scoped toolbox and profile)."""
    cands = []
    for member, deps in team.items():
        rep = (await make_fit_node(deps)({"job": job}))["fit_report"]
        cands.append(MemberFit(member=member, fit=rep["score"],
                               covered=sum(m["status"] == "covered" for m in rep["matches"]),
                               rate_ok=_rate_ok(job, deps.profile), evidence_ids=rep["evidence_ids"][:5]))
    cands.sort(key=lambda c: (c.rate_ok, c.fit, c.covered), reverse=True)
    best = cands[0] if cands else None
    floor = config()["decision"]["watch_if_fit_below"]   # same bar as a "bid" decision, not just "not skip"
    if not best or best.fit < floor or not best.rate_ok:
        return Routing(job_id=job["job_id"], chosen=None, candidates=cands,
                       reason=f"no member reaches bid-level fit {floor} at an acceptable rate "
                              f"(best {best.member if best else '-'} {best.fit if best else 0:.2f})")
    runner_up = cands[1].fit if len(cands) > 1 else 0
    return Routing(job_id=job["job_id"], chosen=best.member, candidates=cands,
                   reason=f"{best.member}: fit {best.fit:.2f} ({best.covered} requirements covered) vs next {runner_up:.2f}")
