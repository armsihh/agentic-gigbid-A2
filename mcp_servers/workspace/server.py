"""Workspace MCP server (A3): calendar slots, tentative interview holds, email drafts.

Backed by a local mock (a JSON file per user) rather than Google Calendar/Gmail, so it runs anywhere;
the agent only ever sees these MCP tools, so swapping in the Google APIs changes this file only.
Nothing here sends anything: holds are TENTATIVE and emails are DRAFTS.

    uv run python -m mcp_servers.workspace.server                       # stdio
    WORKSPACE_MCP_TOKENS="tok:user1:workspace:read+workspace:write" \
      uv run python -m mcp_servers.workspace.server --http --port 8103
"""
from __future__ import annotations

import argparse
import json
import os
import random
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_servers.common import (
    ROOT,
    AuditLog,
    StaticTokenVerifier,
    current_user,
    default_audit_path,
    require_scope,
    trace_id_from,
)

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)

WORK_START_H, WORK_END_H = 9, 18
DEFAULT_TZ = "Asia/Karachi"


class Slot(BaseModel):
    start: str = Field(description="ISO datetime with offset")
    end: str
    timezone: str


class SlotList(BaseModel):
    timezone: str
    slots: list[Slot]


class Hold(BaseModel):
    hold_id: str
    title: str
    start: str
    end: str
    status: str = Field(description="Always 'tentative' until the human confirms in their calendar")
    thread_id: str | None = None


class EmailDraft(BaseModel):
    draft_id: str
    to: str
    subject: str
    body: str
    status: str = "draft"


class WorkspaceWriteResult(BaseModel):
    dry_run: bool
    hold: Hold | None = None
    draft: EmailDraft | None = None


class WorkspaceStore:
    """Per-user JSON state: busy blocks (seeded synthetic meetings), holds, drafts, idempotency keys."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.environ.get("WORKSPACE_STATE_DIR", ROOT / "data" / "workspace_state"))
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, user: str) -> Path:
        return self.root / f"{''.join(ch for ch in user if ch.isalnum() or ch in '-_')}.json"

    def load(self, user: str) -> dict:
        p = self._path(user)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return {"timezone": DEFAULT_TZ, "busy": self._seed_busy(user), "holds": [], "drafts": [], "idem": {}}

    def save(self, user: str, state: dict) -> None:
        tmp = self._path(user).with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self._path(user))

    @staticmethod
    def _seed_busy(user: str) -> list[dict]:
        """A plausible synthetic week of meetings so free-slot finding is non-trivial."""
        rng = random.Random(user)
        tz = ZoneInfo(DEFAULT_TZ)
        busy, today = [], date.today()
        for d in range(21):
            day = today + timedelta(days=d)
            if day.weekday() >= 5:
                continue
            for _ in range(rng.randint(1, 3)):
                h = rng.randint(WORK_START_H, WORK_END_H - 2)
                s = datetime(day.year, day.month, day.day, h, rng.choice([0, 30]), tzinfo=tz)
                busy.append({"start": s.isoformat(), "end": (s + timedelta(minutes=rng.choice([30, 60, 90]))).isoformat(),
                             "title": "busy"})
        return busy


def free_slots(state: dict, start: date, end: date, minutes: int, tz_name: str, max_slots: int) -> list[Slot]:
    tz = ZoneInfo(tz_name)
    busy = [(datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"])) for b in state["busy"]]
    busy += [(datetime.fromisoformat(h["start"]), datetime.fromisoformat(h["end"])) for h in state["holds"]]
    now = datetime.now(tz)
    out: list[Slot] = []
    day = start
    while day <= end and len(out) < max_slots:
        if day.weekday() < 5:
            t = datetime(day.year, day.month, day.day, WORK_START_H, tzinfo=tz)
            stop = datetime(day.year, day.month, day.day, WORK_END_H, tzinfo=tz)
            while t + timedelta(minutes=minutes) <= stop and len(out) < max_slots:
                e = t + timedelta(minutes=minutes)
                if t > now and not any(bs < e and t < be for bs, be in busy):
                    out.append(Slot(start=t.isoformat(), end=e.isoformat(), timezone=tz_name))
                    t = e + timedelta(minutes=60)  # spread suggestions out
                else:
                    t += timedelta(minutes=30)
        day += timedelta(days=1)
    return out


def build_server(store: WorkspaceStore | None = None, token_spec: str | None = None,
                 http_url: str = "http://localhost:8103") -> FastMCP:
    store = store or WorkspaceStore()
    token_spec = token_spec if token_spec is not None else os.environ.get("WORKSPACE_MCP_TOKENS")
    auth_kwargs = {}
    if token_spec or os.environ.get("MCP_SIGNING_KEY"):
        auth_kwargs = {"token_verifier": StaticTokenVerifier(token_spec),
                           "auth": AuthSettings(issuer_url=http_url, resource_server_url=http_url,
                                             required_scopes=["workspace:read"], validate_token_resource=False)}
    mcp = FastMCP("gigbid-workspace", instructions=(
        "The freelancer's calendar and email drafts. Holds are tentative and emails are drafts: nothing is "
        "sent or confirmed from here."), **auth_kwargs)
    audit = AuditLog(default_audit_path("workspace"))

    def run(tool: str, args: dict, ctx: Context | None, fn, scope: str = "workspace:read"):
        user, scopes = current_user("WORKSPACE_USER")
        t0, ok, res = time.perf_counter(), False, None
        try:
            require_scope(scopes, scope)
            with store._lock:
                res = fn(user)
            ok = True
            return res
        except ToolError as e:
            res = {"error": str(e)}
            raise
        finally:
            audit.write(server="workspace", user=user, tool=tool, args=args, ok=ok, result=res,
                        trace_id=trace_id_from(ctx), duration_ms=(time.perf_counter() - t0) * 1000)

    def idempotent(state: dict, key: str, body: dict, make):
        prior = state["idem"].get(key)
        if prior:
            if prior["body"] != body:
                raise ToolError("[conflict] idempotency_key already used with different arguments")
            return prior["result"]
        result = make()
        state["idem"][key] = {"body": body, "result": result}
        return result

    @mcp.tool(annotations=READ)
    def get_free_slots(
        start_date: Annotated[date, Field(description="First day to search (YYYY-MM-DD)")],
        end_date: Annotated[date, Field(description="Last day to search (YYYY-MM-DD), at most 21 days after start")],
        duration_minutes: Annotated[int, Field(ge=15, le=240)] = 30,
        max_slots: Annotated[int, Field(ge=1, le=10)] = 3,
        timezone: Annotated[str | None, Field(description="IANA timezone for the result; default: freelancer's")] = None,
        ctx: Context | None = None,
    ) -> SlotList:
        """Find free interview slots in the freelancer's working hours (weekdays 09:00-18:00)."""
        if end_date < start_date or (end_date - start_date).days > 21:
            raise ToolError("[invalid] end_date must be within 21 days after start_date")

        def fn(user):
            st = store.load(user)
            tz = timezone or st["timezone"]
            try:
                ZoneInfo(tz)
            except Exception as e:
                raise ToolError(f"[invalid] unknown timezone {tz!r}") from e
            return SlotList(timezone=tz, slots=free_slots(st, start_date, end_date, duration_minutes, tz, max_slots))
        return run("get_free_slots", {"start_date": str(start_date), "end_date": str(end_date),
                                      "duration_minutes": duration_minutes}, ctx, fn)

    @mcp.tool(annotations=WRITE)
    def create_interview_hold(
        start: Annotated[datetime, Field(description="ISO datetime with timezone offset")],
        duration_minutes: Annotated[int, Field(ge=15, le=240)],
        title: Annotated[str, Field(min_length=3, max_length=200)],
        idempotency_key: Annotated[str, Field(min_length=8, max_length=128)],
        thread_id: str | None = None,
        dry_run: bool = False,
        ctx: Context | None = None,
    ) -> WorkspaceWriteResult:
        """Put a TENTATIVE hold on the freelancer's calendar for a proposed interview. Does not invite anyone."""
        if start.tzinfo is None:
            raise ToolError("[invalid] start must include a timezone offset")
        end = start + timedelta(minutes=duration_minutes)

        def fn(user):
            st = store.load(user)
            body = {"start": start.isoformat(), "duration": duration_minutes, "title": title, "thread_id": thread_id}
            if not dry_run and idempotency_key in st["idem"]:  # replay BEFORE the clash check, or a retry clashes with itself
                return WorkspaceWriteResult(dry_run=False, hold=Hold(**idempotent(st, idempotency_key, body, None)))
            clash = [b for b in st["busy"] + st["holds"]
                     if datetime.fromisoformat(b["start"]) < end and start < datetime.fromisoformat(b["end"])]
            if clash:
                raise ToolError("[conflict] that time is not free")
            hold = Hold(hold_id="hold-" + uuid.uuid4().hex[:8], title=title, start=start.isoformat(),
                        end=end.isoformat(), status="tentative", thread_id=thread_id)
            if dry_run:
                return WorkspaceWriteResult(dry_run=True, hold=hold)
            result = idempotent(st, idempotency_key, body, lambda: (st["holds"].append(hold.model_dump()) or hold.model_dump()))
            store.save(user, st)
            return WorkspaceWriteResult(dry_run=False, hold=Hold(**result))
        return run("create_interview_hold", {"start": start.isoformat(), "title": title, "dry_run": dry_run},
                   ctx, fn, scope="workspace:write")

    @mcp.tool(annotations=WRITE)
    def create_email_draft(
        to: Annotated[str, Field(min_length=3, max_length=320)],
        subject: Annotated[str, Field(min_length=1, max_length=300)],
        body: Annotated[str, Field(min_length=1, max_length=10000)],
        idempotency_key: Annotated[str, Field(min_length=8, max_length=128)],
        dry_run: bool = False,
        ctx: Context | None = None,
    ) -> WorkspaceWriteResult:
        """Save an email DRAFT in the freelancer's mailbox. Never sends."""
        def fn(user):
            st = store.load(user)
            draft = EmailDraft(draft_id="draft-" + uuid.uuid4().hex[:8], to=to, subject=subject, body=body)
            if dry_run:
                return WorkspaceWriteResult(dry_run=True, draft=draft)
            result = idempotent(st, idempotency_key, {"to": to, "subject": subject, "body": body},
                                lambda: (st["drafts"].append(draft.model_dump()) or draft.model_dump()))
            store.save(user, st)
            return WorkspaceWriteResult(dry_run=False, draft=EmailDraft(**result))
        return run("create_email_draft", {"to": to, "subject": subject, "dry_run": dry_run}, ctx, fn,
                   scope="workspace:write")

    @mcp.tool(annotations=READ)
    def list_holds(ctx: Context | None = None) -> list[Hold]:
        """List tentative interview holds created by GigBid."""
        return run("list_holds", {}, ctx, lambda user: [Hold(**h) for h in store.load(user)["holds"]])

    return mcp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8103)
    a = ap.parse_args()
    if a.http:
        server = build_server(http_url=f"http://{a.host}:{a.port}")
        server.settings.host, server.settings.port = a.host, a.port
        if a.host not in ("127.0.0.1", "localhost"):  # containers: allow the compose service names only
            from mcp.server.transport_security import TransportSecuritySettings
            hosts = [h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
            server.settings.transport_security = TransportSecuritySettings(
                enable_dns_rebinding_protection=bool(hosts), allowed_hosts=hosts,
                allowed_origins=[f"http://{h}" for h in hosts])
        server.run("streamable-http")
    else:
        build_server().run("stdio")


if __name__ == "__main__":
    main()
