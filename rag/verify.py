"""Claim verification (B3, R5): split a draft into claims, check each against portfolio evidence, label it
supported / partly_supported / unsupported, and remove unsupported claims before the Critic sees the draft.

Only sentences that assert something about the freelancer's experience are claims ("I built...", "my ...",
numbers, named tools). Plans and pleasantries ("I would start with...", "Happy to chat") are not checked.

Default judge (no LLM, deterministic, cheap):
  1. relevance = best cross-encoder score between the claim and any evidence chunk (sigmoid)
  2. hard facts = numbers (81%, 4,000, 3.4x) and named tools in the claim must appear in that evidence
  supported:        relevance >= high and every hard fact found
  partly_supported: relevance >= low, or some hard facts missing
  unsupported:      otherwise
An LLM judge can be injected (`judge=`) and is calibrated against hand labels (evals/runners/judge_calibration.py).
"""
from __future__ import annotations

import math
import re
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field

from rag.index.dense import Reranker

Label = Literal["supported", "partly_supported", "unsupported"]

FIRST_PERSON_CLAIM = re.compile(
    r"\b(i|i've|i have|i'd|my|we)\b.*\b(built|build|created|developed|designed|deployed|delivered|shipped|led|"
    r"worked|trained|fine-tuned|automated|migrated|integrated|implemented|reduced|increased|improved|cut|saved|"
    r"raised|lifted|wrote|used|have|has|had|experience|years|clients?|projects?)\b", re.IGNORECASE)
PLAN = re.compile(r"\b(i would|i'd start|i will|i'll|i can|i plan|happy to|let's|looking forward|would love)\b", re.IGNORECASE)
NUMBER = re.compile(r"\d[\d,.]*\s*(%|x\b|k\b|ms\b|s\b|fps\b|hours?|days?|weeks?|months?|years?)?", re.IGNORECASE)
YEARS_EXPERIENCE = re.compile(r"\b(\d+)\+?\s*years?\b", re.IGNORECASE)


class Evidence(BaseModel):
    evidence_id: str
    text: str


class ClaimCheck(BaseModel):
    claim: str
    label: Label
    evidence_ids: list[str] = Field(default_factory=list)
    relevance: float
    missing_facts: list[str] = Field(default_factory=list)
    reason: str


class VerificationReport(BaseModel):
    claims: list[ClaimCheck]
    unsupported_rate: float
    cleaned_draft: str
    removed: list[str]


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])|\n+", text.strip())
    return [p.strip() for p in parts if p and len(p.strip()) > 3]


def is_claim(sentence: str) -> bool:
    s = sentence.strip()
    if PLAN.search(s) and not re.search(r"\b(built|delivered|shipped|led|reduced|increased)\b", s, re.IGNORECASE):
        return False
    return bool(FIRST_PERSON_CLAIM.search(s) or NUMBER.search(s))


def hard_facts(claim: str, known_terms: set[str]) -> list[str]:
    facts = [m.group(0).strip().rstrip(".,") for m in NUMBER.finditer(claim) if re.search(r"\d", m.group(0))]
    low = claim.lower()
    facts += [t for t in known_terms if len(t) > 2 and re.search(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])", low)]
    return facts


def _norm(s: str) -> str:
    return re.sub(r"[\s,]", "", s.lower())


def _fact_in(fact: str, text: str) -> bool:
    if _norm(fact) in _norm(text):
        return True
    num = re.match(r"[\d.,]+", fact)
    return bool(num) and _norm(num.group(0)) in _norm(text) and len(num.group(0)) >= 2


class ClaimVerifier:
    def __init__(self, reranker: Reranker | None = None, high: float = 0.6, low: float = 0.3,
                 known_terms: set[str] | None = None,
                 judge: Callable[[str, list[Evidence]], tuple[Label, list[str], str]] | None = None):
        self.reranker = reranker or Reranker()
        self.high, self.low = high, low
        self.known_terms = {t.lower() for t in (known_terms or set())}
        self.judge = judge

    def check(self, claim: str, evidence: list[Evidence]) -> ClaimCheck:
        if self.judge is not None:
            label, ids, reason = self.judge(claim, evidence)
            return ClaimCheck(claim=claim, label=label, evidence_ids=ids, relevance=float("nan"), reason=reason)
        if not evidence:
            return ClaimCheck(claim=claim, label="unsupported", relevance=0.0, reason="no evidence retrieved")
        scores = self.reranker.score(claim, [e.text for e in evidence])
        order = sorted(range(len(evidence)), key=lambda i: -scores[i])
        best = 1 / (1 + math.exp(-scores[order[0]]))
        top = [evidence[i] for i in order[:3]]
        top_text = "\n".join(e.text for e in top)
        facts = hard_facts(claim, self.known_terms)
        missing = [f for f in facts if not _fact_in(f, top_text)]
        years = YEARS_EXPERIENCE.search(claim)
        if years and not _fact_in(years.group(0), top_text):
            missing.append(years.group(0))  # "10 years of experience" must be literally supported
        if best >= self.high and not missing:
            label, reason = "supported", "evidence matches and every number/tool appears in it"
        elif best >= self.low or (facts and len(missing) < len(facts)):
            label = "partly_supported"
            reason = f"related evidence, but not found in it: {', '.join(missing)}" if missing else "weak match"
        else:
            label, reason = "unsupported", "no evidence supports this claim"
        if missing and len(missing) == len(facts) and facts and best < self.high:
            label, reason = "unsupported", f"specific facts not in any evidence: {', '.join(missing)}"
        # a number the evidence does not contain is a fabricated result, however relevant the rest of the
        # sentence is ("routed 99% of tickets" when the evidence says 81%): never keep it
        numeric_missing = [m for m in missing if re.search(r"\d", m)]
        if numeric_missing:
            label, reason = "unsupported", f"number not in the evidence: {', '.join(numeric_missing)}"
        return ClaimCheck(claim=claim, label=label, evidence_ids=[e.evidence_id for e in top], relevance=round(best, 3),
                          missing_facts=missing, reason=reason)

    def verify(self, draft: str, evidence: list[Evidence]) -> VerificationReport:
        sentences = split_sentences(draft)
        checks = [self.check(s, evidence) for s in sentences if is_claim(s)]
        bad = {c.claim for c in checks if c.label == "unsupported"}
        kept = [s for s in sentences if s not in bad]
        rate = len(bad) / len(checks) if checks else 0.0
        return VerificationReport(claims=checks, unsupported_rate=round(rate, 3), cleaned_draft=" ".join(kept),
                                  removed=sorted(bad))


def verify_claims(draft: str, evidence: list[dict]) -> list[dict]:
    """Starter-kit signature, kept for compatibility."""
    ev = [Evidence(evidence_id=e.get("evidence_id") or e.get("id", "?"), text=e["text"]) for e in evidence]
    return [c.model_dump() for c in ClaimVerifier().verify(draft, ev).claims]
