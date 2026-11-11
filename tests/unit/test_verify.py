"""Claim verification (B3): supported claims kept, fabricated facts removed, plans not treated as claims."""
from __future__ import annotations

import pytest

from rag.verify import ClaimVerifier, Evidence, is_claim, split_sentences

EVIDENCE = [
    Evidence(evidence_id="ai_ml-cs-ticket-triage#2", text=(
        "Support ticket triage classifier - Outcome. Routed 81% of tickets automatically at 94% precision; "
        "manual routing time fell by about 70%.")),
    Evidence(evidence_id="ai_ml-cs-ticket-triage#1", text=(
        "Fine-tuned a DistilBERT classifier on 38k historical tickets for a UK SaaS helpdesk company.")),
]


def test_claim_detection():
    assert is_claim("I built a ticket triage classifier that routed 81% of tickets.")
    assert not is_claim("I would start with a baseline and an error analysis.")
    assert not is_claim("Happy to chat this week.")
    assert len(split_sentences("Hi there. I built X for Y! Happy to chat.")) == 3


@pytest.fixture(scope="module")
def verifier():
    return ClaimVerifier(known_terms={"celery", "kubernetes", "distilbert", "pytorch"})


def test_supported_claim(verifier):
    c = verifier.check("I built a support ticket triage classifier that routed 81% of tickets automatically "
                       "at 94% precision.", EVIDENCE)
    assert c.label == "supported", c


def test_fabricated_number_is_not_supported(verifier):
    c = verifier.check("I built a ticket classifier that routed 99% of tickets automatically.", EVIDENCE)
    assert c.label != "supported" and "99%" in c.missing_facts


def test_fabricated_years_and_tool_are_caught(verifier):
    c = verifier.check("I have 10 years of experience running Kubernetes clusters for Google.", EVIDENCE)
    assert c.label == "unsupported"


def test_verify_removes_unsupported_before_critic(verifier):
    draft = ("Hi - you need ticket routing. I fine-tuned a DistilBERT classifier on 38k historical tickets. "
             "I have 10 years of experience running Kubernetes clusters for Google. I would start with a baseline.")
    rep = verifier.verify(draft, EVIDENCE)
    assert any("Kubernetes" in r for r in rep.removed)
    assert "DistilBERT" in rep.cleaned_draft and "Kubernetes" not in rep.cleaned_draft
    assert "I would start with a baseline." in rep.cleaned_draft
    assert 0 < rep.unsupported_rate < 1
