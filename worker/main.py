"""Arq worker (E1): long agent runs and scheduled scouting execute here, never inside web requests.

    uv run arq worker.main.WorkerSettings

Idempotency: graph thread ids are derived from (user, job) and every marketplace write carries an idempotency key
derived from the thread, so a worker restart or a re-delivered job resumes from the checkpoint and never
double-analyses or double-submits. Arq job ids are the run ids, so a run is enqueued at most once.
"""
from __future__ import annotations

import os
from typing import ClassVar

from arq import cron
from arq.connections import RedisSettings

from apps.api.db import User, engine, session
from apps.api.runs import RunManager
from apps.api.runtime import runtime
from apps.api.scheduler import Scheduler


async def startup(ctx) -> None:
    engine()
    await runtime.start()
    ctx["runs"] = RunManager(runtime)
    ctx["scheduler"] = Scheduler(runtime, ctx["runs"])


async def shutdown(ctx) -> None:
    await runtime.stop()


async def execute_run(ctx, run_id: str, user_id: str, kind: str, thread_id: str, payload) -> str:
    with session() as s:
        user = s.get(User, user_id)
    await ctx["runs"].execute(run_id, user, kind, thread_id, payload)
    return run_id


async def schedule_tick(ctx) -> None:
    await ctx["scheduler"].tick()


class WorkerSettings:
    functions: ClassVar[list] = [execute_run]
    cron_jobs: ClassVar[list] = [cron(schedule_tick, second=0)]     # every minute; each saved search has its own interval
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    max_jobs = int(os.environ.get("WORKER_MAX_JOBS", "4"))
    job_timeout = 600
    max_tries = 3                                   # bounded retries; graph checkpoints make retries safe
