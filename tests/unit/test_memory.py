"""Long-term memory only changes through explicit promotion rules (R7)."""
from __future__ import annotations

from langgraph.store.memory import InMemoryStore

from agent.memory.promotion_rules import outcome_insight, style_candidates
from agent.memory.store import MemoryManager

DRAFT = ("I am a passionate engineer and I hope this finds you well. I built a churn model for a telecom "
         "with a 3.4x top-decile lift. I would start with a baseline.")
EDIT = "I built a churn model for a telecom with a 3.4x top-decile lift. I would start with a baseline."


def test_candidates_from_one_edit():
    # deleting a whole sentence teaches "cut the opening", not a ban on every word in it (conservative)
    keys = {c.key for c in style_candidates(DRAFT, EDIT)}
    assert "drop_opening:first_sentence" in keys
    assert not any(k.startswith("ban_phrase:") for k in keys)
    # deleting a short phrase inside a sentence yields a phrase ban
    keys = {c.key for c in style_candidates("I built a robust, cutting-edge churn model.", "I built a churn model.")}
    assert "ban_phrase:robust cutting-edge" in keys


def test_style_rule_needs_three_distinct_threads():
    m = MemoryManager(InMemoryStore())
    assert m.record_edit("u", "t1", DRAFT, EDIT) == []
    assert m.record_edit("u", "t1", DRAFT, EDIT) == []          # same thread again does not count
    assert m.record_edit("u", "t2", DRAFT, EDIT) == []
    promoted = m.record_edit("u", "t3", DRAFT, EDIT)
    assert "drop_opening:first_sentence" in promoted
    rules = m.style_rules("u")
    assert rules and all("promotion_rule" in r for r in rules)
    assert all("I built a churn" not in str(r) for r in rules)  # raw edit text never stored as memory


def test_contradiction_demotes_and_blocks():
    m = MemoryManager(InMemoryStore())
    for t in ("t1", "t2", "t3"):
        m.record_edit("u", t, "I am passionate about data. I built X.", "I built X.")
    assert any("passionate" in r["value"] for r in m.style_rules("u"))
    m.record_edit("u", "t4", "I built X.", "I am passionate about data. I built X.")  # user re-adds it
    assert not any("passionate" in r["value"] for r in m.style_rules("u"))


def test_user_can_delete_a_rule():
    m = MemoryManager(InMemoryStore())
    for t in ("t1", "t2", "t3"):
        m.record_edit("u", t, DRAFT, EDIT)
    key = m.style_rules("u")[0]["key"]
    m.delete("u", "style", key)
    assert key not in {r["key"] for r in m.style_rules("u")}


def test_outcome_insight_needs_evidence():
    assert outcome_insight("cites_metric", {"yes": (3, 5), "no": (0, 5)}) is None        # too few
    assert outcome_insight("cites_metric", {"yes": (4, 20), "no": (3, 20)}) is None      # overlapping CIs
    ins = outcome_insight("cites_metric", {"yes": (12, 30), "no": (1, 30)})
    assert ins and ins["better"] == "yes"


def test_outcome_memory_promotes_from_counts_only():
    m = MemoryManager(InMemoryStore())
    good = "Hi - you need X. I cut costs 40% for a similar client. Happy to start."
    bad = "Dear Sir, I am a passionate hardworking person. I can do this job."
    for i in range(30):
        m.record_outcome("u", "ai_ml", good, "replied" if i % 5 < 2 else "lost")
        m.record_outcome("u", "ai_ml", bad, "lost")
    insights = m.outcome_insights("u", "ai_ml")
    assert insights and all("good" not in str(i) for i in insights)
    assert any(i["feature"] == "opening_style" and i["better"] == "specific" for i in insights)
