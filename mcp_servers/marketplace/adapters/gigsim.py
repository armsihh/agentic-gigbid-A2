"""GigSim adapter: maps the GigSim REST contract (gigsim/API.md) onto MarketplacePort.

This is the ONLY file that knows GigSim's URLs and field names. If an official GigSim is
released with a different contract, only the `_map_*` functions and paths here change.
"""
from __future__ import annotations

import asyncio
import os
import random
from typing import Any

import httpx

from agent.marketplace_port import (
    ClientHistory,
    Conflict,
    ConnectsBalance,
    DryRunPreview,
    InsufficientConnects,
    Job,
    JobPage,
    JobSummary,
    MarketEvent,
    MarketplaceError,
    MarketplaceUnavailable,
    MarketPolicy,
    MarketStats,
    Message,
    NotFound,
    PolicyViolation,
    PriceQuantiles,
    Proposal,
    ProposalDraftRequest,
    RateLimited,
    Thread,
)

RETRYABLE_STATUS = {429, 502, 503, 504}


class GigSimAdapter:
    name = "gigsim"

    def __init__(self, base_url: str | None = None, token: str | None = None, timeout_s: float = 10.0,
                 max_attempts: int = 4, backoff_base_s: float = 0.5, max_backoff_s: float = 8.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url or os.environ.get("GIGSIM_BASE_URL", "http://localhost:8081")
        self.token = token or os.environ.get("GIGSIM_API_TOKEN", "dev-ai_ml")
        self.max_attempts, self.backoff_base_s, self.max_backoff_s = max_attempts, backoff_base_s, max_backoff_s
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout_s, transport=transport,
                                         headers={"Authorization": f"Bearer {self.token}"})

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------ transport with retries
    async def _request(self, method: str, path: str, *, params: dict | None = None,
                       json: dict | None = None, idempotency_key: str | None = None) -> httpx.Response:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        params = {k: v for k, v in (params or {}).items() if v not in (None, [], "")}
        last: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                r = await self._client.request(method, path, params=params, json=json, headers=headers)
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError) as e:
                last = MarketplaceUnavailable(f"GigSim unreachable: {type(e).__name__}", attempt=attempt)
            else:
                if r.status_code < 400:
                    return r
                if r.status_code not in RETRYABLE_STATUS:
                    raise _to_error(r)
                last = _to_error(r)
                retry_after = r.headers.get("Retry-After")
                if retry_after and attempt < self.max_attempts:
                    await asyncio.sleep(min(float(retry_after), self.max_backoff_s))
                    continue
            if attempt < self.max_attempts:  # exponential backoff with full jitter
                await asyncio.sleep(random.uniform(0, min(self.max_backoff_s, self.backoff_base_s * 2 ** (attempt - 1))))
        assert last is not None
        raise last

    async def _get(self, path: str, **params: Any) -> Any:
        return (await self._request("GET", path, params=params)).json()

    # ------------------------------------------------------------ reads
    async def health(self) -> dict[str, Any]:
        return (await self._request("GET", "/health")).json()

    async def get_policy(self) -> MarketPolicy:
        p = await self._get("/v1/policy")
        return MarketPolicy(version=str(p.get("version")), rules=p.get("rules", []), raw=p)

    async def search_jobs(self, query=None, category=None, skills=None, payment_type=None, min_budget=None,
                          posted_after=None, limit=20, cursor=0) -> JobPage:
        d = await self._get("/v1/jobs", q=query, category=category, skills=skills or [], payment_type=payment_type,
                            min_budget=min_budget, posted_after=posted_after, limit=limit, cursor=cursor)
        return JobPage(items=[_map_job_summary(j) for j in d["items"]], total=d["total"],
                       next_cursor=d.get("next_cursor"))

    async def get_job(self, job_id: str) -> Job:
        return _map_job(await self._get(f"/v1/jobs/{job_id}"))

    async def get_client_history(self, client_id: str) -> ClientHistory:
        c = await self._get(f"/v1/clients/{client_id}")
        return ClientHistory(**{k: c.get(k) for k in ClientHistory.model_fields if c.get(k) is not None})

    async def get_connects_balance(self) -> ConnectsBalance:
        return ConnectsBalance(**await self._get("/v1/connects"))

    async def get_market_stats(self, category=None, experience_level=None) -> MarketStats:
        d = await self._get("/v1/market/stats", category=category, experience_level=experience_level)
        src = (d.get("category_level") or (d.get("by_category") or {}).get(category or "", None) or {}) if category else {}

        def q(x: dict | None) -> PriceQuantiles | None:
            return PriceQuantiles(**x) if x else None
        return MarketStats(category=category, experience_level=experience_level,
                           fixed_budget=q(src.get("fixed_budget")), hourly_high=q(src.get("hourly_high")),
                           hourly_low=q(src.get("hourly_low")))

    async def list_proposals(self, status=None) -> list[Proposal]:
        d = await self._get("/v1/proposals", status=status)
        return [_map_proposal(p) for p in d["items"]]

    async def get_proposal(self, proposal_id: str) -> Proposal:
        return _map_proposal(await self._get(f"/v1/proposals/{proposal_id}"))

    async def list_threads(self) -> list[Thread]:
        d = await self._get("/v1/threads")
        return [Thread(**{k: t.get(k) for k in ("thread_id", "proposal_id", "job_id", "client_id", "job_title")},
                       messages=[Message(**t["last_message"])] if t.get("last_message") else [])
                for t in d["items"]]

    async def get_thread(self, thread_id: str) -> Thread:
        t = await self._get(f"/v1/threads/{thread_id}")
        return Thread(**{k: t.get(k) for k in ("thread_id", "proposal_id", "job_id", "client_id", "job_title")},
                      messages=[Message(**m) for m in t["messages"]])

    async def list_events(self, after: int = 0) -> list[MarketEvent]:
        d = await self._get("/v1/events", after=after)
        out = []
        for e in d["items"]:
            base = {k: e.get(k) for k in ("seq", "type", "at", "proposal_id", "thread_id")}
            out.append(MarketEvent(**base, data={k: v for k, v in e.items() if k not in base}))
        return out

    # ------------------------------------------------------------ writes
    async def create_proposal_draft(self, req: ProposalDraftRequest, idempotency_key: str, dry_run: bool = False):
        body = req.model_dump() | {"dry_run": dry_run}
        d = (await self._request("POST", "/v1/proposals", json=body, idempotency_key=idempotency_key)).json()
        if dry_run:
            w = d["would_create"]
            return DryRunPreview(action="create_proposal_draft", would_send=w,
                                 connects_cost=w["connects_cost_on_submit"],
                                 connects_balance_after=w["connects_balance_after_submit"],
                                 policy_version=w.get("policy_version"))
        return _map_proposal(d)

    async def submit_proposal(self, proposal_id: str, idempotency_key: str, dry_run: bool = False):
        body = {"confirm": True, "dry_run": dry_run}
        d = (await self._request("POST", f"/v1/proposals/{proposal_id}/submit", json=body,
                                 idempotency_key=idempotency_key)).json()
        if dry_run:
            w = d["would_submit"]
            return DryRunPreview(action="submit_proposal", would_send=w, connects_cost=w["connects_cost"],
                                 connects_balance_after=w["connects_balance_after"],
                                 policy_version=w.get("policy_version"))
        return _map_proposal(d)

    async def send_message(self, thread_id: str, text: str, idempotency_key: str, dry_run: bool = False):
        d = (await self._request("POST", f"/v1/threads/{thread_id}/messages", json={"text": text, "dry_run": dry_run},
                                 idempotency_key=idempotency_key)).json()
        if dry_run:
            return DryRunPreview(action="send_message", would_send=d["would_send"])
        return Message(**d)


# ---------------------------------------------------------------- mapping
def _map_job_summary(j: dict) -> JobSummary:
    return JobSummary(job_id=j["job_id"], title=j["title"], snippet=j.get("description", "")[:280],
                      skills=j.get("skills") or [], category=j.get("category"),
                      experience_level=j.get("experience_level"), payment_type=j["payment_type"],
                      budget=j.get("budget"), hourly_low=j.get("hourly_low"), hourly_high=j.get("hourly_high"),
                      connects_cost=j.get("connects_cost") or 0, client_id=j.get("client_id"),
                      country=j.get("country"), posted_at=j.get("posted_at"))


def _map_job(j: dict) -> Job:
    return Job(**_map_job_summary(j).model_dump(), description=j.get("description", ""),
               duration=j.get("duration"), applicants=j.get("applicants"))


def _map_proposal(p: dict) -> Proposal:
    return Proposal(**{k: p.get(k) for k in Proposal.model_fields if p.get(k) is not None})


def _to_error(r: httpx.Response) -> MarketplaceError:
    try:
        err = r.json().get("error", {})
    except ValueError:
        err = {}
    msg = err.get("message") or r.text[:200]
    details = {k: v for k, v in err.items() if k not in ("message",)} | {"status": r.status_code}
    if r.status_code == 429:
        return RateLimited(msg, retry_after=r.headers.get("Retry-After"), **details)
    if r.status_code >= 500:
        return MarketplaceUnavailable(msg, **details)
    if r.status_code == 404:
        return NotFound(msg, **details)
    if r.status_code == 402:
        return InsufficientConnects(msg, **details)
    if r.status_code == 409:
        return Conflict(msg, **details)
    if r.status_code == 422 and err.get("code") == "policy_violation":
        return PolicyViolation(msg, **details)
    return MarketplaceError(msg, **details)
