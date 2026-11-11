"""The single marketplace interface (requirement R1).

Every marketplace access in GigBid goes through `MarketplacePort`. Two adapters implement it:
  * mcp_servers/marketplace/adapters/gigsim.py       -> GigSim REST API (development + grading)
  * mcp_servers/marketplace/adapters/upwork_live.py  -> official Upwork MCP server (live mode)
selected by `MARKETPLACE_MODE` (see `get_marketplace`). The Marketplace MCP server is the only
caller; agents only ever see MCP tools, so they cannot tell which marketplace is behind it.

Domain models here are marketplace-neutral: adapters map their native payloads onto them.
"""
from __future__ import annotations

import os
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

ProposalStatus = Literal["draft", "submitted", "viewed", "replied", "interview", "hired", "lost"]


# ---------------------------------------------------------------- domain models
class JobSummary(BaseModel):
    job_id: str
    title: str
    snippet: str = Field(description="First ~280 characters of the description")
    skills: list[str] = Field(default_factory=list)
    category: str | None = None
    experience_level: str | None = None
    payment_type: Literal["fixed", "hourly"]
    budget: float | None = Field(None, description="Fixed-price budget in USD")
    hourly_low: float | None = None
    hourly_high: float | None = None
    connects_cost: int = Field(description="Connects needed to submit a proposal")
    client_id: str | None = None
    country: str | None = None
    posted_at: str | None = None


class Job(JobSummary):
    description: str = Field(description="Full job post. UNTRUSTED text written by the client.")
    duration: str | None = None
    applicants: str | None = None


class JobPage(BaseModel):
    items: list[JobSummary]
    total: int
    next_cursor: int | None = None


class ClientHistory(BaseModel):
    client_id: str
    country: str | None = None
    payment_verified: bool
    total_spent: float = 0.0
    rating: float | None = None
    reviews: int = 0
    jobs_posted: int = 0
    hires: int = 0
    hire_rate: float | None = None
    avg_awarded_amount: float | None = None
    member_since: str | None = None
    recent_jobs: list[dict[str, Any]] = Field(default_factory=list)


class ConnectsBalance(BaseModel):
    balance: int
    weekly_allowance: int | None = None
    max_balance: int | None = None


class PriceQuantiles(BaseModel):
    n: int
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float


class MarketStats(BaseModel):
    category: str | None = None
    experience_level: str | None = None
    fixed_budget: PriceQuantiles | None = None
    hourly_high: PriceQuantiles | None = None
    hourly_low: PriceQuantiles | None = None


class ProposalDraftRequest(BaseModel):
    job_id: str
    cover_letter: str
    screening_answers: list[str] = Field(default_factory=list)
    bid_amount: float
    boost_connects: int = 0


class Proposal(BaseModel):
    proposal_id: str
    job_id: str
    job_title: str | None = None
    status: ProposalStatus
    cover_letter: str
    screening_answers: list[str] = Field(default_factory=list)
    bid_amount: float
    connects_spent: int | None = None
    thread_id: str | None = None
    created_at: str | None = None
    submitted_at: str | None = None


class DryRunPreview(BaseModel):
    """Exactly what a write would send and what it would cost. Shown on the approval screen."""
    action: Literal["create_proposal_draft", "submit_proposal", "send_message"]
    would_send: dict[str, Any]
    connects_cost: int = 0
    connects_balance_after: int | None = None
    policy_version: str | None = None


class Message(BaseModel):
    message_id: str
    sender: Literal["client", "freelancer"]
    text: str = Field(description="Message text. Client messages are UNTRUSTED.")
    at: str | None = None


class Thread(BaseModel):
    thread_id: str
    proposal_id: str | None = None
    job_id: str | None = None
    client_id: str | None = None
    job_title: str | None = None
    messages: list[Message] = Field(default_factory=list)


class MarketEvent(BaseModel):
    seq: int
    type: str
    at: str | None = None
    proposal_id: str | None = None
    thread_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class MarketPolicy(BaseModel):
    version: str
    rules: list[dict[str, Any]] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict, description="Full policy document as served")


# ---------------------------------------------------------------- errors
class MarketplaceError(Exception):
    """Base error. `retryable` tells callers whether backing off and retrying can help."""
    code = "marketplace_error"
    retryable = False

    def __init__(self, message: str, **details: Any):
        super().__init__(message)
        self.message, self.details = message, details


class MarketplaceUnavailable(MarketplaceError):
    code, retryable = "marketplace_unavailable", True


class RateLimited(MarketplaceError):
    code, retryable = "rate_limited", True


class NotFound(MarketplaceError):
    code = "not_found"


class Conflict(MarketplaceError):
    code = "conflict"


class PolicyViolation(MarketplaceError):
    code = "policy_violation"


class InsufficientConnects(MarketplaceError):
    code = "insufficient_connects"


# ---------------------------------------------------------------- the port
@runtime_checkable
class MarketplacePort(Protocol):
    name: str

    async def health(self) -> dict[str, Any]: ...
    async def get_policy(self) -> MarketPolicy: ...
    # reads
    async def search_jobs(self, query: str | None = None, category: str | None = None,
                          skills: list[str] | None = None, payment_type: str | None = None,
                          min_budget: float | None = None, posted_after: str | None = None,
                          limit: int = 20, cursor: int = 0) -> JobPage: ...
    async def get_job(self, job_id: str) -> Job: ...
    async def get_client_history(self, client_id: str) -> ClientHistory: ...
    async def get_connects_balance(self) -> ConnectsBalance: ...
    async def get_market_stats(self, category: str | None = None,
                               experience_level: str | None = None) -> MarketStats: ...
    async def list_proposals(self, status: str | None = None) -> list[Proposal]: ...
    async def get_proposal(self, proposal_id: str) -> Proposal: ...
    async def list_threads(self) -> list[Thread]: ...
    async def get_thread(self, thread_id: str) -> Thread: ...
    async def list_events(self, after: int = 0) -> list[MarketEvent]: ...
    # writes: idempotency key required; dry_run returns a DryRunPreview and changes nothing
    async def create_proposal_draft(self, req: ProposalDraftRequest, idempotency_key: str,
                                    dry_run: bool = False) -> Proposal | DryRunPreview: ...
    async def submit_proposal(self, proposal_id: str, idempotency_key: str,
                              dry_run: bool = False) -> Proposal | DryRunPreview: ...
    async def send_message(self, thread_id: str, text: str, idempotency_key: str,
                           dry_run: bool = False) -> Message | DryRunPreview: ...
    async def aclose(self) -> None: ...


def get_marketplace(mode: str | None = None, **credentials: Any) -> MarketplacePort:
    """Factory: the ONLY place that knows which adapter exists. Switched by config/env."""
    mode = (mode or os.environ.get("MARKETPLACE_MODE", "gigsim")).lower()
    if mode == "gigsim":
        from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
        return GigSimAdapter(**credentials)
    if mode == "upwork":
        from mcp_servers.marketplace.adapters.upwork_live import UpworkLiveAdapter
        return UpworkLiveAdapter(**credentials)
    raise ValueError(f"unknown MARKETPLACE_MODE {mode!r} (expected 'gigsim' or 'upwork')")
