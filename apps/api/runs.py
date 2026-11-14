"""Run manager: executes graph runs (bid, conversation, resume after approval), streams node-by-node progress,
persists events for replay, and projects graph state into the inbox / pipeline tables.

Execution: if REDIS_URL is set, runs are enqueued to the Arq worker (worker/main.py) and progress arrives over
Redis pub/sub; otherwise they run as background tasks in this process (dev, tests). Either way, nothing long runs
inside a web request: endpoints return a run id immediately and the UI follows /runs/{id}/stream.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
import uuid
from collections import defaultdict
from typing import Any

from langgraph.types import Command

from agent.mcp_client import current_trace_id
from agent.state import halt_of
from apps.api.db import JobRecord, Outcome, Rejection, RunRecord, User, now, session
from apps.api.settings import get_settings


class EventBus:
    """Fan-out of run events to SSE subscribers. In-process queues, mirrored to Redis pub/sub when configured."""
    def __init__(self) -> None:
        self.subs: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._redis = None

    async def redis(self):
        url = get_settings().redis_url
        if url and self._redis is None:
            from redis import asyncio as aioredis
            self._redis = aioredis.from_url(url)
        return self._redis

    async def publish(self, run_id: str, event: dict) -> None:
        for q in list(self.subs.get(run_id, [])):
            q.put_nowait(event)
        r = await self.redis()
        if r is not None:
            await r.publish(f"run:{run_id}", json.dumps(event, default=str))

    async def subscribe(self, run_id: str):
        q: asyncio.Queue = asyncio.Queue()
        self.subs[run_id].append(q)
        r = await self.redis()
        pubsub, pump = None, None
        if r is not None:
            pubsub = r.pubsub()
            await pubsub.subscribe(f"run:{run_id}")

            async def _pump():
                async for m in pubsub.listen():
                    if m.get("type") == "message":
                        q.put_nowait(json.loads(m["data"]))
            pump = asyncio.create_task(_pump())
        try:
            while True:
                yield await q.get()
        finally:
            self.subs[run_id].remove(q)
            if pump:
                pump.cancel()
            if pubsub:
                await pubsub.unsubscribe()


bus = EventBus()
TERMINAL_RUN = {"done", "waiting_approval", "failed"}


def bid_thread(user_id: str, job_id: str) -> str:
    return f"{user_id}:bid:{job_id}"


def conv_thread(user_id: str, mthread: str) -> str:
    return f"{user_id}:conv:{mthread}"


def stage_for(values: dict) -> str:
    if values.get("submission"):
        return "submitted"
    if values.get("status") == "waiting_approval":
        return "drafted"
    return "inbox"


async def project(user: User, thread_id: str, values: dict, interrupted: bool) -> None:
    """Graph state -> JobRecord (inbox/pipeline listing)."""
    job = values.get("job") or {}
    if not job:
        return
    risk, fit, dec, price = (values.get(k) or {} for k in ("risk_report", "fit_report", "decision", "price"))
    status = halt_of(values) or ("waiting_approval" if interrupted else values.get("status", "running"))
    with session() as s:
        rec = s.query(JobRecord).filter_by(user_id=user.id, thread_id=thread_id).first()
        if rec is None:
            rec = JobRecord(user_id=user.id, thread_id=thread_id, job_id=job["job_id"], title=job["title"][:300])
            s.add(rec)
        rec.category, rec.status = job.get("category"), status
        rec.action = dec.get("action")
        rec.fit, rec.risk, rec.risk_level = fit.get("score"), risk.get("score"), risk.get("level")
        rec.price, rec.connects_cost = price.get("amount"), job.get("connects_cost")
        sub = values.get("submission") or {}
        if sub.get("proposal_id"):
            rec.proposal_id = sub["proposal_id"]
        if rec.stage in ("inbox", "drafted") or not rec.stage:
            rec.stage = stage_for(values | {"status": status})
        rec.summary = {"reasons": dec.get("reasons", [])[:4], "flags": [f["type"] for f in risk.get("flags", [])][:6],
                       "budget": job.get("budget"), "hourly_high": job.get("hourly_high"),
                       "payment_type": job.get("payment_type"), "posted_at": job.get("posted_at")}
        s.commit()


def sweep_orphans() -> int:
    """In-process mode: runs live in this process, so after a restart (deploy, out-of-memory) every unfinished run
    is dead. Mark them failed (the run viewer stops waiting) and their jobs 'interrupted' (the job page offers Retry)."""
    with session() as s:
        recs = s.query(RunRecord).filter(RunRecord.status.in_(("queued", "running"))).all()
        for r in recs:
            r.status, r.finished_at, r.error = "failed", now(), "interrupted: the server restarted before this run finished"
            r.events = (r.events or []) + [{"seq": len(r.events or []) + 1, "ts": time.time(), "type": "run",
                                            "status": "failed", "error": r.error}]
            j = s.query(JobRecord).filter_by(user_id=r.user_id, thread_id=r.thread_id).first()
            if j and j.status in ("queued", "running"):
                j.status = "interrupted"
        s.commit()
        return len(recs)


class RunManager:
    def __init__(self, runtime) -> None:
        self.rt = runtime
        self.tasks: dict[str, asyncio.Task] = {}
        # one graph run at a time by default: each run holds embedding models + LLM payloads, and two at once
        # exceeded the 512 MB free-tier container (Render OOM-killed it mid-run). Extra runs wait their turn.
        self.slots = asyncio.Semaphore(max(1, int(os.environ.get("MAX_CONCURRENT_RUNS", "1"))))

    # ------------------------------------------------------------ entry points (return immediately)
    async def start_bid(self, user: User, job: dict) -> str:
        from agent.graphs.bid_graph import initial_state
        tid = bid_thread(user.id, job["job_id"])
        trace = "tr-" + uuid.uuid4().hex[:16]
        state = initial_state(job, tid, user.id, user.persona, trace)
        await project(user, tid, {"job": job, "status": "queued"}, False)
        return await self._launch(user, "bid", tid, state, trace)

    async def resume(self, user: User, thread_id: str, decision: dict) -> str:
        kind = "conversation" if ":conv:" in thread_id else "bid"
        if decision.get("action") == "reject" and decision.get("reason"):
            with session() as s:
                s.add(Rejection(user_id=user.id, thread_id=thread_id, reason=decision["reason"][:2000]))
                s.commit()
        return await self._launch(user, kind, thread_id, Command(resume=decision), "tr-" + uuid.uuid4().hex[:16],
                                  run_kind="resume")

    async def start_conversation(self, user: User, mthread: str, last_seen: str | None = None) -> str:
        tid = conv_thread(user.id, mthread)
        state = {"thread_id": tid, "user_id": user.id, "persona": user.persona, "marketplace_thread_id": mthread,
                 "last_seen_message_id": last_seen}
        return await self._launch(user, "conversation", tid, state, "tr-" + uuid.uuid4().hex[:16])

    async def _launch(self, user: User, kind: str, thread_id: str, payload: Any, trace: str,
                      run_kind: str | None = None) -> str:
        run_id = "run-" + uuid.uuid4().hex[:12]
        with session() as s:
            s.add(RunRecord(id=run_id, user_id=user.id, thread_id=thread_id, kind=run_kind or kind, trace_id=trace))
            s.commit()
        if get_settings().redis_url:
            from arq import create_pool
            from arq.connections import RedisSettings
            pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
            await pool.enqueue_job("execute_run", run_id, user.id, kind, thread_id,
                                   payload if not isinstance(payload, Command) else {"__resume__": payload.resume},
                                   _job_id=run_id)
        else:
            self.tasks[run_id] = asyncio.create_task(self._gated(run_id, user, kind, thread_id, payload))
        return run_id

    async def _gated(self, run_id: str, user: User, kind: str, thread_id: str, payload: Any) -> None:
        async with self.slots:
            await self.execute(run_id, user, kind, thread_id, payload)

    # ------------------------------------------------------------ execution (API task or worker)
    async def execute(self, run_id: str, user: User, kind: str, thread_id: str, payload: Any) -> None:
        if isinstance(payload, dict) and "__resume__" in payload:
            payload = Command(resume=payload["__resume__"])
        graph = self.rt.graph(user, kind)
        cfg = {"configurable": {"thread_id": thread_id}, "run_name": f"{kind}:{thread_id}",
               "tags": [kind, user.persona], "metadata": {"user_id": user.id, "run_id": run_id}}
        with session() as s:
            rec = s.get(RunRecord, run_id)
            trace = rec.trace_id
        token = current_trace_id.set(trace)
        t0 = time.perf_counter()
        events, status, err, values = [], "running", None, {}
        await self._event(run_id, events, {"type": "run", "status": "running", "kind": kind, "thread_id": thread_id})
        try:
            async for chunk in graph.astream(payload, cfg, stream_mode="updates"):
                for node, upd in chunk.items():
                    if node == "__interrupt__":
                        await self._event(run_id, events, {"type": "interrupt", "node": "approval",
                                                           "summary": "waiting for your approval"})
                        continue
                    for st in (upd or {}).get("trace", []) or []:
                        await self._event(run_id, events, {"type": "node", "node": st.get("node", node),
                                                           "summary": st.get("summary"), "at": st.get("at"),
                                                           "latency_ms": st.get("latency_ms"), "model": st.get("model"),
                                                           "cost_usd": st.get("cost_usd")})
            snap = await graph.aget_state(cfg)
            interrupted = bool(snap.tasks and any(t.interrupts for t in snap.tasks))
            values = snap.values
            if kind == "bid":
                await project(user, thread_id, values, interrupted)
            status = "waiting_approval" if interrupted else "done"
            if halt_of(values):
                status = "done"
        except Exception as e:  # noqa: BLE001 - recorded, shown in the run viewer, thread stays resumable
            status, err = "failed", f"{type(e).__name__}: {e}"
        finally:
            current_trace_id.reset(token)
        tokens = int(values.get("tokens_used") or 0)
        cost = round(sum(float(e.get("cost_usd") or 0) for e in events), 6)
        await self._event(run_id, events, {"type": "run", "status": status, "error": err})
        with session() as s:
            rec = s.get(RunRecord, run_id)
            rec.status, rec.finished_at, rec.error = status, now(), err
            rec.latency_s = round(time.perf_counter() - t0, 2)
            rec.events, rec.tokens, rec.cost_usd = events, tokens, cost
            s.commit()

    async def _event(self, run_id: str, events: list, ev: dict) -> None:
        ev = {"seq": len(events) + 1, "ts": time.time(), **ev}
        events.append(ev)
        await bus.publish(run_id, ev)

    # ------------------------------------------------------------ outcomes -> pipeline + outcome memory
    async def record_outcome(self, user: User, proposal_id: str, status: str, connects: int = 0) -> None:
        stage = {"viewed": "viewed", "replied": "replied", "interview": "interview", "hired": "hired",
                 "lost": "lost", "submitted": "submitted"}.get(status)
        with session() as s:
            rec = s.query(JobRecord).filter_by(user_id=user.id, proposal_id=proposal_id).first()
            if rec and stage:
                rec.stage = stage
            if status in ("replied", "interview", "hired", "lost"):
                s.add(Outcome(user_id=user.id, proposal_id=proposal_id, status=status,
                              category=rec.category if rec else None, connects_spent=connects))
            s.commit()
            thread_id = rec.thread_id if rec else None
            category = rec.category if rec else None
        if thread_id and status in ("hired", "lost", "replied") and self.rt.memory:
            graph = self.rt.graph(user, "bid")
            snap = await graph.aget_state({"configurable": {"thread_id": thread_id}})
            d, p = snap.values.get("draft") or {}, snap.values.get("price") or {}
            if d.get("cover_letter"):
                self.rt.memory.record_outcome(user.id, category or "other", d["cover_letter"], status,
                                              p.get("amount"), (p.get("band_low"), p.get("band_high"))
                                              if p.get("band_low") else None)

    async def wait(self, run_id: str, timeout: float = 120) -> str:
        task = self.tasks.get(run_id)
        if task:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), timeout)
        with session() as s:
            return s.get(RunRecord, run_id).status
