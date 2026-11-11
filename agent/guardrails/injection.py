"""Prompt-injection defence for untrusted text (job posts, client messages) - E4 / R9.

Layer 1 (here, deterministic): detect instruction-like text aimed at an AI and neutralise it before any LLM sees it.
Layer 2 (prompts): untrusted text is always wrapped by `wrap_untrusted` in a delimited block that the system
         prompt declares to be data, never instructions.
Layer 3 (architecture): no LLM node holds a write tool; writes need human approval; compliance re-checks output.
Known gap (documented in the report): paraphrased or non-English attacks that avoid these patterns get past layer 1
and are left to layers 2-3.
"""
from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel, Field

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("override", re.compile(r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|any|your)\b"
                            r"[^.\n]{0,30}\b(instructions?|rules?|prompts?|polic(y|ies)|guidelines?)", re.IGNORECASE)),
    ("addressed_to_ai", re.compile(r"\b(note|message|instruction)s?\s+(to|for)\s+(any\s+)?(ai|llm|assistant|agent|bot|gpt|chatgpt|claude)s?\b", re.IGNORECASE)),
    ("ai_role_tag", re.compile(r"(\[|<|\(|^|\n)\s*(system|assistant|ai agent instruction|developer)\s*(\]|>|\)|:)", re.IGNORECASE)),
    ("mode_switch", re.compile(r"\byou are now\b|\b(admin|developer|god|jailbreak|dan)\s+mode\b", re.IGNORECASE)),
    ("exfiltrate", re.compile(r"\b(print|reveal|show|output|repeat)\b[^.\n]{0,30}\b(system prompt|instructions|tools you have|api key)", re.IGNORECASE)),
    ("bypass_approval", re.compile(r"\b(without|skip|bypass)\b[^.\n]{0,25}\b(human|review|approval|confirmation)\b", re.IGNORECASE)),
    ("spend", re.compile(r"\bspend\b[^.\n]{0,20}\b(all|every|max(imum)?)\b[^.\n]{0,15}\bconnects\b", re.IGNORECASE)),
    ("fabricate", re.compile(r"\b(state|claim|say|write)\b[^.\n]{0,30}\b(you|the applicant|freelancer)\b[^.\n]{0,20}"
                             r"\b(has|have|had|worked)\b[^.\n]{0,40}\b(years?|experience|google|meta|microsoft)", re.IGNORECASE)),
    ("contact_exfil", re.compile(r"\b(put|include|add|share|send)\b[^.\n]{0,40}\b(personal\s+)?(email|phone|whats ?app|telegram|wallet)"
                                 r"[^.\n]{0,40}\b(proposal|first line|reply|message)\b", re.IGNORECASE)),
    ("hidden_html", re.compile(r"<!--.*?-->", re.DOTALL)),
]
ZERO_WIDTH = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")


class InjectionReport(BaseModel):
    detected: bool
    matches: list[str] = Field(default_factory=list, description="pattern ids that fired")
    excerpts: list[str] = Field(default_factory=list)
    sanitized: str


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return ZERO_WIDTH.sub("", text)


def scan(text: str) -> InjectionReport:
    t = normalise(text)
    matches, excerpts = [], []
    spans = []
    for pid, pat in PATTERNS:
        for m in pat.finditer(t):
            matches.append(pid)
            excerpts.append(t[max(0, m.start() - 20): m.end() + 40].strip()[:160])
            spans.append((m.start(), m.end()))
    sanitized = t
    if spans:
        # neutralise whole sentences containing an injection, keep the rest of the post intact
        sents = re.split(r"(?<=[.!?])\s+|\n+", t)
        bad = [s for s in sents if any(p.search(s) for _, p in PATTERNS)]
        for s in bad:
            sanitized = sanitized.replace(s, "[removed: instruction addressed to an AI]")
        sanitized = PATTERNS[-1][1].sub("[removed: hidden comment]", sanitized)
    return InjectionReport(detected=bool(matches), matches=sorted(set(matches)), excerpts=excerpts[:5],
                           sanitized=sanitized)


def wrap_untrusted(kind: str, text: str) -> str:
    """Delimit third-party text. The tag name includes a fixed nonce-like suffix the attacker cannot predict
    from the post alone, and any closing tag inside the text is escaped."""
    tag = f"untrusted_{kind}_7f3a"
    safe = text.replace(f"</{tag}>", f"</ {tag}>")
    return f"<{tag}>\n{safe}\n</{tag}>"
