"""API end to end: sign up -> analyse a job (background run) -> inbox -> approval payload -> approve -> submitted ->
pipeline; SSE replay; tenant isolation; degraded health. In-process GigSim + MCP servers, scripted models."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

GOOD_JOB = "job-a532010879"


@pytest.fixture
def client(tmp_path, monkeypatch, adapter_factory, gigsim):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'app.db').as_posix()}")
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INLINE_SCHEDULER", "0")
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path / "audit"))
    monkeypatch.delenv("REDIS_URL", raising=False)
    from apps.api import db, settings
    settings.get_settings.cache_clear()
    db.reset_engine()
    import apps.api.runtime as rt_mod
    from apps.api.runtime import Runtime
    fresh = Runtime()
    for mod in ("apps.api.runtime", "apps.api.main", "apps.api.routers.jobs", "apps.api.routers.proposals",
                "apps.api.routers.approvals", "apps.api.routers.messages", "apps.api.routers.analytics",
                "apps.api.routers.auth"):
        m = __import__(mod, fromlist=["x"])
        if hasattr(m, "runtime"):
            monkeypatch.setattr(m, "runtime", fresh)
    monkeypatch.setattr(rt_mod, "runtime", fresh)

    from mcp_servers.marketplace.server import build_server as bm
    from mcp_servers.portfolio.server import build_server as bp
    from mcp_servers.portfolio.tools import PortfolioStore
    from mcp_servers.workspace.server import WorkspaceStore
    from mcp_servers.workspace.server import build_server as bw
    fresh._inproc_servers = {"marketplace": bm(adapter_factory, token_spec="", audit_path=str(tmp_path / "a.jsonl")),
                             "portfolio": bp(PortfolioStore(variant="bm25"), token_spec=""),
                             "workspace": bw(WorkspaceStore(tmp_path / "ws"), token_spec="")}
    from agent.testing import FakeModels
    from tests.integration.test_bid_graph import APPROVE, SPEC, WRITER, PassVerifier
    fresh._verifier = PassVerifier()
    models = FakeModels({"analyst": [SPEC], "writer": [WRITER], "critic": [APPROVE]})
    real_deps = fresh.deps

    def deps(user):
        d = real_deps(user)
        d.model_factory = models
        return d
    monkeypatch.setattr(fresh, "deps", deps)
    from apps.api.main import app
    with TestClient(app) as c:
        yield c


def wait_run(c, run_id, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = c.get(f"/api/runs/{run_id}").json()
        if r["status"] not in ("queued", "running"):
            return r
        time.sleep(0.2)
    raise AssertionError("run did not finish")


def signup(c, email="a@example.com"):
    r = c.post("/api/auth/register", json={"email": email, "password": "correct-horse-1", "persona": "ai_ml"})
    assert r.status_code == 200, r.text
    return r.json()


def test_full_journey(client, gigsim):
    c = client
    assert c.get("/api/jobs").status_code == 401
    signup(c)
    run = c.post(f"/api/jobs/{GOOD_JOB}/analyze").json()
    done = wait_run(c, run["run_id"])
    assert done["status"] == "waiting_approval", done
    nodes = [e["node"] for e in done["events"] if e["type"] == "node"]
    assert {"analyst", "risk_assessor", "fit_matcher", "writer", "critic", "compliance"} <= set(nodes)

    inbox = c.get("/api/jobs").json()
    assert inbox[0]["job_id"] == GOOD_JOB and inbox[0]["status"] == "waiting_approval" and inbox[0]["fit"]
    detail = c.get(f"/api/jobs/{GOOD_JOB}").json()
    assert detail["fit_report"]["matches"] and detail["pending_approval"]
    studio = c.get(f"/api/proposals/{GOOD_JOB}").json()
    assert studio["draft"]["cover_letter"] and studio["dry_run_preview"]["connects_cost"] == 8
    pend = c.get("/api/approvals").json()
    assert len(pend) == 1
    payload = c.get(f"/api/approvals/{pend[0]['thread_id']}").json()
    assert payload["kind"] == "proposal_approval"

    # refresh-safe: the SSE stream replays recorded events
    with c.stream("GET", f"/api/runs/{run['run_id']}/stream") as s:
        body = "".join(chunk for chunk in s.iter_text())
    assert "event: node" in body and "waiting_approval" in body

    assert c.post(f"/api/approvals/{pend[0]['thread_id']}", json={"action": "reject"}).status_code == 422
    res = c.post(f"/api/approvals/{pend[0]['thread_id']}", json={"action": "approve"}).json()
    assert wait_run(c, res["run_id"])["status"] == "done"
    assert c.post(f"/api/approvals/{pend[0]['thread_id']}", json={"action": "approve"}).status_code == 409  # once
    pipe = c.get("/api/pipeline").json()
    assert [j["job_id"] for j in pipe["submitted"]] == [GOOD_JOB]
    sent = [p for p in gigsim.account("ai_ml").proposals.values() if p["status"] != "draft"]
    assert len(sent) == 1
    assert c.get("/api/analytics").json()["funnel"]["submitted"] == 1


def test_tenant_isolation(client):
    c = client
    signup(c, "a@example.com")
    run = c.post(f"/api/jobs/{GOOD_JOB}/analyze").json()
    wait_run(c, run["run_id"])
    thread = c.get("/api/approvals").json()[0]["thread_id"]
    c.post("/api/auth/logout")
    signup(c, "b@example.com")
    assert c.get("/api/jobs").json() == []
    assert c.get(f"/api/approvals/{thread}").status_code == 404
    assert c.post(f"/api/approvals/{thread}", json={"action": "approve"}).status_code == 404
    assert c.get(f"/api/runs/{run['run_id']}").status_code == 404


def test_settings_memory_and_health(client):
    c = client
    signup(c)
    r = c.put("/api/settings", json={"hourly_rate": 40, "autonomy": {"auto_skip_low_fit": True}}).json()
    assert r["settings"]["hourly_rate"] == 40
    assert c.put("/api/settings", json={"marketplace": "upwork"}).status_code == 409   # must connect first
    assert c.get("/api/memory").json() == []
    h = c.get("/api/health").json()
    assert h["api"] == "ok" and h["marketplace"] == "ok"


def test_runs_orphaned_by_a_restart_become_retryable(client):
    """Render OOM-killed the container mid-run: on the next start the run must not stay 'queued' forever."""
    from apps.api.db import JobRecord, RunRecord, User, session
    from apps.api.runs import sweep_orphans
    signup(client, "orphan@example.com")
    with session() as s:
        u = s.query(User).filter_by(email="orphan@example.com").first()
        tid = f"{u.id}:bid:job-x"
        s.add(RunRecord(id="run-orphan", user_id=u.id, thread_id=tid, kind="bid", trace_id="tr-x"))
        s.add(JobRecord(user_id=u.id, thread_id=tid, job_id="job-x", title="x", status="queued"))
        s.commit()
    assert sweep_orphans() == 1
    r = client.get("/api/runs/run-orphan").json()
    assert r["status"] == "failed" and "restarted" in r["error"]
    with session() as s:
        assert s.query(JobRecord).filter_by(thread_id=tid).first().status == "interrupted"
    assert sweep_orphans() == 0
