"""Sign-in, onboarding settings, saved searches, portfolio upload, memory viewer, Upwork OAuth."""
from __future__ import annotations

import datetime as dt
import json
import re

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile

from apps.api.auth.users import COOKIE, CurrentUser, authenticate, create_user, make_token
from apps.api.db import SavedSearch, User, session
from apps.api.runtime import ROOT, runtime
from apps.api.schemas import (
    Credentials,
    Me,
    MemoryItem,
    Register,
    SavedSearchIn,
    SavedSearchOut,
    UserSettings,
)
from apps.api.settings import get_settings

router = APIRouter(tags=["auth"])


def me_of(u: User) -> Me:
    return Me(id=u.id, email=u.email, persona=u.persona, marketplace=u.marketplace, settings=u.settings or {})


def _login_response(resp: Response, u: User) -> Me:
    s = get_settings()
    resp.set_cookie(COOKIE, make_token(u.id), httponly=True, samesite="lax", secure=s.app_env != "development",
                    max_age=s.session_hours * 3600)
    return me_of(u)


@router.post("/auth/register", response_model=Me)
def register(body: Register, resp: Response) -> Me:
    u = create_user(body.email, body.password, body.persona)
    with session() as s:
        s.add(SavedSearch(user_id=u.id, name=f"{body.persona} jobs", query={"category": body.persona, "limit": 20},
                          interval_minutes=60))
        s.commit()
    return _login_response(resp, u)


@router.post("/auth/login", response_model=Me)
def login(body: Credentials, resp: Response) -> Me:
    u = authenticate(body.email, body.password)
    if not u:
        raise HTTPException(401, "wrong email or password")
    return _login_response(resp, u)


@router.post("/auth/logout")
def logout(resp: Response) -> dict:
    resp.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/auth/me", response_model=Me)
def me(user: User = CurrentUser) -> Me:
    return me_of(user)


@router.get("/settings", response_model=Me)
def get_settings_(user: User = CurrentUser) -> Me:
    return me_of(user)


@router.put("/settings", response_model=Me)
def put_settings(body: UserSettings, user: User = CurrentUser) -> Me:
    with session() as s:
        u = s.get(User, user.id)
        if body.persona:
            u.persona = body.persona
        if body.marketplace:
            if body.marketplace == "upwork" and not _upwork_connected(user.id):
                raise HTTPException(409, "connect your Upwork account first (Settings -> Connected accounts)")
            u.marketplace = body.marketplace
        st = dict(u.settings or {})
        for k in ("hourly_rate", "min_fixed_budget", "weekly_connects_budget", "budgets"):
            v = getattr(body, k)
            if v is not None:
                st[k] = v
        if body.autonomy is not None:
            st["autonomy"] = body.autonomy.model_dump()
        u.settings = st
        s.commit()
        runtime.invalidate(user.id)
        return me_of(u)


@router.get("/saved-searches", response_model=list[SavedSearchOut])
def list_searches(user: User = CurrentUser):
    with session() as s:
        rows = s.query(SavedSearch).filter_by(user_id=user.id).all()
        return [SavedSearchOut(id=r.id, name=r.name, interval_minutes=r.interval_minutes,
                               last_run_at=r.last_run_at.isoformat() if r.last_run_at else None,
                               **{k: r.query.get(k) for k in ("query", "category", "payment_type", "min_budget")},
                               skills=r.query.get("skills", [])) for r in rows]


@router.post("/saved-searches", response_model=SavedSearchOut)
def add_search(body: SavedSearchIn, user: User = CurrentUser):
    q = body.model_dump(exclude={"name", "interval_minutes"}, exclude_none=True)
    with session() as s:
        r = SavedSearch(user_id=user.id, name=body.name, query=q, interval_minutes=body.interval_minutes)
        s.add(r)
        s.commit()
        return SavedSearchOut(id=r.id, **body.model_dump())


@router.delete("/saved-searches/{sid}")
def del_search(sid: int, user: User = CurrentUser):
    with session() as s:
        r = s.query(SavedSearch).filter_by(id=sid, user_id=user.id).first()
        if not r:
            raise HTTPException(404, "not found")
        s.delete(r)
        s.commit()
    return {"ok": True}


@router.post("/portfolio/upload")
async def upload_portfolio(title: str = Form(..., min_length=3, max_length=200), skills: str = Form(""),
                           industry: str = Form(""), file: UploadFile = File(...), user: User = CurrentUser):
    """Add a case study (Markdown or text). Written into the persona's portfolio folder; the Portfolio server
    re-indexes incrementally on its next call (mtime check)."""
    raw = (await file.read())[:200_000].decode("utf-8", errors="replace")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "item"
    cid = f"{user.persona}-cs-user-{slug}"
    fm = {"id": cid, "type": "case_study", "persona": user.persona, "project": f"user-{slug}",
          "skills": [x.strip() for x in skills.split(",") if x.strip()], "date": dt.date.today().isoformat(),
          "client_industry": industry or None, "synthetic": False, "uploaded_by": user.id}
    path = ROOT / "data" / "personas" / user.persona / "case_studies" / f"{cid}.md"
    path.write_text("---\n" + json.dumps(fm) + "\n---\n" + f"# {title}\n\n{raw}\n", encoding="utf-8")
    return {"id": cid, "indexed": "on next search"}


@router.get("/memory", response_model=list[MemoryItem])
def memory(user: User = CurrentUser):
    m = runtime.memory
    items = [MemoryItem(kind="style", key=r["key"], text=r["rule"], detail=r) for r in m.style_rules(user.id)]
    items += [MemoryItem(kind="outcome", key=i["key"], text=i["insight"], detail=i) for i in m.outcome_insights(user.id)]
    return items


@router.delete("/memory/{kind}/{key}")
def forget(kind: str, key: str, user: User = CurrentUser):
    if kind not in ("style", "outcome"):
        raise HTTPException(400, "kind must be style or outcome")
    runtime.memory.delete(user.id, kind, key)
    return {"ok": True}


# ---------------------------------------------------------------- live Upwork (OAuth 2.1 via the official MCP)
def _upwork_connected(user_id: str) -> bool:
    try:
        from apps.api.auth.token_store import EncryptedTokenStore
        return EncryptedTokenStore(user_id).is_connected()
    except RuntimeError:
        return False


_broker = None


@router.post("/auth/upwork/connect")
async def upwork_connect(user: User = CurrentUser):
    global _broker
    from apps.api.auth.upwork_oauth import OAuthBroker
    _broker = _broker or OAuthBroker()
    try:
        url = await _broker.start(user.id)
    except Exception as e:
        raise HTTPException(502, f"could not reach Upwork MCP: {type(e).__name__}") from e
    return {"authorization_url": url}


@router.get("/auth/upwork/callback")
def upwork_callback(code: str, state: str | None = None, user: User = CurrentUser):
    if _broker is None:
        raise HTTPException(400, "no OAuth flow in progress")
    _broker.complete(user.id, code, state)
    return {"ok": True, "next": "tokens are stored encrypted; switch marketplace to 'upwork' in Settings"}


@router.get("/auth/upwork/status")
def upwork_status(user: User = CurrentUser):
    return {"connected": _upwork_connected(user.id)}
