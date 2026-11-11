import os

os.environ["GIGSIM_ERROR_RATE"] = "0"
os.environ["GIGSIM_SLOW_RATE"] = "0"
os.environ["GIGSIM_RPM"] = "100000"

import pytest
from fastapi.testclient import TestClient

from gigsim.app import _buckets, app, world

H = {"Authorization": "Bearer dev-ai_ml"}
ADMIN = {"Authorization": "Bearer dev-admin"}
GOOD_LETTER = ("Hi - you need an NLP classifier. I built a support ticket triage model for a UK SaaS company "
               "that routed 81% of tickets automatically at 94% precision using Python and scikit-learn. "
               "I would start with a baseline and an error analysis.")


@pytest.fixture(autouse=True)
def fresh():
    world.reset()
    _buckets.clear()
    world.cfg["faults"].update(error_rate=0, slow_rate=0)
    world.cfg["rate_limit"]["requests_per_minute"] = 100000
    yield


c = TestClient(app)


def open_job(category="ai_ml"):
    r = c.get("/v1/jobs", params={"category": category, "limit": 50}, headers=H)
    assert r.status_code == 200
    # pick a fixed-price job with a real client (not a scam) for deterministic behaviour
    for j in r.json()["items"]:
        if j["payment_type"] == "fixed" and j["budget"] and not j["client_id"].startswith("cl-syn"):
            return j
    return r.json()["items"][0]


def test_auth_required():
    assert c.get("/v1/jobs").status_code == 401
    assert c.get("/v1/jobs", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_job_detail_hides_internal_fields():
    j = c.get(f"/v1/jobs/{open_job()['job_id']}", headers=H).json()
    for hidden in ("release_order", "must_have_skills", "is_scammer"):
        assert hidden not in j
    assert len(j["description"]) > 0


def test_client_profile_has_history_not_hidden_prefs():
    j = open_job()
    prof = c.get(f"/v1/clients/{j['client_id']}", headers=H).json()
    assert "payment_verified" in prof and "must_have_skills" not in prof


def test_draft_dry_run_previews_cost_without_creating():
    j = open_job()
    body = {"job_id": j["job_id"], "cover_letter": GOOD_LETTER, "bid_amount": j["budget"], "dry_run": True}
    r = c.post("/v1/proposals", json=body, headers=H).json()
    assert r["dry_run"] and r["would_create"]["connects_cost_on_submit"] == j["connects_cost"]
    assert c.get("/v1/proposals", headers=H).json()["items"] == []


def test_idempotent_draft_and_key_reuse_conflict():
    j = open_job()
    body = {"job_id": j["job_id"], "cover_letter": GOOD_LETTER, "bid_amount": j["budget"]}
    r1 = c.post("/v1/proposals", json=body, headers=H | {"Idempotency-Key": "k1"})
    r2 = c.post("/v1/proposals", json=body, headers=H | {"Idempotency-Key": "k1"})
    assert r1.json()["proposal_id"] == r2.json()["proposal_id"]
    assert r2.headers["Idempotent-Replay"] == "true"
    r3 = c.post("/v1/proposals", json=body | {"bid_amount": 1}, headers=H | {"Idempotency-Key": "k1"})
    assert r3.status_code == 409
    assert c.post("/v1/proposals", json=body, headers=H).status_code == 400  # key required


def test_contact_details_rejected_by_policy():
    j = open_job()
    body = {"job_id": j["job_id"], "cover_letter": GOOD_LETTER + " Email me at me@example.com",
            "bid_amount": 100}
    r = c.post("/v1/proposals", json=body, headers=H | {"Idempotency-Key": "k2"})
    assert r.status_code == 422 and r.json()["error"]["rule"] == "no_off_platform"


def _draft(j, key="d"):
    body = {"job_id": j["job_id"], "cover_letter": GOOD_LETTER, "bid_amount": j["budget"] or 50}
    return c.post("/v1/proposals", json=body, headers=H | {"Idempotency-Key": key}).json()


def test_submit_needs_confirm_and_spends_connects_exactly_once():
    j = open_job()
    p = _draft(j)
    before = c.get("/v1/connects", headers=H).json()["balance"]
    assert c.post(f"/v1/proposals/{p['proposal_id']}/submit", json={}, headers=H | {"Idempotency-Key": "s"}
                  ).status_code == 422
    for _ in range(3):  # retried submit with the same key
        r = c.post(f"/v1/proposals/{p['proposal_id']}/submit", json={"confirm": True},
                   headers=H | {"Idempotency-Key": "s1"})
        assert r.status_code == 200
    after = c.get("/v1/connects", headers=H).json()["balance"]
    assert before - after == j["connects_cost"]
    # a different key on an already-submitted proposal is refused, not re-spent
    r = c.post(f"/v1/proposals/{p['proposal_id']}/submit", json={"confirm": True},
               headers=H | {"Idempotency-Key": "s2"})
    assert r.status_code == 409
    assert c.get("/v1/connects", headers=H).json()["balance"] == after


def test_client_eventually_replies_or_loses_and_events_flow():
    j = open_job()
    p = _draft(j)
    c.post(f"/v1/proposals/{p['proposal_id']}/submit", json={"confirm": True}, headers=H | {"Idempotency-Key": "s"})
    c.post("/admin/fast-forward", headers=ADMIN)
    c.post("/admin/fast-forward", headers=ADMIN)
    status = c.get(f"/v1/proposals/{p['proposal_id']}", headers=H).json()["status"]
    assert status in ("replied", "lost")
    types = [e["type"] for e in c.get("/v1/events", headers=H).json()["items"]]
    assert types[:2] == ["proposal.drafted", "proposal.submitted"]


def _submit_many(n: int) -> None:
    world.account("ai_ml").connects = 10_000  # enough Connects for many proposals
    world.policy["proposals"]["max_open_proposals"] = 1000
    jobs = c.get("/v1/jobs", params={"category": "ai_ml", "limit": n}, headers=H).json()["items"]
    for i, j in enumerate(jobs):
        p = _draft(j, key=f"d{i}")
        if "proposal_id" in p:
            c.post(f"/v1/proposals/{p['proposal_id']}/submit", json={"confirm": True},
                   headers=H | {"Idempotency-Key": f"s{i}"})
    c.post("/admin/fast-forward", headers=ADMIN)
    c.post("/admin/fast-forward", headers=ADMIN)


def test_outcomes_are_deterministic_per_proposal_content():
    _submit_many(25)
    first = sorted((p["job_id"], p["status"]) for p in c.get("/v1/proposals", headers=H).json()["items"])
    world.reset()
    _buckets.clear()
    _submit_many(25)
    second = sorted((p["job_id"], p["status"]) for p in c.get("/v1/proposals", headers=H).json()["items"])
    assert first == second


def test_interview_flow_when_freelancer_proposes_slot():
    _submit_many(40)
    threads = c.get("/v1/threads", headers=H).json()["items"]
    real = [t for t in threads if t["intent"] != "scam"]
    assert real, "expected at least one client reply across 40 proposals"
    t = real[0]
    c.post(f"/v1/threads/{t['thread_id']}/messages", json={"text": "Happy to talk. Tuesday 3pm or Wed 11am PKT?"},
           headers=H | {"Idempotency-Key": "m1"})
    c.post("/admin/fast-forward", headers=ADMIN)
    st = c.get(f"/v1/proposals/{t['proposal_id']}", headers=H).json()["status"]
    assert st in ("interview", "replied")


def test_rate_limit_returns_429_with_retry_after():
    world.cfg["rate_limit"].update(requests_per_minute=60, burst=3)
    codes = [c.get("/v1/me", headers=H).status_code for _ in range(5)]
    assert 429 in codes
    r = c.get("/v1/me", headers=H)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1


def test_job_stream_releases_new_jobs():
    before = c.get("/v1/jobs", params={"limit": 1}, headers=H).json()["total"]
    c.post("/admin/advance", params={"batches": 2}, headers=ADMIN)
    after = c.get("/v1/jobs", params={"limit": 1}, headers=H).json()["total"]
    assert after > before
