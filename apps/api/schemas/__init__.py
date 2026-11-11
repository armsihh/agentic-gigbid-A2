"""Request / response models. The web client is generated from the OpenAPI schema these produce."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class Register(Credentials):
    persona: Literal["ai_ml", "web_dev", "data_analysis"] = "ai_ml"


class Me(BaseModel):
    id: str
    email: str
    persona: str
    marketplace: str
    settings: dict[str, Any]


class Autonomy(BaseModel):
    auto_skip_low_fit: bool = False      # may auto-skip; GigBid never auto-sends


class UserSettings(BaseModel):
    persona: Literal["ai_ml", "web_dev", "data_analysis"] | None = None
    marketplace: Literal["gigsim", "upwork"] | None = None
    hourly_rate: float | None = Field(None, gt=0, le=1000)
    min_fixed_budget: float | None = Field(None, ge=0, le=1_000_000)
    weekly_connects_budget: int | None = Field(None, ge=0, le=1000)
    autonomy: Autonomy | None = None
    budgets: dict[str, float] | None = None


class SavedSearchIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    query: str | None = None
    category: Literal["ai_ml", "web_dev", "data_analysis", "other"] | None = None
    skills: list[str] = Field(default_factory=list)
    payment_type: Literal["fixed", "hourly"] | None = None
    min_budget: float | None = None
    interval_minutes: int = Field(60, ge=5, le=1440)


class SavedSearchOut(SavedSearchIn):
    id: int
    last_run_at: str | None = None


class JobRow(BaseModel):
    job_id: str
    thread_id: str
    title: str
    category: str | None
    status: str
    stage: str
    action: str | None
    fit: float | None
    risk: float | None
    risk_level: str | None
    price: float | None
    connects_cost: int | None
    summary: dict[str, Any]
    updated_at: str


class JobDetail(BaseModel):
    job: dict[str, Any]
    status: str | None
    halt: str | None = None
    job_spec: dict[str, Any] | None = None
    risk_report: dict[str, Any] | None = None
    fit_report: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None
    price: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    trace: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    has_draft: bool = False
    pending_approval: bool = False


class Studio(BaseModel):
    thread_id: str
    job: dict[str, Any]
    draft: dict[str, Any] | None
    claims: list[dict[str, Any]] = Field(default_factory=list)
    verification: dict[str, Any] | None = None
    critiques: list[dict[str, Any]] = Field(default_factory=list)
    compliance: dict[str, Any] | None = None
    price: dict[str, Any] | None = None
    risk_report: dict[str, Any] | None = None
    dry_run_preview: dict[str, Any] | None = None
    pending_approval: bool = False
    status: str | None = None


class ApprovalIn(BaseModel):
    action: Literal["approve", "edit", "reject"]
    edited_cover_letter: str | None = Field(None, max_length=5000)
    reason: str | None = Field(None, max_length=2000)


class PendingApproval(BaseModel):
    thread_id: str
    kind: str
    title: str
    created_at: str | None = None


class RunOut(BaseModel):
    id: str
    thread_id: str
    kind: str
    status: str
    trace_id: str
    started_at: str
    finished_at: str | None
    latency_s: float | None
    tokens: int
    cost_usd: float
    events: list[dict[str, Any]]
    error: str | None
    trace_url: str | None = None


class RunStarted(BaseModel):
    run_id: str
    thread_id: str | None = None


class ParagraphIn(BaseModel):
    index: int = Field(ge=0, le=20)
    instruction: str = Field("Make it more specific to the client's need.", max_length=500)


class Health(BaseModel):
    api: str
    marketplace: str
    marketplace_detail: str | None = None
    mode: str
    servers: dict[str, Any] = Field(default_factory=dict)


class MemoryItem(BaseModel):
    kind: Literal["style", "outcome"]
    key: str
    text: str
    detail: dict[str, Any]


class Analytics(BaseModel):
    by_category: list[dict[str, Any]]
    connects: dict[str, Any]
    cost_latency: dict[str, Any]
    top_rejection_reasons: list[dict[str, Any]]
    funnel: dict[str, int]
