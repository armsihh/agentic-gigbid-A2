"""Long-term memory on a LangGraph store (Postgres in deployment, in-memory in tests). Writes go ONLY through
`MemoryManager`, which applies agent/memory/promotion_rules.py. Raw tool output never enters these namespaces.

Namespaces (per user):
  ("memory", user, "style")            promoted style rules           <- shown in the UI memory viewer, deletable
  ("memory", user, "style_candidates") candidate rules + support      (bookkeeping, not used by the writer)
  ("memory", user, "outcome_stats")    aggregate counts per category/feature (numbers only)
  ("memory", user, "outcome")          promoted outcome insights      <- shown in the UI, deletable
"""
from __future__ import annotations

import time
from typing import Any

from langgraph.store.base import BaseStore

from agent.memory.promotion_rules import (
    StyleCandidate,
    contradicted,
    outcome_insight,
    proposal_features,
    should_promote_style,
    style_candidates,
)

REPLIED = {"replied", "interview", "hired"}


def ns(user: str, kind: str) -> tuple[str, ...]:
    return ("memory", user, kind)


class MemoryManager:
    def __init__(self, store: BaseStore):
        self.store = store

    # ------------------------------------------------------------ style
    def record_edit(self, user: str, thread_id: str, original: str, edited: str,
                    protected_terms: set[str] | None = None) -> list[str]:
        """Observe one human edit. Returns the keys of rules promoted by this edit."""
        promoted = []
        cands = style_candidates(original, edited, protected_terms)
        # contradictions: user re-added a phrase that is a pending/promoted ban
        for item in self.store.search(ns(user, "style_candidates"), limit=1000):
            c = StyleCandidate(item.value["kind"], item.value["value"])
            if contradicted(c, original, edited):
                v = item.value | {"contradictions": item.value.get("contradictions", 0) + 1}
                self.store.put(ns(user, "style_candidates"), item.key, v)
                self.store.delete(ns(user, "style"), item.key)  # demote
        for c in cands:
            cur = self.store.get(ns(user, "style_candidates"), c.key)
            v = cur.value if cur else {"kind": c.kind, "value": c.value, "threads": [], "contradictions": 0}
            if thread_id not in v["threads"]:
                v["threads"] = [*v["threads"], thread_id]
            self.store.put(ns(user, "style_candidates"), c.key, v)
            if should_promote_style(set(v["threads"]), v["contradictions"]) and not self.store.get(ns(user, "style"), c.key):
                self.store.put(ns(user, "style"), c.key, {
                    "rule": c.as_rule(), "kind": c.kind, "value": c.value, "support_threads": v["threads"],
                    "promoted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "promotion_rule": f">= 3 distinct threads, 0 contradictions ({len(v['threads'])} threads)"})
                promoted.append(c.key)
        return promoted

    def style_rules(self, user: str) -> list[dict[str, Any]]:
        return [i.value | {"key": i.key} for i in self.store.search(ns(user, "style"), limit=200)]

    # ------------------------------------------------------------ outcomes
    def record_outcome(self, user: str, category: str, cover_letter: str, status: str,
                       price: float | None = None, band: tuple[float, float] | None = None) -> list[str]:
        """Observe one final marketplace outcome; update counts; (re)evaluate insights. Returns promoted keys."""
        replied = status in REPLIED
        changed = []
        for feat, val in proposal_features(cover_letter, price, band).items():
            key = f"{category}:{feat}"
            cur = self.store.get(ns(user, "outcome_stats"), key)
            arms = dict(cur.value["arms"]) if cur else {}
            r, n = arms.get(val, (0, 0))
            arms[val] = (r + int(replied), n + 1)
            self.store.put(ns(user, "outcome_stats"), key, {"category": category, "feature": feat, "arms": arms})
            ins = outcome_insight(feat, {k: tuple(v) for k, v in arms.items()})
            if ins:
                text = (f"In {category}, proposals with {feat.replace('_', ' ')} = {ins['better']} got replies "
                        f"{ins['reply_rate_better']:.0%} of the time vs {ins['reply_rate_worse']:.0%} for {ins['worse']} "
                        f"(n={ins['n_better']}/{ins['n_worse']}).")
                self.store.put(ns(user, "outcome"), key, ins | {"category": category, "insight": text,
                                                                "promotion_rule": "both arms n>=10, Wilson 90% CIs disjoint"})
                changed.append(key)
            else:
                self.store.delete(ns(user, "outcome"), key)
        return changed

    def outcome_insights(self, user: str, category: str | None = None) -> list[dict[str, Any]]:
        items = [i.value | {"key": i.key} for i in self.store.search(ns(user, "outcome"), limit=200)]
        return [i for i in items if category is None or i["category"] == category]

    # ------------------------------------------------------------ UI: view / delete
    def delete(self, user: str, kind: str, key: str) -> None:
        self.store.delete(ns(user, kind), key)
        if kind == "style":  # forgetting a rule also forgets its support, so it is not re-promoted next edit
            self.store.delete(ns(user, "style_candidates"), key)
