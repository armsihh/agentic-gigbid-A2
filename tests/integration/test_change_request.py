"""Change request (2 Nov 2026 platform policy update): crowded jobs cost +4 Connects; cover letters <= 1,500 chars.

GigBid absorbs it with config + 12 lines (see docs/CHANGE_REQUEST.md): pricing reads the marketplace's Connects cost
(so the surcharge flows into the expected-value check untouched), and the length limit lives in config, used by the
Writer prompt, the Critic and the Compliance Guard.
"""
from __future__ import annotations

import pytest

from agent.nodes.common import config
from agent.nodes.compliance import check
from gigsim.world import ROOT as GIGSIM_ROOT


@pytest.fixture
def updated_policy(gigsim, monkeypatch):
    monkeypatch.setenv("GIGSIM_POLICY_FILE", str(GIGSIM_ROOT / "gigsim" / "policy_2026-11-02.yaml"))
    gigsim.reset()
    gigsim.cfg["faults"].update(error_rate=0, slow_rate=0)
    yield gigsim
    monkeypatch.delenv("GIGSIM_POLICY_FILE")
    gigsim.reset()


def test_crowded_jobs_cost_more_and_pricing_sees_it(updated_policy, adapter_factory):
    import asyncio
    crowded = next(j for j in updated_policy.jobs.values() if j["status"] == "open" and j.get("applicants") == "50+")
    base = int(crowded["connects_cost"])
    job = asyncio.run(adapter_factory().get_job(crowded["job_id"]))
    assert job.connects_cost == base + 4                     # the platform applies the surcharge...
    from agent.nodes.pricing import quote
    q = quote(job.model_dump(), {}, {}, {"hourly_rate": 35, "min_fixed_budget": 300}, 0.8, job.connects_cost)
    assert q.connects_cost == base + 4                       # ...and GigBid's pricing uses it with no code change


def test_long_letters_rejected_by_platform_and_blocked_before_sending(updated_policy):
    from gigsim.world import GigSimError
    job = next(j for j in updated_policy.jobs.values() if j["status"] == "open" and j["category"] == "ai_ml")
    letter = "I built a ticket classifier that routed 81% of tickets. " * 40       # ~2,300 characters
    with pytest.raises(GigSimError) as e:
        updated_policy.create_draft("ai_ml", {"job_id": job["job_id"], "cover_letter": letter, "bid_amount": 300})
    assert e.value.code == "cover_letter_length"
    v = check(letter)
    assert not v.allowed and any(x.rule_id == "concise_proposals" for x in v.violations)
    assert config()["compliance"]["proposal_length"]["max_chars"] == 1500
