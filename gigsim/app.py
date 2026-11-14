"""GigSim HTTP API. Run: uv run uvicorn gigsim.app:app --port 8081

Contract documented in gigsim/API.md. GigBid talks to this ONLY through
mcp_servers/marketplace/adapters/gigsim.py, so replacing GigSim means changing that adapter.
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gigsim.world import GigSimError, World, strip_internal

app = FastAPI(title="GigSim", version="1.0.0",
              description="Marketplace simulator for GigBid (built for AI-4016; synthetic + Kaggle-derived data)")
world = World()
_fault_rng = random.Random()
_buckets: dict[str, list[float]] = {}  # token -> [tokens_available, last_refill]


@app.exception_handler(GigSimError)
async def _gigsim_error(_: Request, exc: GigSimError):
    headers = {"Retry-After": str(exc.extra.pop("retry_after"))} if "retry_after" in exc.extra else None
    return JSONResponse(status_code=exc.status, headers=headers,
                        content={"error": {"code": exc.code, "message": exc.message, **strip_internal(exc.extra)}})


# ---------------------------------------------------------------- dependencies
def _token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise GigSimError(401, "unauthorized", "missing bearer token")
    return authorization.split(" ", 1)[1].strip()


def _rate_limit(token: str) -> None:
    rl = world.cfg["rate_limit"]
    rate = rl["requests_per_minute"] / 60.0
    now = time.time()
    tokens, last = _buckets.get(token, [float(rl["burst"]), now])
    tokens = min(float(rl["burst"]), tokens + (now - last) * rate)
    if tokens < 1:
        _buckets[token] = [tokens, now]
        raise GigSimError(429, "rate_limited", "too many requests", retry_after=max(1, int((1 - tokens) / rate) + 1))
    _buckets[token] = [tokens - 1, now]


async def freelancer(authorization: Annotated[str | None, Header()] = None) -> str:
    token = _token(authorization)
    fid = world.cfg["auth"]["tokens"].get(token)
    if not fid:
        raise GigSimError(401, "unauthorized", "unknown token")
    _rate_limit(token)
    f = world.cfg["faults"]
    if _fault_rng.random() < f["slow_rate"]:
        await asyncio.sleep(f["slow_seconds"])
    if _fault_rng.random() < f["error_rate"]:  # fails BEFORE any side effect, so retries are safe
        raise GigSimError(503, "service_unavailable", "transient error, retry with backoff")
    world.tick()
    return fid


async def admin(authorization: Annotated[str | None, Header()] = None) -> None:
    if _token(authorization) != world.cfg["auth"]["admin_token"]:
        raise GigSimError(403, "forbidden", "admin token required")


Fid = Annotated[str, Depends(freelancer)]
IdemKey = Annotated[str | None, Header(alias="Idempotency-Key")]


# ---------------------------------------------------------------- schemas
class DraftIn(BaseModel):
    job_id: str
    cover_letter: str = Field(min_length=1, max_length=8000)
    screening_answers: list[str] = Field(default_factory=list, max_length=10)
    bid_amount: float = Field(gt=0, le=1_000_000)
    boost_connects: int = Field(default=0, ge=0, le=100)
    dry_run: bool = False


class SubmitIn(BaseModel):
    confirm: bool = False
    dry_run: bool = False


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    dry_run: bool = False


# ---------------------------------------------------------------- public
@app.get("/health")
def health():
    return {"status": "ok", "policy_version": world.policy["version"], "uptime_s": round(time.time() - world.start)}


@app.get("/v1/policy")
def policy(_: Fid):
    return world.policy


@app.get("/v1/me")
def me(fid: Fid):
    acc = world.account(fid)
    return {"freelancer_id": fid, "connects_balance": acc.connects,
            "weekly_allowance": world.policy["connects"]["weekly_allowance"],
            "open_proposals": sum(1 for p in acc.proposals.values()
                                  if p["status"] in ("submitted", "viewed", "replied", "interview"))}


@app.get("/v1/jobs")
def search_jobs(_: Fid, q: str | None = None, category: str | None = None,
                skills: Annotated[list[str], Query()] = [],  # noqa: B006
                payment_type: Literal["fixed", "hourly"] | None = None, min_budget: float | None = None,
                posted_after: str | None = None, limit: int = Query(20, ge=1, le=100),
                cursor: int = Query(0, ge=0)):
    return world.search_jobs(q, category, skills, payment_type, min_budget, posted_after, limit, cursor)


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str, _: Fid):
    return world.get_job(job_id)


@app.get("/v1/clients/{client_id}")
def get_client(client_id: str, _: Fid):
    return world.client_profile(client_id)


@app.get("/v1/market/stats")
def market_stats(_: Fid, category: str | None = None, experience_level: str | None = None):
    return world.stats(category, experience_level)


@app.get("/v1/connects")
def connects(fid: Fid):
    acc = world.account(fid)
    return {"balance": acc.connects, "weekly_allowance": world.policy["connects"]["weekly_allowance"],
            "max_balance": world.policy["connects"]["max_balance"]}


@app.get("/v1/proposals")
def list_proposals(fid: Fid, status: str | None = None):
    acc = world.account(fid)
    items = [p for p in acc.proposals.values() if not status or p["status"] == status]
    return {"items": strip_internal(items)}


@app.get("/v1/proposals/{proposal_id}")
def get_proposal(proposal_id: str, fid: Fid):
    p = world.account(fid).proposals.get(proposal_id)
    if not p:
        raise GigSimError(404, "proposal_not_found", "proposal not found")
    return strip_internal(p)


@app.post("/v1/proposals")
def create_proposal(body: DraftIn, fid: Fid, idem: IdemKey = None):
    if body.dry_run:
        return world.create_draft(fid, body.model_dump())
    res, replay = world.idempotent(fid, idem, body.model_dump(), lambda: world.create_draft(fid, body.model_dump()))
    return JSONResponse(strip_internal(res), headers={"Idempotent-Replay": str(replay).lower()})


@app.post("/v1/proposals/{proposal_id}/submit")
def submit_proposal(proposal_id: str, body: SubmitIn, fid: Fid, idem: IdemKey = None):
    if body.dry_run:
        return strip_internal(world.submit(fid, proposal_id, body.model_dump()))
    res, replay = world.idempotent(fid, idem, {"proposal_id": proposal_id, **body.model_dump()},
                                   lambda: world.submit(fid, proposal_id, body.model_dump()))
    return JSONResponse(strip_internal(res), headers={"Idempotent-Replay": str(replay).lower()})


@app.get("/v1/threads")
def list_threads(fid: Fid):
    acc = world.account(fid)
    return {"items": [{k: v for k, v in t.items() if k != "messages"} | {"last_message": t["messages"][-1]}
                      for t in acc.threads.values()]}


@app.get("/v1/threads/{thread_id}")
def get_thread(thread_id: str, fid: Fid):
    t = world.account(fid).threads.get(thread_id)
    if not t:
        raise GigSimError(404, "thread_not_found", "thread not found")
    return t


@app.post("/v1/threads/{thread_id}/messages")
def send_message(thread_id: str, body: MessageIn, fid: Fid, idem: IdemKey = None):
    if body.dry_run:
        return world.send_message(fid, thread_id, body.model_dump())
    res, replay = world.idempotent(fid, idem, {"thread_id": thread_id, **body.model_dump()},
                                   lambda: world.send_message(fid, thread_id, body.model_dump()))
    return JSONResponse(res, headers={"Idempotent-Replay": str(replay).lower()})


@app.get("/v1/events")
def events(fid: Fid, after: int = 0, limit: int = Query(100, ge=1, le=500)):
    evs = [e for e in world.account(fid).events if e["seq"] > after][:limit]
    return {"items": evs, "last_seq": evs[-1]["seq"] if evs else after}


# ---------------------------------------------------------------- admin (simulation control)
@app.post("/admin/advance", dependencies=[Depends(admin)])
def admin_advance(batches: int = 1):
    return {"released": world.advance(batches)}


@app.post("/admin/fast-forward", dependencies=[Depends(admin)])
def admin_fast_forward():
    return {"fired": world.fast_forward()}


class FaultsIn(BaseModel):
    error_rate: float = Field(ge=0, le=1)
    slow_rate: float = Field(0, ge=0, le=1)


@app.post("/admin/faults", dependencies=[Depends(admin)])
def admin_faults(body: FaultsIn):
    """Simulate an outage (error_rate=1) or flakiness for demos and UI tests."""
    world.cfg["faults"].update(error_rate=body.error_rate, slow_rate=body.slow_rate)
    return world.cfg["faults"]


@app.post("/admin/reset", dependencies=[Depends(admin)])
def admin_reset():
    world.reset()
    _buckets.clear()
    return {"status": "reset"}


@app.get("/admin/state", dependencies=[Depends(admin)])
def admin_state():
    return {"jobs_open": sum(1 for j in world.jobs.values() if j["status"] == "open"),
            "jobs_pending": sum(1 for j in world.jobs.values() if j["status"] == "pending"),
            "scheduled_events": len(world.scheduled),
            "accounts": {fid: {"connects": a.connects, "proposals": len(a.proposals), "threads": len(a.threads)}
                         for fid, a in world.accounts.items()}}
