"""GigBid API (FastAPI). Run: uv run uvicorn apps.api.main:app --port 8000

All routes live under /api; the built React app is served at / in the single-container deployment.
The TypeScript client in apps/web/src/lib/api is generated from this app's OpenAPI schema.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from agent.guardrails.pii import mask_text
from apps.api.db import User, engine, session
from apps.api.routers import analytics, approvals, auth, jobs, messages, proposals, runs
from apps.api.runs import RunManager
from apps.api.runtime import runtime
from apps.api.scheduler import Scheduler
from apps.api.settings import get_settings


class PiiFilter(logging.Filter):
    """Mask emails / phones / payment details in every log line (E4)."""
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mask_text(str(record.msg))
        if record.args:
            record.args = tuple(mask_text(str(a)) for a in record.args) if isinstance(record.args, tuple) else record.args
        return True


def seed_reviewer() -> None:
    """Reviewer login preloaded with a persona (password only from env, never committed)."""
    s = get_settings()
    if not s.reviewer_password:
        return
    from apps.api.auth.users import create_user
    from apps.api.db import SavedSearch
    with session() as db:
        exists = db.query(User).filter(User.email == s.reviewer_email).first()
    if not exists:
        u = create_user(s.reviewer_email, s.reviewer_password, "ai_ml",
                        {"hourly_rate": 35, "min_fixed_budget": 300, "weekly_connects_budget": 80,
                         "autonomy": {"auto_skip_low_fit": True}})
        with session() as db:
            db.add(SavedSearch(user_id=u.id, name="AI/ML jobs", query={"category": "ai_ml"}, interval_minutes=30))
            db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    for h in logging.getLogger().handlers + logging.getLogger("uvicorn").handlers:
        h.addFilter(PiiFilter())
    engine()
    seed_reviewer()
    await runtime.start()
    app.state.runs = RunManager(runtime)
    app.state.scheduler = Scheduler(runtime, app.state.runs, tick_s=float(os.environ.get("SCHEDULER_TICK_S", "60")))
    if not get_settings().redis_url and os.environ.get("INLINE_SCHEDULER", "1") == "1":
        app.state.scheduler.start()      # no worker configured: run the schedule in-process
    yield
    await app.state.scheduler.stop()
    await runtime.stop()


app = FastAPI(title="GigBid API", version="1.0.0", lifespan=lifespan,
              description="Multi-agent freelancer copilot: inbox, proposals, approvals, conversations, runs.")
app.add_middleware(CORSMiddleware, allow_origins=[get_settings().web_origin], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

api = APIRouter(prefix="/api")
for r in (auth, jobs, proposals, approvals, messages, runs, analytics):
    api.include_router(r.router)
app.include_router(api)


@app.middleware("http")
async def trace_header(request: Request, call_next):
    """One trace id per request, echoed back so the UI can link a run to its trace."""
    tid = request.headers.get("x-trace-id")
    resp = await call_next(request)
    if tid:
        resp.headers["x-trace-id"] = tid
    return resp


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    logging.getLogger("gigbid.api").exception("unhandled error")
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: internal error"})


web_dir = get_settings().serve_web_dir
if web_dir and Path(web_dir).exists():
    app.mount("/assets", StaticFiles(directory=Path(web_dir) / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = Path(web_dir) / path
        return FileResponse(f if f.is_file() else Path(web_dir) / "index.html")
