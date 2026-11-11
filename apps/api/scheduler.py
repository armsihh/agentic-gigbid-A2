"""Scheduled work (E1), used by the Arq worker (worker/main.py) and, without Redis, by an in-process loop.

  scout tick   every saved search runs on its own interval; new jobs are deduplicated and each one starts a
               bid-graph thread whose id is derived from (user, job): processing is idempotent, a worker restart
               never re-analyses or re-submits (the thread already exists / the checkpoint says where it is).
  events tick  polls marketplace events: updates the pipeline board, records outcomes (outcome memory), and starts
               the conversation graph when a client message arrives.
Live mode respects the conservative interval in agent/config.yaml (upwork.min_search_interval_s).
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging

from agent.mcp_client import ServiceDegraded
from agent.nodes.common import tool_json
from agent.nodes.scout import fingerprint
from apps.api.db import JobRecord, SavedSearch, User, now, session
from apps.api.runs import RunManager, bid_thread

log = logging.getLogger("gigbid.scheduler")


class Scheduler:
    def __init__(self, runtime, runs: RunManager, tick_s: float = 60):
        self.rt, self.runs, self.tick_s = runtime, runs, tick_s
        self.event_cursor: dict[str, int] = {}
        self._task: asyncio.Task | None = None
        self.max_new_per_tick = 5          # polite: bounded work per tick per user

    async def scout_user(self, user: User, force: bool = False) -> int:
        tb = self.rt.toolbox(user.id, user.persona)
        with session() as s:
            searches = s.query(SavedSearch).filter_by(user_id=user.id).all()
            known = {r.job_id for r in s.query(JobRecord).filter_by(user_id=user.id).all()}
            fps = {r.summary.get("fp"): r.job_id for r in s.query(JobRecord).filter_by(user_id=user.id).all()
                   if r.summary and r.summary.get("fp")}
        started = 0
        for ss in searches:
            due = force or not ss.last_run_at or now() - ss.last_run_at >= dt.timedelta(minutes=ss.interval_minutes)
            if not due:
                continue
            args = {k: v for k, v in (ss.query or {}).items() if v not in (None, [], "")} | {"limit": 20}
            page = tool_json(await tb.call("scout", "search_jobs", args))
            for item in (page.get("items", []) if isinstance(page, dict) else []):
                if item["job_id"] in known or started >= self.max_new_per_tick:
                    continue
                job = tool_json(await tb.call("scout", "get_job", {"job_id": item["job_id"]}))
                fp = fingerprint(job)
                job["duplicate_of"] = fps.get(fp)
                fps.setdefault(fp, job["job_id"])
                known.add(job["job_id"])
                await self.runs.start_bid(user, job)
                with session() as s:
                    r = s.query(JobRecord).filter_by(thread_id=bid_thread(user.id, job["job_id"])).first()
                    if r:
                        r.summary = {**(r.summary or {}), "fp": fp}
                        s.commit()
                started += 1
            with session() as s:
                row = s.get(SavedSearch, ss.id)
                row.last_run_at = now()
                s.commit()
        return started

    async def events_user(self, user: User) -> int:
        tb = self.rt.toolbox(user.id, user.persona)
        after = self.event_cursor.get(user.id, 0)
        res = tool_json(await tb.call("client_liaison", "list_events", {"after": after}))
        evs = res.get("events", []) if isinstance(res, dict) else []
        for e in evs:
            t = e["type"]
            if t.startswith("proposal.") and e.get("proposal_id"):
                await self.runs.record_outcome(user, e["proposal_id"], t.split(".", 1)[1],
                                               int((e.get("data") or {}).get("connects_spent") or 0))
            if t in ("proposal.replied", "message.received") and e.get("thread_id"):
                await self.runs.start_conversation(user, e["thread_id"])
        if evs:
            self.event_cursor[user.id] = res.get("last_seq", after)
        return len(evs)

    async def tick(self) -> None:
        with session() as s:
            users = s.query(User).all()
        for u in users:
            if u.marketplace != "gigsim" and u.marketplace != "upwork":
                continue
            try:
                await self.scout_user(u)
                await self.events_user(u)
            except ServiceDegraded as e:
                log.warning("marketplace down for %s: %s (will retry next tick)", u.id, e)
            except Exception:
                log.exception("tick failed for %s", u.id)

    def start(self) -> None:
        async def loop():
            while True:
                await self.tick()
                await asyncio.sleep(self.tick_s)
        self._task = asyncio.create_task(loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
