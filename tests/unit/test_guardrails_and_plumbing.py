"""PII masking, rate limiter, bearer-token scopes and the encrypted token store."""
from __future__ import annotations

import time

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from mcp.shared.auth import OAuthToken

from agent.guardrails.pii import mask, mask_text
from apps.api.auth.token_store import EncryptedTokenStore
from mcp_servers.common import RateLimiter, StaticTokenVerifier, require_scope


def test_pii_masking():
    s = "Mail ali@x.com or call +92 300 1234567, card 4111 1111 1111 1111, CNIC 35202-1234567-1, token: abc123"
    m = mask_text(s)
    for secret in ("ali@x.com", "1234567,", "4111", "35202-1234567-1", "abc123"):
        assert secret not in m
    assert mask({"Authorization": "Bearer x", "nested": ["a@b.io"]}) == {"Authorization": "[REDACTED]", "nested": ["[EMAIL]"]}


async def test_rate_limiter_waits_politely_then_refuses():
    rl = RateLimiter(per_minute=600, burst=2, max_wait_s=0.5)  # 10/s
    t0 = time.monotonic()
    for _ in range(4):
        await rl.acquire("u")
    assert time.monotonic() - t0 >= 0.15  # had to wait for refill
    slow = RateLimiter(per_minute=6, burst=1, max_wait_s=0.1)
    await slow.acquire("u")
    with pytest.raises(ToolError, match="rate_limited retryable"):
        await slow.acquire("u")
    await slow.acquire("other-user")  # per-user buckets


async def test_static_tokens_and_scopes():
    v = StaticTokenVerifier("t1:alice:marketplace:read,t2:bob:marketplace:read+marketplace:write")
    a, b = await v.verify_token("t1"), await v.verify_token("t2")
    assert a.client_id == "alice" and await v.verify_token("nope") is None
    require_scope(b.scopes, "marketplace:write")
    with pytest.raises(ToolError, match="forbidden"):
        require_scope(a.scopes, "marketplace:write")


async def test_token_store_encrypts_at_rest(tmp_path):
    st = EncryptedTokenStore("alice", root=tmp_path, secret="s3cret")
    await st.set_tokens(OAuthToken(access_token="ACCESS-TOKEN-VALUE", token_type="Bearer", refresh_token="REFRESH"))
    raw = st.path.read_bytes()
    assert b"ACCESS-TOKEN-VALUE" not in raw and b"REFRESH" not in raw
    assert (await st.get_tokens()).access_token == "ACCESS-TOKEN-VALUE"
    other = EncryptedTokenStore("alice", root=tmp_path, secret="wrong")
    assert await other.get_tokens() is None  # wrong key cannot read, does not crash
    assert EncryptedTokenStore("bob", root=tmp_path, secret="s3cret").path != st.path  # tenant scoped
    assert "ACCESS" not in repr(st)
    st.disconnect()
    assert not st.is_connected()
