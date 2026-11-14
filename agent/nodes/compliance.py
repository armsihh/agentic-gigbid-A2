"""Compliance Guard: enforce the policy pack on outgoing text. Removes contact details and guarantees, blocks
off-platform / free-work content and invented claims, with a reason shown in the UI. Deterministic first pass
(always runs, no model call); rules come from agent/config.yaml `compliance` + the marketplace policy version."""
from __future__ import annotations

import re

from agent.guardrails.injection import scan
from agent.handoffs import ComplianceVerdict, Violation
from agent.nodes.common import config, step

CONTACT = [re.compile(p, re.IGNORECASE) for p in (
    r"[\w.+-]+@[\w-]+(\.[\w-]+)+", r"(?<!\d)\+?\d[\d\s().-]{8,}\d(?!\d)", r"\b(whats ?app|telegram|skype|signal|wechat)\b",
    r"\b(linkedin\.com|calendly\.com|t\.me)/\S+")]
OFF_PLATFORM = re.compile(r"\b(outside (of )?(upwork|the platform)|pay (me )?directly|bank transfer|paypal|crypto|usdt)\b", re.IGNORECASE)
FREE_WORK = re.compile(r"\b(for free|free of charge|unpaid|no charge)\b", re.IGNORECASE)
YEARS = re.compile(r"\b(\d{2,})\+?\s*years?\b", re.IGNORECASE)


def _sentences(t: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", t) if s.strip()]


def check(text: str, profile: dict | None = None, policy_version: str | None = None) -> ComplianceVerdict:
    cfg = config()["compliance"]
    violations: list[Violation] = []
    redacted = text
    for s in _sentences(text):
        if any(p.search(s) for p in CONTACT):
            violations.append(Violation(rule_id="contact_details", excerpt=s[:160], action="removed"))
            redacted = redacted.replace(s, "")
        elif any(re.search(p, s, re.IGNORECASE) for p in cfg["guarantee_patterns"]):
            violations.append(Violation(rule_id="guarantees", excerpt=s[:160], action="removed"))
            redacted = redacted.replace(s, "")
    # block rules run on the ORIGINAL text: redacting a contact detail must not hide the off-platform intent
    # in the same sentence ("Email me at x@y.com and pay me directly")
    for s in _sentences(text):
        if OFF_PLATFORM.search(s):
            violations.append(Violation(rule_id="no_off_platform", excerpt=s[:160], action="blocked"))
        if FREE_WORK.search(s):
            violations.append(Violation(rule_id="no_free_work", excerpt=s[:160], action="blocked"))
        m = YEARS.search(s)
        if m and profile and int(m.group(1)) > int(profile.get("years", 0)):
            violations.append(Violation(rule_id="no_fabrication", excerpt=s[:160], action="blocked"))
    if len(text) > cfg["proposal_length"]["max_chars"] + 400:  # + room for screening answers in `text`
        violations.append(Violation(rule_id="concise_proposals", excerpt=f"{len(text)} characters", action="blocked"))
    if scan(text).detected:
        violations.append(Violation(rule_id="injection_echo", excerpt="draft repeats instructions aimed at AI tools",
                                    action="blocked"))
    blocked = [v for v in violations if v.action == "blocked"]
    redacted = re.sub(r"[ \t]{2,}", " ", re.sub(r"\n{3,}", "\n\n", redacted)).strip()
    return ComplianceVerdict(allowed=not blocked,
                             blocked_reason="; ".join(f"{v.rule_id}: \"{v.excerpt[:80]}\"" for v in blocked) or None,
                             violations=violations, redacted_text=redacted if violations else None,
                             policy_version=policy_version)


def make_compliance_node(deps):
    async def compliance(state: dict) -> dict:
        draft = state["draft"]
        text = draft["cover_letter"] + "\n\n" + "\n".join(a["answer"] for a in draft.get("screening_answers", []))
        v = check(text, deps.profile)
        out: dict = {"compliance": v.model_dump(),
                     "trace": [step("compliance", "allowed" if v.allowed else f"BLOCKED: {v.blocked_reason}")]}
        if v.redacted_text is not None and v.allowed:
            cl = check(draft["cover_letter"], deps.profile)
            out["draft"] = {**draft, "cover_letter": cl.redacted_text or draft["cover_letter"]}
        if not v.allowed:
            out["status"] = "blocked"
        return out
    return compliance
