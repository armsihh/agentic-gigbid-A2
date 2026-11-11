"""Explicit promotion rules for long-term memory (R7, C2). Nothing reaches long-term memory except through here.

Two memories, both per user:

STYLE MEMORY (learned from the user's edits to drafts)
  observe:  each approved edit is diffed against the draft; the diff yields *candidate* style rules:
              ban_phrase   a word/phrase the user deleted        ("passionate", "I hope this finds you well")
              drop_opening the user deleted the first sentence
              shorter      the user cut >= 25% of the length
              sign_off     the user added the same closing line
  promote:  a candidate becomes a rule only when
              (1) it was seen in >= STYLE_MIN_SUPPORT distinct threads (default 3), AND
              (2) it was never contradicted (the user re-adding a banned phrase resets it), AND
              (3) for ban_phrase: the phrase is 1-6 words and not a skill/tool name the portfolio uses
            Raw edit text is NOT stored, only the minimal rule and the thread ids that support it.

OUTCOME MEMORY (what won or got replies, per job category)
  observe:  each marketplace outcome adds 1 to aggregate counts for (category, feature): features are proposal
            properties we control (opening_style, cites_metric, length_bucket, price_vs_band).
  promote:  an insight ("in ai_ml, openings that cite a metric get more replies") is promoted only when both
            arms have >= OUTCOME_MIN_N outcomes and the Wilson 90% intervals of the reply rates do not overlap.
            It is demoted again if a later update makes the intervals overlap.
"""
from __future__ import annotations

import difflib
import math
import re
from dataclasses import dataclass

STYLE_MIN_SUPPORT = 3
OUTCOME_MIN_N = 10
Z90 = 1.645
WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")


@dataclass(frozen=True)
class StyleCandidate:
    kind: str           # ban_phrase | drop_opening | shorter | sign_off
    value: str          # normalised phrase / description

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.value}"

    def as_rule(self) -> str:
        return {"ban_phrase": f'Never use the phrase "{self.value}".',
                "drop_opening": "Cut the generic first sentence; open with the client's need.",
                "shorter": "Keep proposals at least 25% shorter than the first draft.",
                "sign_off": f'End with: "{self.value}"'}[self.kind]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def style_candidates(original: str, edited: str, protected_terms: set[str] | None = None) -> list[StyleCandidate]:
    """Diff one draft against the user's edit and return candidate style rules (not yet promoted)."""
    protected = {t.lower() for t in (protected_terms or set())}
    out: set[StyleCandidate] = set()
    o_sent, e_sent = _sentences(original), _sentences(edited)
    if o_sent and e_sent and o_sent[0] != e_sent[0] and o_sent[0] not in edited:
        out.add(StyleCandidate("drop_opening", "first_sentence"))
    if len(edited) <= 0.75 * len(original):
        out.add(StyleCandidate("shorter", "25pct"))
    ow, ew = WORD.findall(original.lower()), WORD.findall(edited.lower())
    sm = difflib.SequenceMatcher(a=ow, b=ew, autojunk=False)
    for tag, i1, i2, _j1, _j2 in sm.get_opcodes():
        if tag in ("delete", "replace") and 1 <= i2 - i1 <= 6:
            phrase = " ".join(ow[i1:i2])
            if phrase not in edited.lower() and phrase not in protected and len(phrase) >= 4:
                out.add(StyleCandidate("ban_phrase", phrase))
    if e_sent and (not o_sent or e_sent[-1] != o_sent[-1]) and len(e_sent[-1].split()) <= 8:
        out.add(StyleCandidate("sign_off", e_sent[-1]))
    return sorted(out, key=lambda c: c.key)


def contradicted(candidate: StyleCandidate, original: str, edited: str) -> bool:
    """The user ADDED a phrase we were about to ban: evidence against the rule."""
    return (candidate.kind == "ban_phrase" and candidate.value in edited.lower()
            and candidate.value not in original.lower())


def should_promote_style(support_threads: set[str], contradictions: int) -> bool:
    return len(support_threads) >= STYLE_MIN_SUPPORT and contradictions == 0


def should_promote_style_edit(edit_count: int, consistent_pattern: bool) -> bool:
    """Starter-kit signature, kept for compatibility."""
    return edit_count >= STYLE_MIN_SUPPORT and consistent_pattern


# ---------------------------------------------------------------- outcome memory
def wilson(successes: int, n: int, z: float = Z90) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def outcome_insight(feature: str, arms: dict[str, tuple[int, int]]) -> dict | None:
    """arms: value -> (replies, n). Returns a promotable insight or None (rule above)."""
    ok = {v: rn for v, rn in arms.items() if rn[1] >= OUTCOME_MIN_N}
    if len(ok) < 2:
        return None
    rates = {v: (r / n, *wilson(r, n), n) for v, (r, n) in ok.items()}
    best = max(rates, key=lambda v: rates[v][0])
    worst = min(rates, key=lambda v: rates[v][0])
    if rates[best][1] <= rates[worst][2]:  # intervals overlap -> not enough evidence
        return None
    return {"feature": feature, "better": best, "worse": worst,
            "reply_rate_better": round(rates[best][0], 3), "reply_rate_worse": round(rates[worst][0], 3),
            "n_better": rates[best][3], "n_worse": rates[worst][3]}


def proposal_features(cover_letter: str, price: float | None = None, band: tuple[float, float] | None = None) -> dict[str, str]:
    """Features of a proposal we control, recorded with its outcome."""
    words = len(cover_letter.split())
    first = _sentences(cover_letter)[:1]
    generic = bool(first) and bool(re.search(r"dear|passionate|perfect fit|hard ?working|i have read", first[0], re.IGNORECASE))
    feats = {"opening_style": "generic" if generic else "specific",
             "cites_metric": "yes" if re.search(r"\d+(\.\d+)?\s*(%|x\b)", cover_letter) else "no",
             "length_bucket": "short" if words < 120 else ("medium" if words < 250 else "long")}
    if price is not None and band:
        feats["price_vs_band"] = "below" if price < band[0] else ("above" if price > band[1] else "inside")
    return feats
