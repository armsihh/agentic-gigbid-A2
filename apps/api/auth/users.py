"""Users and sessions: PBKDF2 password hashing (stdlib), JWT in an HttpOnly cookie (or Bearer header)."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
import secrets
import uuid

import jwt
from fastapi import Cookie, Depends, Header, HTTPException

from apps.api.db import User, session
from apps.api.settings import get_settings

COOKIE = "gigbid_session"
ITER = 260_000


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, ITER)
    return f"pbkdf2${ITER}${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, it, salt, dk = stored.split("$")
        cand = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(cand.hex(), dk)
    except (ValueError, TypeError):
        return False


def make_token(user_id: str) -> str:
    s = get_settings()
    exp = dt.datetime.now(dt.UTC) + dt.timedelta(hours=s.session_hours)
    return jwt.encode({"sub": user_id, "exp": exp, "jti": secrets.token_hex(8)}, s.app_secret_key, algorithm="HS256")


def create_user(email: str, password: str, persona: str = "ai_ml", settings: dict | None = None) -> User:
    with session() as s:
        if s.query(User).filter(User.email == email.lower()).first():
            raise HTTPException(409, "email already registered")
        u = User(id="u-" + uuid.uuid4().hex[:12], email=email.lower(), password_hash=hash_password(password),
                 persona=persona, settings=settings or {})
        s.add(u)
        s.commit()
        return u


def authenticate(email: str, password: str) -> User | None:
    with session() as s:
        u = s.query(User).filter(User.email == email.lower()).first()
        return u if u and verify_password(password, u.password_hash) else None


def current_user(gigbid_session: str | None = Cookie(None), authorization: str | None = Header(None)) -> User:
    token = gigbid_session or (authorization[7:] if authorization and authorization.lower().startswith("bearer ") else None)
    if not token:
        raise HTTPException(401, "not signed in")
    try:
        sub = jwt.decode(token, get_settings().app_secret_key, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError as e:
        raise HTTPException(401, "session expired") from e
    with session() as s:
        u = s.get(User, sub)
    if not u:
        raise HTTPException(401, "unknown user")
    return u


CurrentUser = Depends(current_user)
