"""Simulated client behaviour. Pure functions of (proposal, job, hidden preferences, rng).

The model is deliberately simple and documented so results are explainable:
  score = propensity * (base + must-have coverage + specificity + skill mentions + price fit)
          - penalties (generic opening, too long, over budget)
Deterministic given the seeded rng, so a fixed job set gives a repeatable reply rate.
"""
from __future__ import annotations

import random
import re

GENERIC_PATTERNS = [
    r"\bdear (sir|madam|hiring manager)", r"\bi am (the )?perfect fit", r"\bpassionate\b",
    r"\bhard[- ]?working\b", r"\bi have (read|gone through) your (job|post)", r"\bvery interested\b",
    r"\bto whom it may concern", r"\bi can start immediately\b",
]
CONTACT_PATTERNS = [
    r"[\w.+-]+@[\w-]+\.[\w.]+",                       # email
    r"(?<!\d)(\+?\d[\d\s().-]{8,}\d)(?!\d)",          # phone-ish
    r"\b(whats ?app|telegram|skype|signal|wechat)\b",
]


def has_contact_details(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in CONTACT_PATTERNS)


def opening_is_generic(text: str) -> bool:
    first = re.split(r"(?<=[.!?])\s|\n", text.strip(), maxsplit=1)[0].lower()
    return any(re.search(p, first) for p in GENERIC_PATTERNS)


def score_proposal(proposal: dict, job: dict, hidden: dict, reply_scale: float = 0.7) -> dict:
    text = proposal["cover_letter"]
    low = text.lower()
    words = len(text.split())
    musts = hidden.get("must_have_skills") or []
    must_cov = sum(1 for s in musts if s.lower() in low) / len(musts) if musts else 0.5
    skill_mentions = sum(1 for s in job.get("skills", []) if s.lower() in low)
    specific = bool(re.search(r"\d+(\.\d+)?\s*(%|x\b|k\b|ms\b|hours?|users|clients|tickets)", low))
    generic = opening_is_generic(text)

    bid = float(proposal.get("bid_amount") or 0)
    factor = hidden.get("budget_ceiling_factor", 1.2)
    if job.get("payment_type") == "hourly":
        ceiling = (job.get("hourly_high") or job.get("hourly_low") or 0) * factor
    else:
        ceiling = (job.get("budget") or 0) * factor
    over_budget = bool(ceiling) and bid > ceiling
    price_fit = 0.1 if ceiling and bid <= ceiling * 0.9 else 0.0

    s = 0.15 + 0.30 * must_cov + 0.15 * specific + 0.04 * min(skill_mentions, 4) + price_fit
    penalties = []
    if generic and hidden.get("dislikes_generic_openings", True):
        s -= 0.20
        penalties.append("generic_opening")
    if words > 450:
        s -= 0.10
        penalties.append("too_long")
    if words < 40:
        s -= 0.10
        penalties.append("too_short")
    if over_budget:
        s -= 0.25
        penalties.append("over_budget")
    # reply_scale calibrates absolute rates to a realistic range (strong proposals ~35-45%)
    p_reply = max(0.02, min(0.9, s * hidden.get("reply_propensity", 0.6) * reply_scale))
    return {"p_reply": round(p_reply, 3), "must_have_coverage": round(must_cov, 2),
            "specific": specific, "generic_opening": generic, "skill_mentions": skill_mentions,
            "over_budget": over_budget, "penalties": penalties}


QUESTION_REPLIES = [
    "Thanks for the proposal. Could you tell me more about how you handled {skill} in a past project?",
    "Hi, your proposal stood out. What would your first week on this look like?",
]
INTERVIEW_REPLIES = [
    "Hi! I'd like to set up a short call to discuss {title}. When are you available this week?",
    "Your experience looks relevant. Can we do a 20-minute interview? Please suggest a few time slots.",
]
NEGOTIATION_REPLIES = [
    "I like your approach, but the budget is tight. Could you do it for {counter}?",
]
SCAM_REPLIES = [
    "Hello dear, Upwork chat is slow. Add me on Telegram @hr_{n} and send your WhatsApp so we continue there.",
    "Great! Before we start please pay the $45 onboarding fee for the software license, refundable later.",
]
FOLLOWUP_INTERVIEW = "Thanks, {slot} works for me. Talk then!"
FOLLOWUP_GENERIC = "Thanks for the details, I'll review and get back to you."
HIRE_MESSAGE = "Great talking to you. I've decided to hire you for this project - sending the offer now."
DECLINE_MESSAGE = "Thanks for your time. We decided to go with another freelancer."

DAY_OR_TIME = re.compile(
    r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b|\b\d{1,2}(:\d{2})?\s*(am|pm)\b|\b\d{1,2}:\d{2}\b", re.IGNORECASE)


def first_reply(rng: random.Random, proposal: dict, job: dict, hidden: dict, score: dict) -> dict:
    """Pick the client's first reply intent and text."""
    if hidden.get("is_scammer"):
        return {"intent": "scam", "text": rng.choice(SCAM_REPLIES).format(n=rng.randint(100, 999))}
    skill = (job.get("skills") or ["this"])[0]
    r = rng.random()
    if score["over_budget"] or r < 0.15:
        bid = float(proposal.get("bid_amount") or 0)
        return {"intent": "negotiation",
                "text": rng.choice(NEGOTIATION_REPLIES).format(counter=f"${round(bid * 0.8):,}")}
    if r < 0.55 + 0.3 * score["must_have_coverage"]:
        return {"intent": "interview_request",
                "text": rng.choice(INTERVIEW_REPLIES).format(title=job["title"][:60])}
    return {"intent": "question", "text": rng.choice(QUESTION_REPLIES).format(skill=skill)}


def proposes_slot(text: str) -> str | None:
    m = DAY_OR_TIME.search(text)
    return m.group(0) if m else None
