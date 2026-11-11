"""Encrypted per-user OAuth token store (A4 / E4).

Implements the MCP SDK's `TokenStorage` protocol, so `OAuthClientProvider` reads and refreshes
Upwork tokens through it. Tokens are encrypted at rest with Fernet (AES-128-CBC + HMAC) using a key
derived from APP_SECRET_KEY, scoped by user id (tenant), and never logged.

Backend: one encrypted file per user under TOKEN_STORE_DIR (Postgres table in deployment, same API).
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[3]


def _fernet(secret: str | None = None) -> Fernet:
    secret = secret or os.environ.get("APP_SECRET_KEY")
    if not secret or secret == "replace_me":
        raise RuntimeError("APP_SECRET_KEY must be set to a real secret to store OAuth tokens")
    key = base64.urlsafe_b64encode(hashlib.sha256(("gigbid-token-store:" + secret).encode()).digest())
    return Fernet(key)


class _Record(BaseModel):
    tokens: OAuthToken | None = None
    client_info: OAuthClientInformationFull | None = None


class EncryptedTokenStore:
    """TokenStorage for one (user, provider) pair."""

    def __init__(self, user_id: str, provider: str = "upwork", root: str | Path | None = None,
                 secret: str | None = None):
        if not user_id or any(ch in user_id for ch in "/\\.."):
            raise ValueError("invalid user id")
        self.user_id, self.provider = user_id, provider
        self.root = Path(root or os.environ.get("TOKEN_STORE_DIR", ROOT / "data" / "token_store"))
        self.root.mkdir(parents=True, exist_ok=True)
        self._f = _fernet(secret)

    @property
    def path(self) -> Path:
        h = hashlib.sha256(f"{self.provider}:{self.user_id}".encode()).hexdigest()[:24]
        return self.root / f"{h}.bin"

    def _read(self) -> _Record:
        if not self.path.exists():
            return _Record()
        try:
            return _Record.model_validate_json(self._f.decrypt(self.path.read_bytes()))
        except InvalidToken:  # wrong key or tampered: treat as not connected, never crash or leak
            return _Record()

    def _write(self, rec: _Record) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(self._f.encrypt(rec.model_dump_json().encode()))
        tmp.replace(self.path)

    # --- mcp.client.auth.TokenStorage protocol
    async def get_tokens(self) -> OAuthToken | None:
        return self._read().tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        rec = self._read()
        rec.tokens = tokens
        self._write(rec)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self._read().client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        rec = self._read()
        rec.client_info = client_info
        self._write(rec)

    # --- app helpers
    def is_connected(self) -> bool:
        return self._read().tokens is not None

    def disconnect(self) -> None:
        self.path.unlink(missing_ok=True)

    def __repr__(self) -> str:  # never print secrets
        return f"EncryptedTokenStore(user={self.user_id!r}, provider={self.provider!r})"
