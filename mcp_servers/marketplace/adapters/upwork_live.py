"""Live Upwork adapter (A4): official Upwork MCP server (https://mcp.upwork.com/mcp) behind MarketplacePort.

Connection: MultiServerMCPClient over Streamable HTTP, authenticated with OAuth 2.1 (dynamic client
registration + PKCE) via `apps.api.auth.upwork_oauth.OAuthBroker`; tokens are encrypted per user.

Platform respect (assignment "Integrity" rules, Upwork bots & automation policy):
  * Only the official MCP server. No scraping, browser automation or session cookies.
  * Job search is rate-guarded: at most one live search per `min_search_interval_s` per user (cached).
  * Proposals are only ever created as DRAFTS after approval in GigBid. `submit_proposal` never
    auto-confirms: the user confirms the draft on upwork.com, where Connects are actually spent.
  * Messages go out only through this adapter after approval in GigBid's UI.

Upwork does not publish fixed tool names; they are discovered with list_tools after login. The
`upwork.tool_map` section of agent/config.yaml lists candidate names per port method; mapping of
results is tolerant to field naming. STATUS: implemented against the published capability list,
not yet exercised against a live account (no Upwork account available during development).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import yaml

from agent.marketplace_port import (
    ClientHistory,
    ConnectsBalance,
    DryRunPreview,
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
    Proposal,
    ProposalDraftRequest,
    Thread,
)

ROOT = Path(__file__).resolve().parents[3]
UPWORK_MCP_URL = os.environ.get("UPWORK_MCP_URL", "https://mcp.upwork.com/mcp")


def _cfg() -> dict:
    cfg = yaml.safe_load((ROOT / "agent" / "config.yaml").read_text())
    return cfg.get("upwork", {})


def _pick(d: dict, *keys: str, default: Any = None) -> Any:
    """First present key, also searching one level of nesting (tolerant mapping)."""
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    for v in d.values():
        if isinstance(v, dict):
            for k in keys:
                if k in v and v[k] is not None:
                    return v[k]
    return default


class UpworkLiveAdapter:
    name = "upwork"

    def __init__(self, user_id: str | None = None, auth: Any = None, client: Any = None):
        """`auth`: an httpx.Auth (OAuthClientProvider from OAuthBroker.provider(user_id)).
        `client`: injectable MultiServerMCPClient (tests)."""
        self.user_id = user_id or os.environ.get("MARKETPLACE_USER", "local")
        cfg = _cfg()
        self.tool_map: dict[str, list[str]] = cfg.get("tool_map", {})
        self.min_search_interval_s = float(cfg.get("min_search_interval_s", 900))
        if client is None:
            from langchain_mcp_adapters.client import MultiServerMCPClient
            if auth is None:
                from apps.api.auth.upwork_oauth import OAuthBroker
                auth = OAuthBroker().provider(self.user_id)
            client = MultiServerMCPClient({"upwork": {"transport": "streamable_http", "url": UPWORK_MCP_URL,
                                                      "auth": auth, "timeout": 30}})
        self._client = client
        self._tools: dict[str, str] | None = None
        self._search_cache: dict[str, tuple[float, JobPage]] = {}

    async def aclose(self) -> None:
        return None

    # ------------------------------------------------------------ MCP plumbing
    async def _resolve_tools(self, session) -> dict[str, str]:
        if self._tools is None:
            available = {t.name for t in (await session.list_tools()).tools}
            resolved = {}
            for method, candidates in self.tool_map.items():
                for c in candidates:
                    if c in available:
                        resolved[method] = c
                        break
            self._tools = resolved
        return self._tools

    async def _call(self, method: str, args: dict[str, Any]) -> Any:
        try:
            async with self._client.session("upwork") as s:
                tools = await self._resolve_tools(s)
                if method not in tools:
                    raise MarketplaceError(f"Upwork MCP exposes no tool for {method!r}; update upwork.tool_map",
                                           method=method)
                res = await s.call_tool(tools[method], {k: v for k, v in args.items() if v is not None})
        except MarketplaceError:
            raise
        except Exception as e:
            raise MarketplaceUnavailable(f"Upwork MCP unavailable: {type(e).__name__}") from e
        if res.isError:
            text = " ".join(getattr(c, "text", "") for c in res.content)
            if "not found" in text.lower():
                raise NotFound(text[:300])
            raise MarketplaceError(text[:300])
        if res.structuredContent is not None:
            return res.structuredContent
        text = "".join(getattr(c, "text", "") for c in res.content)
        try:
            return json.loads(text)
        except ValueError:
            return {"text": text}

    # ------------------------------------------------------------ reads
    async def health(self) -> dict[str, Any]:
        try:
            async with self._client.session("upwork") as s:
                await self._resolve_tools(s)
            return {"status": "ok", "tools_mapped": sorted(self._tools or {})}
        except Exception as e:
            raise MarketplaceUnavailable(f"Upwork MCP unavailable: {type(e).__name__}") from e

    async def get_policy(self) -> MarketPolicy:
        # Upwork's rules are not served over MCP; we use our policy pack, versioned by file.
        pack = (ROOT / "data" / "policy_pack" / "marketplace_policy.md").read_text(encoding="utf-8")
        return MarketPolicy(version="upwork-policy-pack", rules=[{"id": "pack", "text": pack}], raw={})

    async def search_jobs(self, query=None, category=None, skills=None, payment_type=None, min_budget=None,
                          posted_after=None, limit=20, cursor=0) -> JobPage:
        key = json.dumps([query, category, skills, payment_type, min_budget, limit, cursor])
        hit = self._search_cache.get(key)
        if hit and time.time() - hit[0] < self.min_search_interval_s:
            return hit[1]  # polite: never poll the live marketplace faster than the configured interval
        d = await self._call("search_jobs", {"query": " ".join(filter(None, [query, *(skills or [])])) or None,
                                             "category": category, "limit": limit, "offset": cursor})
        items = _pick(d, "jobs", "items", "results", default=[]) or []
        page = JobPage(items=[_job_summary(j) for j in items], total=int(_pick(d, "total", "count", default=len(items))),
                       next_cursor=cursor + limit if len(items) == limit else None)
        self._search_cache[key] = (time.time(), page)
        return page

    async def get_job(self, job_id: str) -> Job:
        j = await self._call("get_job", {"job_id": job_id, "id": job_id})
        j = _pick(j, "job", default=j) if isinstance(j, dict) else j
        s = _job_summary(j)
        return Job(**s.model_dump(), description=str(_pick(j, "description", "content", default="")),
                   duration=_pick(j, "duration", "engagement_duration"), applicants=_pick(j, "applicants", "proposals_count"))

    async def get_client_history(self, client_id: str) -> ClientHistory:
        c = await self._call("get_client_history", {"client_id": client_id})
        return ClientHistory(client_id=client_id, country=_pick(c, "country"),
                             payment_verified=bool(_pick(c, "payment_verified", "paymentVerificationStatus", default=False)),
                             total_spent=float(_pick(c, "total_spent", "totalSpent", default=0) or 0),
                             rating=_pick(c, "rating", "feedback_score"), reviews=int(_pick(c, "reviews", "total_reviews", default=0) or 0),
                             jobs_posted=int(_pick(c, "jobs_posted", "total_jobs", default=0) or 0),
                             hires=int(_pick(c, "hires", "total_hires", default=0) or 0))

    async def get_connects_balance(self) -> ConnectsBalance:
        d = await self._call("get_connects_balance", {})
        return ConnectsBalance(balance=int(_pick(d, "connects", "balance", "available_connects", default=0)))

    async def get_market_stats(self, category=None, experience_level=None) -> MarketStats:
        # Upwork does not expose market statistics over MCP: fall back to the Kaggle-derived stats.
        stats = json.loads((ROOT / "data" / "gigsim_seed" / "market_stats.json").read_text())
        src = stats["by_category"].get(category or "", {})
        from agent.marketplace_port import PriceQuantiles

        def q(x):
            return PriceQuantiles(**x) if x else None
        return MarketStats(category=category, experience_level=experience_level, fixed_budget=q(src.get("fixed_budget")),
                           hourly_high=q(src.get("hourly_high")), hourly_low=q(src.get("hourly_low")))

    async def list_proposals(self, status=None) -> list[Proposal]:
        d = await self._call("list_proposals", {"status": status})
        return [_proposal(p) for p in (_pick(d, "proposals", "items", default=[]) or [])]

    async def get_proposal(self, proposal_id: str) -> Proposal:
        return _proposal(await self._call("get_proposal", {"proposal_id": proposal_id}))

    async def list_threads(self) -> list[Thread]:
        d = await self._call("list_threads", {})
        return [Thread(thread_id=str(_pick(t, "id", "room_id", "thread_id")), job_title=_pick(t, "title", "topic"))
                for t in (_pick(d, "threads", "rooms", "items", default=[]) or [])]

    async def get_thread(self, thread_id: str) -> Thread:
        d = await self._call("get_thread", {"thread_id": thread_id, "room_id": thread_id})
        msgs = [Message(message_id=str(_pick(m, "id", "message_id", default=i)),
                        sender="freelancer" if _pick(m, "is_mine", "from_me", default=False) else "client",
                        text=str(_pick(m, "text", "message", "body", default="")), at=_pick(m, "created_at", "at"))
                for i, m in enumerate(_pick(d, "messages", "items", default=[]) or [])]
        return Thread(thread_id=thread_id, messages=msgs)

    async def list_events(self, after: int = 0) -> list[MarketEvent]:
        # No event feed over MCP: the worker diffs list_proposals / list_threads instead.
        return []

    # ------------------------------------------------------------ writes (draft-only)
    async def create_proposal_draft(self, req: ProposalDraftRequest, idempotency_key: str, dry_run: bool = False):
        if dry_run:
            job = await self.get_job(req.job_id)
            bal = await self.get_connects_balance()
            return DryRunPreview(action="create_proposal_draft", would_send=req.model_dump(),
                                 connects_cost=job.connects_cost + req.boost_connects,
                                 connects_balance_after=bal.balance - job.connects_cost - req.boost_connects,
                                 policy_version="upwork-policy-pack")
        d = await self._call("create_proposal_draft", {
            "job_id": req.job_id, "cover_letter": req.cover_letter, "bid_amount": req.bid_amount,
            "screening_answers": req.screening_answers, "idempotency_key": idempotency_key})
        p = _proposal(_pick(d, "proposal", default=d) | {"job_id": req.job_id, "cover_letter": req.cover_letter,
                                                         "bid_amount": req.bid_amount})
        return p.model_copy(update={"status": "draft"})

    async def submit_proposal(self, proposal_id: str, idempotency_key: str, dry_run: bool = False):
        """Never auto-confirms. The draft already lives on Upwork; the user confirms it on upwork.com."""
        preview = DryRunPreview(action="submit_proposal",
                                would_send={"proposal_id": proposal_id,
                                            "note": "Confirm this draft on upwork.com; Connects are spent there."})
        if dry_run:
            return preview
        p = await self.get_proposal(proposal_id)
        return p.model_copy(update={"status": "draft"})

    async def send_message(self, thread_id: str, text: str, idempotency_key: str, dry_run: bool = False):
        if dry_run:
            return DryRunPreview(action="send_message", would_send={"thread_id": thread_id, "text": text})
        d = await self._call("send_message", {"thread_id": thread_id, "room_id": thread_id, "text": text,
                                              "idempotency_key": idempotency_key})
        return Message(message_id=str(_pick(d, "id", "message_id", default=idempotency_key)), sender="freelancer",
                       text=text, at=_pick(d, "created_at"))


def _job_summary(j: dict) -> JobSummary:
    budget = _pick(j, "budget", "amount", "fixed_price")
    if isinstance(budget, dict):
        budget = _pick(budget, "amount", "max", "value")
    hourly = _pick(j, "hourly_budget", "hourly_rate", "hourlyBudget")
    lo = hi = None
    if isinstance(hourly, dict):
        lo, hi = _pick(hourly, "min", "low"), _pick(hourly, "max", "high")
    ptype = "hourly" if (hourly or str(_pick(j, "type", "job_type", default="")).lower().startswith("hour")) else "fixed"
    desc = str(_pick(j, "description", "snippet", "content", default=""))
    skills = _pick(j, "skills", "required_skills", default=[]) or []
    skills = [s if isinstance(s, str) else str(_pick(s, "name", "prettyName", default="")) for s in skills]
    return JobSummary(job_id=str(_pick(j, "id", "job_id", "ciphertext")), title=str(_pick(j, "title", default="")),
                      snippet=desc[:280], skills=[s for s in skills if s], category=_pick(j, "category"),
                      experience_level=_pick(j, "experience_level", "contractorTier"), payment_type=ptype,
                      budget=float(budget) if budget else None, hourly_low=lo, hourly_high=hi,
                      connects_cost=int(_pick(j, "connects_cost", "connectPrice", "connects", default=0) or 0),
                      client_id=_pick(j, "client_id", "client", default=None) if not isinstance(_pick(j, "client"), dict)
                      else str(_pick(j["client"], "id", default="")), country=_pick(j, "country", "client_country"),
                      posted_at=_pick(j, "posted_at", "createdDateTime", "publishedDateTime"))


def _proposal(p: dict) -> Proposal:
    status = str(_pick(p, "status", default="draft")).lower()
    status = {"pending": "submitted", "active": "submitted", "archived": "lost", "declined": "lost",
              "hired": "hired", "offer": "interview"}.get(status, status)
    if status not in {"draft", "submitted", "viewed", "replied", "interview", "hired", "lost"}:
        status = "submitted"
    return Proposal(proposal_id=str(_pick(p, "id", "proposal_id", default="")), job_id=str(_pick(p, "job_id", default="")),
                    status=status, cover_letter=str(_pick(p, "cover_letter", "coverLetter", default="")),
                    bid_amount=float(_pick(p, "bid_amount", "amount", "charge_rate", default=0) or 0))
