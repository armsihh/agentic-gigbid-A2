"""Shared plumbing for GigBid's MCP servers: auth, per-user rate limiting, audit log, trace ids."""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError

from agent.guardrails.pii import mask

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- auth
class StaticTokenVerifier(TokenVerifier):
    """Bearer tokens from env, format: "token:user_id:scope1+scope2,token2:user2:scope".

    The API (apps/api) mints one token per GigBid user and per agent role, so each agent's
    MCP connection only carries the scopes it needs (e.g. marketplace:read for the Scout).
    """

    def __init__(self, spec: str | None):
        self.tokens: dict[str, AccessToken] = {}
        for entry in filter(None, (spec or "").split(",")):
            token, user, scopes = (entry.split(":", 2) + [""])[:3]
            self.tokens[token] = AccessToken(token=token, client_id=user, scopes=scopes.split("+") if scopes else [])

    async def verify_token(self, token: str) -> AccessToken | None:
        if token in self.tokens:
            return self.tokens[token]
        return verify_signed_token(token)


def sign_token(user_id: str, scopes: list[str], key: str | None = None) -> str:
    """Per-user, per-agent MCP token minted by the API: "<user>.<scope+scope>.<hmac>"."""
    import hashlib
    import hmac
    key = key or os.environ.get("MCP_SIGNING_KEY", "")
    body = f"{user_id}.{'+'.join(scopes)}"
    return body + "." + hmac.new(key.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]


def verify_signed_token(token: str) -> AccessToken | None:
    import hashlib
    import hmac
    key = os.environ.get("MCP_SIGNING_KEY", "")
    if not key or token.count(".") < 2:
        return None
    body, sig = token.rsplit(".", 1)
    good = hmac.new(key.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, good):
        return None
    user, scopes = body.rsplit(".", 1)
    return AccessToken(token=token, client_id=user, scopes=scopes.split("+") if scopes else [])


import contextvars

# identity for in-process calls (the API's inproc toolbox); follows each asyncio task, so concurrent runs
# for different users never see each other's identity
local_identity: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_local_identity", default=None)


def current_user(default_env: str) -> tuple[str, list[str]]:
    """User + scopes of the caller. HTTP: from the verified bearer token. In-process: from `local_identity`.
    stdio: from env (a local process is trusted with full scopes)."""
    tok = get_access_token()
    if tok is not None:
        return tok.client_id, tok.scopes
    ident = local_identity.get()
    if ident:
        return ident, ["*"]
    return os.environ.get(default_env, "local"), ["*"]


def require_scope(scopes: list[str], needed: str) -> None:
    if "*" not in scopes and needed not in scopes:
        raise ToolError(f"[forbidden] this token lacks scope {needed!r}")


def trace_id_from(ctx: Context | None) -> str:
    """One trace id flows UI -> API -> graph -> MCP -> audit log (E3). Taken from the request
    `_meta.trace_id`, else the `x-trace-id` HTTP header, else a new id."""
    if ctx is not None:
        try:
            meta = ctx.request_context.meta
            if meta is not None and getattr(meta, "trace_id", None):
                return str(meta.trace_id)
            if meta is not None and (meta.model_extra or {}).get("trace_id"):
                return str(meta.model_extra["trace_id"])
            req = ctx.request_context.request
            if req is not None and req.headers.get("x-trace-id"):
                return req.headers["x-trace-id"]
        except (AttributeError, LookupError, ValueError):
            pass
    return "tr-" + uuid.uuid4().hex[:16]


# ---------------------------------------------------------------- rate limiting
class RateLimiter:
    """Per-user token bucket. Callers wait politely (up to max_wait_s) instead of hammering
    the marketplace; beyond that they get a retryable error."""

    def __init__(self, per_minute: int, burst: int | None = None, max_wait_s: float = 10.0):
        self.rate = per_minute / 60.0
        self.burst = float(burst or max(1, per_minute // 3))
        self.max_wait_s = max_wait_s
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, user: str) -> None:
        async with self._lock:
            now = time.monotonic()
            tokens, last = self._state.get(user, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            wait = 0.0 if tokens >= 1 else (1 - tokens) / self.rate
            if wait > self.max_wait_s:
                self._state[user] = (tokens, now)
                raise ToolError(f"[rate_limited retryable] local rate limit, retry in {wait:.0f}s")
            self._state[user] = (tokens - 1 + wait * self.rate, now + wait)
        if wait:
            await asyncio.sleep(wait)


# ---------------------------------------------------------------- audit log
class AuditLog:
    """Append-only JSONL: who called which tool with what, what came back, under which trace.
    PII is masked before writing. Lines are never rewritten or deleted by the application."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, *, server: str, user: str, tool: str, args: dict[str, Any], ok: bool, result: Any,
              trace_id: str, duration_ms: float) -> None:
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z", "server": server, "user": user,
               "tool": tool, "args": mask(args), "ok": ok, "result": mask(_summarise(result)),
               "trace_id": trace_id, "duration_ms": round(duration_ms, 1)}
        line = json.dumps(rec, default=str, ensure_ascii=False)
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(x) for x in self.path.read_text(encoding="utf-8").split("\n") if x.strip()]


def _summarise(result: Any, limit: int = 2000) -> Any:
    if hasattr(result, "model_dump"):
        result = result.model_dump()
    s = json.dumps(result, default=str)
    return result if len(s) <= limit else {"truncated": s[:limit]}


def default_audit_path(name: str) -> Path:
    return Path(os.environ.get("AUDIT_LOG_DIR", ROOT / "data" / "audit")) / f"{name}.jsonl"
