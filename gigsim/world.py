"""In-memory GigSim world: jobs, clients, accounts, proposals, threads, events.

All time-based behaviour (job stream, client replies) is evaluated lazily via `tick()`,
which every request calls first, so there are no background threads.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from gigsim import client_sim

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent


class GigSimError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


def _read_jsonl(path: Path) -> list[dict]:
    # split on "\n" only: descriptions contain U+2028 which str.splitlines() would break on
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def load_config() -> tuple[dict, dict]:
    cfg = yaml.safe_load((HERE / "config.yaml").read_text())
    policy_path = Path(os.environ.get("GIGSIM_POLICY_FILE", HERE / "policy.yaml"))
    policy = yaml.safe_load(policy_path.read_text())
    if os.environ.get("GIGSIM_TOKENS"):
        cfg["auth"]["tokens"] = dict(p.split(":", 1) for p in os.environ["GIGSIM_TOKENS"].split(","))
    if os.environ.get("GIGSIM_ADMIN_TOKEN"):
        cfg["auth"]["admin_token"] = os.environ["GIGSIM_ADMIN_TOKEN"]
    for key, env in (("error_rate", "GIGSIM_ERROR_RATE"), ("slow_rate", "GIGSIM_SLOW_RATE")):
        if os.environ.get(env) is not None:
            cfg["faults"][key] = float(os.environ[env])
    if os.environ.get("GIGSIM_RPM"):
        cfg["rate_limit"]["requests_per_minute"] = int(os.environ["GIGSIM_RPM"])
    if os.environ.get("GIGSIM_TIME_SCALE"):  # >1 makes all sim delays shorter (tests/demos)
        scale = float(os.environ["GIGSIM_TIME_SCALE"])
        cs = cfg["client_sim"]
        for k in ("view_delay_seconds", "reply_delay_seconds", "followup_delay_seconds"):
            cs[k] = [v / scale for v in cs[k]]
        cs["no_reply_timeout_seconds"] /= scale
        cfg["job_stream"]["interval_seconds"] /= scale
    return cfg, policy


@dataclass
class Account:
    freelancer_id: str
    connects: int
    allowance_week: int
    proposals: dict[str, dict] = field(default_factory=dict)
    threads: dict[str, dict] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)


class World:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.reset()

    # ------------------------------------------------------------------ setup
    def reset(self) -> None:
        with getattr(self, "lock", threading.RLock()):
            self.cfg, self.policy = load_config()
            data_dir = Path(os.environ.get("GIGSIM_DATA_DIR", ROOT / self.cfg["data_dir"]))
            self.rng = random.Random(self.cfg["seed"])
            self.start = time.time()
            jobs = _read_jsonl(data_dir / "jobs.jsonl")
            self.jobs: dict[str, dict] = {j["job_id"]: j for j in jobs}
            self.history = _read_jsonl(data_dir / "history.jsonl")
            self.clients = {c["client_id"]: c for c in _read_jsonl(data_dir / "clients.jsonl")}
            self.hidden = {h["client_id"]: h for h in _read_jsonl(data_dir / "clients_hidden.jsonl")}
            self.market_stats = json.loads((data_dir / "market_stats.json").read_text())
            # job stream state
            self.stream_queue = sorted((j for j in jobs if j["release_order"] > 0),
                                       key=lambda j: j["release_order"])
            self.stream_pos = 0
            self.last_stream_tick = self.start
            for j in jobs:
                j["status"] = "open" if j["release_order"] == 0 else "pending"
                if j["status"] == "open":
                    j["posted_at"] = _iso(self.start - self.rng.uniform(0, 72 * 3600))
            self.history_by_client: dict[str, list[dict]] = {}
            for h in self.history:
                self.history_by_client.setdefault(h["client_id"], []).append(h)
            self.accounts: dict[str, Account] = {}
            self.idempotency: dict[tuple[str, str], tuple[str, Any]] = {}
            self.scheduled: list[dict] = []  # {due, kind, freelancer_id, ...}
            self.event_seq = 0
            self.audit: list[dict] = []

    # ------------------------------------------------------------------ time
    def tick(self) -> None:
        now = time.time()
        with self.lock:
            interval = self.cfg["job_stream"]["interval_seconds"]
            while now - self.last_stream_tick >= interval:
                self.last_stream_tick += interval
                self._release(self.cfg["job_stream"]["batch_size"], self.last_stream_tick)
            due = [e for e in self.scheduled if e["due"] <= now]
            self.scheduled = [e for e in self.scheduled if e["due"] > now]
            for e in sorted(due, key=lambda e: e["due"]):
                self._apply(e)

    def _release(self, n: int, at: float) -> int:
        released = 0
        while released < n and self.stream_pos < len(self.stream_queue):
            j = self.stream_queue[self.stream_pos]
            self.stream_pos += 1
            j["status"], j["posted_at"] = "open", _iso(at)
            released += 1
        return released

    def advance(self, batches: int = 1) -> int:
        with self.lock:
            return self._release(batches * self.cfg["job_stream"]["batch_size"], time.time())

    def fast_forward(self) -> int:
        """Fire every scheduled client event now (tests and demos)."""
        with self.lock:
            n = len(self.scheduled)
            for e in self.scheduled:
                e["due"] = 0
        self.tick()
        return n

    # ------------------------------------------------------------------ accounts
    def account(self, freelancer_id: str) -> Account:
        week = int((time.time() - 1_704_067_200) // (7 * 86400))  # weeks since 2024-01-01 (Mon)
        cc = self.policy["connects"]
        acc = self.accounts.get(freelancer_id)
        if acc is None:
            acc = Account(freelancer_id, cc["weekly_allowance"], week)
            self.accounts[freelancer_id] = acc
        elif week > acc.allowance_week:
            acc.connects = min(cc["max_balance"], acc.connects + cc["weekly_allowance"])
            acc.allowance_week = week
        return acc

    def _event(self, acc: Account, etype: str, **data: Any) -> dict:
        self.event_seq += 1
        ev = {"seq": self.event_seq, "type": etype, "at": _iso(time.time()), **data}
        acc.events.append(ev)
        return ev

    # ------------------------------------------------------------------ idempotency
    def idempotent(self, freelancer_id: str, key: str | None, body: dict, fn):
        if not key:
            raise GigSimError(400, "idempotency_key_required", "Idempotency-Key header is required")
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
        with self.lock:
            prior = self.idempotency.get((freelancer_id, key))
            if prior:
                if prior[0] != digest:
                    raise GigSimError(409, "idempotency_key_reused",
                                      "Idempotency-Key was already used with a different request body")
                return prior[1], True
            result = fn()
            self.idempotency[(freelancer_id, key)] = (digest, result)
            return result, False

    # ------------------------------------------------------------------ reads
    def public_job(self, j: dict, full: bool = False) -> dict:
        keys = ["job_id", "title", "skills", "category", "experience_level", "duration", "payment_type",
                "budget", "hourly_low", "hourly_high", "connects_cost", "applicants", "client_id",
                "country", "posted_at", "status"]
        out = {k: j.get(k) for k in keys}
        out["connects_cost"] = self.connects_cost(j)
        out["description"] = j["description"] if full else j["description"][:280]
        return out

    def connects_cost(self, j: dict) -> int:
        base = int(j.get("connects_cost") or 8)
        for rule in self.policy.get("connects", {}).get("surcharges", []):   # platform policy updates
            if all(str(j.get(k)) == str(v) for k, v in rule.get("when", {}).items()):
                base += int(rule.get("extra", 0))
        return base

    def search_jobs(self, q: str | None, category: str | None, skills: list[str], payment_type: str | None,
                    min_budget: float | None, posted_after: str | None, limit: int, cursor: int) -> dict:
        terms = [t for t in (q or "").lower().split() if t]
        skills_l = [s.lower() for s in skills]
        res = []
        for j in self.jobs.values():
            if j["status"] != "open":
                continue
            if category and j["category"] != category:
                continue
            if payment_type and j["payment_type"] != payment_type:
                continue
            if min_budget and (j.get("budget") or j.get("hourly_high") or 0) < min_budget:
                continue
            if posted_after and j["posted_at"] <= posted_after:
                continue
            hay = (j["title"] + " " + j["description"] + " " + " ".join(j["skills"])).lower()
            if terms and not all(t in hay for t in terms):
                continue
            if skills_l and not any(s in [x.lower() for x in j["skills"]] for s in skills_l):
                continue
            res.append(j)
        res.sort(key=lambda j: j["posted_at"], reverse=True)
        page = res[cursor:cursor + limit]
        nxt = cursor + limit if cursor + limit < len(res) else None
        return {"items": [self.public_job(j) for j in page], "total": len(res), "next_cursor": nxt}

    def get_job(self, job_id: str) -> dict:
        j = self.jobs.get(job_id)
        if not j or j["status"] == "pending":
            raise GigSimError(404, "job_not_found", f"job {job_id} not found")
        return self.public_job(j, full=True)

    def client_profile(self, client_id: str) -> dict:
        c = self.clients.get(client_id)
        if not c:
            raise GigSimError(404, "client_not_found", f"client {client_id} not found")
        hist = self.history_by_client.get(client_id, [])
        posted = [j for j in self.jobs.values() if j["client_id"] == client_id and j["status"] != "pending"]
        awarded = [h["awarded_amount"] for h in hist if h.get("awarded_amount")]
        return {
            **c,
            "jobs_posted": len(hist) + len(posted),
            "hires": len(awarded),
            "hire_rate": round(len(awarded) / (len(hist) + len(posted)), 2) if (hist or posted) else None,
            "avg_awarded_amount": round(sum(awarded) / len(awarded), 2) if awarded else None,
            "recent_jobs": [{"title": h["title"], "status": h["status"], "awarded_amount": h.get("awarded_amount"),
                             "payment_type": h["payment_type"]} for h in hist[:10]],
            "open_jobs": [j["job_id"] for j in posted if j["status"] == "open"],
        }

    def stats(self, category: str | None, experience_level: str | None) -> dict:
        ms = self.market_stats
        out = {"by_category": ms["by_category"] if not category else {category: ms["by_category"].get(category)}}
        if category and experience_level:
            out["category_level"] = ms["by_category_level"].get(f"{category}|{experience_level}")
        return out

    # ------------------------------------------------------------------ proposals
    def _validate_letter(self, text: str) -> None:
        pc = self.policy["proposals"]
        if not (pc["min_cover_letter_chars"] <= len(text) <= pc["max_cover_letter_chars"]):
            raise GigSimError(422, "cover_letter_length",
                              f"cover letter must be {pc['min_cover_letter_chars']}-{pc['max_cover_letter_chars']} chars")
        if self.policy.get("enforcement", {}).get("block_contact_details") and client_sim.has_contact_details(text):
            raise GigSimError(422, "policy_violation", "contact details are not allowed", rule="no_off_platform")

    def create_draft(self, fid: str, body: dict) -> dict:
        acc = self.account(fid)
        j = self.jobs.get(body["job_id"])
        if not j or j["status"] != "open":
            raise GigSimError(409, "job_not_open", "job is not open for proposals")
        if any(p["job_id"] == j["job_id"] and p["status"] != "draft" for p in acc.proposals.values()):
            raise GigSimError(409, "already_applied", "a proposal for this job was already submitted")
        text = body["cover_letter"] + "\n" + "\n".join(body.get("screening_answers") or [])
        self._validate_letter(text)
        boost = int(body.get("boost_connects") or 0)
        if boost and (not self.policy["connects"]["boost"]["allowed"]
                      or boost > self.policy["connects"]["boost"]["max_extra_connects"]):
            raise GigSimError(422, "invalid_boost", "boost not allowed by policy")
        cost = self.connects_cost(j) + boost
        preview = {"job_id": j["job_id"], "job_title": j["title"], "cover_letter": body["cover_letter"],
                   "screening_answers": body.get("screening_answers") or [], "bid_amount": body["bid_amount"],
                   "bid_type": j["payment_type"], "connects_cost_on_submit": cost,
                   "connects_balance": acc.connects, "connects_balance_after_submit": acc.connects - cost,
                   "policy_version": self.policy["version"]}
        if body.get("dry_run"):
            return {"dry_run": True, "would_create": preview}
        pid = "prop-" + uuid.uuid4().hex[:10]
        prop = {**preview, "proposal_id": pid, "status": "draft", "boost_connects": boost,
                "created_at": _iso(time.time()), "submitted_at": None, "thread_id": None}
        del prop["connects_balance"], prop["connects_balance_after_submit"]
        acc.proposals[pid] = prop
        self._event(acc, "proposal.drafted", proposal_id=pid, job_id=j["job_id"])
        return prop

    def submit(self, fid: str, pid: str, body: dict) -> dict:
        acc = self.account(fid)
        prop = acc.proposals.get(pid)
        if not prop:
            raise GigSimError(404, "proposal_not_found", "proposal not found")
        if prop["status"] != "draft":
            raise GigSimError(409, "already_submitted", "proposal already submitted", proposal=prop)
        if self.policy["proposals"]["require_human_confirmation"] and not body.get("confirm"):
            raise GigSimError(422, "confirmation_required", "submit requires confirm=true")
        j = self.jobs[prop["job_id"]]
        if j["status"] != "open":
            raise GigSimError(409, "job_not_open", "job is no longer open")
        open_n = sum(1 for p in acc.proposals.values() if p["status"] in ("submitted", "viewed", "replied", "interview"))
        if open_n >= self.policy["proposals"]["max_open_proposals"]:
            raise GigSimError(429, "too_many_open_proposals", "open proposal limit reached")
        cost = self.connects_cost(j) + prop["boost_connects"]
        if body.get("dry_run"):
            return {"dry_run": True, "would_submit": {**prop, "connects_cost": cost,
                                                      "connects_balance_after": acc.connects - cost}}
        if acc.connects < cost:
            raise GigSimError(402, "insufficient_connects", f"need {cost} connects, have {acc.connects}")
        acc.connects -= cost
        prop.update(status="submitted", submitted_at=_iso(time.time()), connects_spent=cost)
        self._event(acc, "proposal.submitted", proposal_id=pid, job_id=j["job_id"], connects_spent=cost)
        self._schedule_client(acc, prop, j)
        return {**prop, "connects_balance": acc.connects}

    def _prng(self, *parts: str) -> random.Random:
        return random.Random(hashlib.sha256(("|".join(parts) + str(self.cfg["seed"])).encode()).hexdigest())

    def _schedule_client(self, acc: Account, prop: dict, j: dict) -> None:
        cs = self.cfg["client_sim"]
        hidden = self.hidden.get(j["client_id"], {})
        # Seed from CONTENT (job, bid, text), never from random ids: the same proposal to the same job
        # always gets the same outcome, so reply-rate evaluations are reproducible.
        text = prop["cover_letter"] + "\n".join(prop.get("screening_answers") or [])
        prop["_seed"] = f"{j['job_id']}|{prop['bid_amount']}|{hashlib.sha256(text.encode()).hexdigest()[:16]}"
        rng = self._prng(prop["_seed"])
        score = client_sim.score_proposal(prop, j, hidden, cs.get("reply_scale", 0.7))
        prop["_score"] = score  # internal, stripped from API output
        now = time.time()
        t_view = now + rng.uniform(*cs["view_delay_seconds"])
        views = hidden.get("is_scammer") or rng.random() < 0.85
        replies = hidden.get("is_scammer") or rng.random() < score["p_reply"]
        if views:
            self.scheduled.append({"due": t_view, "kind": "viewed", "fid": acc.freelancer_id,
                                   "pid": prop["proposal_id"]})
        if views and replies:
            self.scheduled.append({"due": t_view + rng.uniform(*cs["reply_delay_seconds"]), "kind": "reply",
                                   "fid": acc.freelancer_id, "pid": prop["proposal_id"]})
        else:
            self.scheduled.append({"due": now + cs["no_reply_timeout_seconds"], "kind": "lost",
                                   "fid": acc.freelancer_id, "pid": prop["proposal_id"]})

    # ------------------------------------------------------------------ threads
    def send_message(self, fid: str, tid: str, body: dict) -> dict:
        acc = self.account(fid)
        th = acc.threads.get(tid)
        if not th:
            raise GigSimError(404, "thread_not_found", "thread not found")
        text = body["text"]
        if self.policy.get("enforcement", {}).get("block_contact_details") and client_sim.has_contact_details(text):
            raise GigSimError(422, "policy_violation", "contact details are not allowed", rule="no_off_platform")
        if body.get("dry_run"):
            return {"dry_run": True, "would_send": {"thread_id": tid, "text": text}}
        msg = {"message_id": "msg-" + uuid.uuid4().hex[:10], "sender": "freelancer", "text": text,
               "at": _iso(time.time())}
        th["messages"].append(msg)
        self._event(acc, "message.sent", thread_id=tid, message_id=msg["message_id"])
        cs = self.cfg["client_sim"]
        rng = self._prng(acc.proposals[th["proposal_id"]]["_seed"], "msg", str(len(th["messages"])), text)
        self.scheduled.append({"due": time.time() + rng.uniform(*cs["followup_delay_seconds"]),
                               "kind": "followup", "fid": fid, "tid": tid, "text": text})
        return msg

    # ------------------------------------------------------------------ scheduled effects
    def _apply(self, e: dict) -> None:
        acc = self.account(e["fid"])
        if e["kind"] in ("viewed", "reply", "lost"):
            prop = acc.proposals[e["pid"]]
            j = self.jobs[prop["job_id"]]
            if e["kind"] == "viewed" and prop["status"] == "submitted":
                prop["status"] = "viewed"
                self._event(acc, "proposal.viewed", proposal_id=prop["proposal_id"])
            elif e["kind"] == "lost" and prop["status"] in ("submitted", "viewed"):
                prop["status"] = "lost"
                self._event(acc, "proposal.lost", proposal_id=prop["proposal_id"], reason="no_reply")
            elif e["kind"] == "reply":
                hidden = self.hidden.get(j["client_id"], {})
                rng = self._prng(prop["_seed"], "reply")
                rep = client_sim.first_reply(rng, prop, j, hidden, prop["_score"])
                tid = "th-" + uuid.uuid4().hex[:10]
                acc.threads[tid] = {"thread_id": tid, "proposal_id": prop["proposal_id"], "job_id": j["job_id"],
                                    "client_id": j["client_id"], "job_title": j["title"], "intent": rep["intent"],
                                    "messages": [{"message_id": "msg-" + uuid.uuid4().hex[:10],
                                                  "sender": "client", "text": rep["text"], "at": _iso(time.time())}]}
                prop.update(status="replied", thread_id=tid)
                self._event(acc, "proposal.replied", proposal_id=prop["proposal_id"], thread_id=tid,
                            intent=rep["intent"])
        elif e["kind"] == "followup":
            self._followup(acc, e)
        elif e["kind"] == "decision":
            th = acc.threads[e["tid"]]
            prop = acc.proposals[th["proposal_id"]]
            if prop["status"] in ("hired", "lost"):
                return
            rng = self._prng(prop["_seed"], "decision")
            p = self.cfg["client_sim"]["hire_base_probability"] * (0.6 + prop["_score"]["p_reply"])
            hired = rng.random() < p
            prop["status"] = "hired" if hired else "lost"
            self._client_msg(acc, th, client_sim.HIRE_MESSAGE if hired else client_sim.DECLINE_MESSAGE)
            self._event(acc, "proposal.hired" if hired else "proposal.lost", proposal_id=prop["proposal_id"],
                        thread_id=th["thread_id"])

    def _client_msg(self, acc: Account, th: dict, text: str) -> None:
        msg = {"message_id": "msg-" + uuid.uuid4().hex[:10], "sender": "client", "text": text, "at": _iso(time.time())}
        th["messages"].append(msg)
        self._event(acc, "message.received", thread_id=th["thread_id"], message_id=msg["message_id"])

    def _followup(self, acc: Account, e: dict) -> None:
        th = acc.threads[e["tid"]]
        prop = acc.proposals[th["proposal_id"]]
        if prop["status"] in ("hired", "lost"):
            return
        cs = self.cfg["client_sim"]
        rng = self._prng(prop["_seed"], "followup", str(len(th["messages"])), e["text"])
        if th["intent"] == "scam":
            self._client_msg(acc, th, rng.choice(client_sim.SCAM_REPLIES).format(n=rng.randint(100, 999)))
            return
        slot = client_sim.proposes_slot(e["text"])
        if th["intent"] in ("interview_request", "question", "negotiation") and slot:
            th["intent"] = "interview_scheduled"
            prop["status"] = "interview"
            self._client_msg(acc, th, client_sim.FOLLOWUP_INTERVIEW.format(slot=slot))
            self._event(acc, "proposal.interview", proposal_id=prop["proposal_id"], thread_id=th["thread_id"],
                        slot=slot)
            self.scheduled.append({"due": time.time() + rng.uniform(*cs["reply_delay_seconds"]),
                                   "kind": "decision", "fid": acc.freelancer_id, "tid": th["thread_id"]})
        elif th["intent"] == "question":
            th["intent"] = "interview_request"
            self._client_msg(acc, th, rng.choice(client_sim.INTERVIEW_REPLIES).format(title=th["job_title"][:60]))
        elif th["intent"] == "negotiation":
            self._client_msg(acc, th, "Thanks. Let's have a quick call first - when are you free?")
            th["intent"] = "interview_request"
        else:
            self._client_msg(acc, th, client_sim.FOLLOWUP_GENERIC)


def strip_internal(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: strip_internal(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [strip_internal(v) for v in obj]
    return obj
