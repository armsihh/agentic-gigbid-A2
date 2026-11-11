"""Structured hand-offs between agents (C3). Anything a later step decides on is one of these Pydantic
objects, never free text. They are also the JSON schemas LLM nodes are asked to fill (structured output).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------- Job Analyst
class Requirement(BaseModel):
    text: str = Field(description="One thing the client needs, in plain words, e.g. 'background job queue with Celery'")
    skills: list[str] = Field(default_factory=list, description="Skills/tools this requirement names or implies")
    must_have: bool = True


class Budget(BaseModel):
    type: Literal["fixed", "hourly", "unknown"] = "unknown"
    min: float | None = None
    max: float | None = None
    currency: str = "USD"


class ScreeningQuestion(BaseModel):
    question: str


class JobSpec(BaseModel):
    job_id: str
    title: str
    summary: str = Field("", description="One sentence: what the client wants built and why")
    deliverables: list[str] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    budget: Budget = Field(default_factory=Budget)
    timeline: str | None = None
    screening_questions: list[ScreeningQuestion] = Field(default_factory=list)
    hidden_needs: list[str] = Field(default_factory=list, description="Needs implied but not stated")
    category: str | None = None
    experience_level: str | None = None


# ---------------------------------------------------------------- Risk Assessor
RiskFlagType = Literal["scam", "free_work", "off_platform", "upfront_payment", "pii_request", "account_sharing",
                       "prompt_injection", "unverified_payment", "no_history", "budget_unrealistic", "duplicate",
                       "other"]


class RiskFlag(BaseModel):
    type: RiskFlagType
    severity: Literal["low", "medium", "high"]
    evidence: str = Field(description="Short quote or fact that triggered the flag")


class RiskReport(BaseModel):
    score: float = Field(ge=0, le=1, description="0 = safe, 1 = certainly a scam / do not engage")
    level: Literal["low", "medium", "high"] = "low"
    flags: list[RiskFlag] = Field(default_factory=list)
    client_quality: float | None = Field(None, ge=0, le=1, description="From payment, spend, rating, hire rate")
    injection_detected: bool = False
    explanation: str


# ---------------------------------------------------------------- Fit Matcher
class RequirementMatch(BaseModel):
    requirement: str
    status: Literal["covered", "partial", "missing"]
    evidence_ids: list[str] = Field(default_factory=list)
    note: str = ""


class FitReport(BaseModel):
    score: float = Field(ge=0, le=1)
    matches: list[RequirementMatch] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- decision + pricing
class BidDecision(BaseModel):
    action: Literal["bid", "watch", "skip"]
    reasons: list[str] = Field(default_factory=list)
    confidence: float = Field(0.5, ge=0, le=1)
    decided_by: Literal["rules", "llm", "autonomy_auto_skip", "human"] = "rules"


class PriceQuote(BaseModel):
    amount: float = Field(gt=0)
    type: Literal["fixed", "hourly"]
    currency: str = "USD"
    band_low: float | None = None
    band_high: float | None = None
    rationale: str
    connects_cost: int = 0
    connects_worth_it: bool = True
    expected_value_usd: float | None = Field(None, description="P(win) x amount - connects cost in USD")


# ---------------------------------------------------------------- writing + checks
class Claim(BaseModel):
    text: str
    evidence_ids: list[str] = Field(default_factory=list)


class ScreeningAnswer(BaseModel):
    question: str
    answer: str
    evidence_ids: list[str] = Field(default_factory=list)


class ProposalDraft(BaseModel):
    job_id: str
    cover_letter: str
    screening_answers: list[ScreeningAnswer] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list, description="Every experience claim and the evidence behind it")
    evidence_ids: list[str] = Field(default_factory=list)
    version: int = 1
    status: Literal["pending_review", "approved", "rejected", "sent"] = "pending_review"


class Critique(BaseModel):
    approve: bool
    grounding: int = Field(ge=1, le=5)
    personalisation: int = Field(ge=1, le=5)
    length_ok: bool
    issues: list[str] = Field(default_factory=list)
    revision_instructions: str = ""
    revision_number: int = 0


class Violation(BaseModel):
    rule_id: str
    excerpt: str
    action: Literal["removed", "blocked"]


class ComplianceVerdict(BaseModel):
    allowed: bool
    blocked_reason: str | None = None
    violations: list[Violation] = Field(default_factory=list)
    redacted_text: str | None = Field(None, description="Draft with contact details / guarantees removed")
    policy_version: str | None = None


# ---------------------------------------------------------------- human approval
class ApprovalDecision(BaseModel):
    action: Literal["approve", "edit", "reject"]
    edited_cover_letter: str | None = None
    edited_screening_answers: list[ScreeningAnswer] | None = None
    reason: str | None = Field(None, description="Required when rejecting")
    approver: str | None = None
