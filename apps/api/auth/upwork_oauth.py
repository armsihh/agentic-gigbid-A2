"""Browser OAuth 2.1 flow for the official Upwork MCP server, driven from the GigBid web UI.

The MCP SDK's `OAuthClientProvider` does discovery, dynamic client registration, PKCE and refresh.
It needs two callbacks: where to send the user (redirect_handler) and how to get the code back
(callback_handler). In a web app these are two HTTP requests, so this broker parks a future per user:

  1. UI: POST /auth/upwork/connect  -> broker.start(user) -> returns the Upwork authorization URL
  2. user logs in on upwork.com, Upwork redirects to  GET /auth/upwork/callback?code=..&state=..
  3. API: broker.complete(user, code, state) -> resolves the future -> provider stores encrypted tokens
"""
from __future__ import annotations

import asyncio
import os

import httpx
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientMetadata
from pydantic import AnyUrl

from apps.api.auth.token_store import EncryptedTokenStore

UPWORK_MCP_URL = os.environ.get("UPWORK_MCP_URL", "https://mcp.upwork.com/mcp")


class OAuthBroker:
    def __init__(self, redirect_uri: str | None = None):
        self.redirect_uri = redirect_uri or os.environ.get("UPWORK_OAUTH_REDIRECT_URI",
                                                           "http://localhost:8000/auth/upwork/callback")
        self._auth_urls: dict[str, asyncio.Future[str]] = {}
        self._codes: dict[str, asyncio.Future[tuple[str, str | None]]] = {}

    def provider(self, user_id: str) -> OAuthClientProvider:
        loop = asyncio.get_event_loop()

        async def redirect_handler(url: str) -> None:
            fut = self._auth_urls.setdefault(user_id, loop.create_future())
            if not fut.done():
                fut.set_result(url)

        async def callback_handler() -> tuple[str, str | None]:
            fut = self._codes.setdefault(user_id, loop.create_future())
            try:
                return await asyncio.wait_for(fut, timeout=600)
            finally:
                self._codes.pop(user_id, None)

        return OAuthClientProvider(
            server_url=UPWORK_MCP_URL,
            client_metadata=OAuthClientMetadata(client_name="GigBid", redirect_uris=[AnyUrl(self.redirect_uri)],
                                                grant_types=["authorization_code", "refresh_token"],
                                                response_types=["code"], token_endpoint_auth_method="none"),
            storage=EncryptedTokenStore(user_id),
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )

    async def start(self, user_id: str) -> str:
        """Begin the flow; returns the URL the UI must open. Tokens are stored when it completes."""
        loop = asyncio.get_event_loop()
        self._auth_urls[user_id] = loop.create_future()
        self._codes[user_id] = loop.create_future()
        auth = self.provider(user_id)

        async def handshake() -> None:  # any authenticated request triggers the OAuth dance
            async with httpx.AsyncClient(auth=auth, timeout=30) as c:
                await c.post(UPWORK_MCP_URL, json={"jsonrpc": "2.0", "id": 0, "method": "ping"},
                             headers={"Accept": "application/json, text/event-stream"})

        asyncio.create_task(handshake())
        return await asyncio.wait_for(self._auth_urls[user_id], timeout=30)

    def complete(self, user_id: str, code: str, state: str | None) -> None:
        fut = self._codes.get(user_id)
        if fut is None or fut.done():
            raise ValueError("no OAuth flow in progress for this user")
        fut.set_result((code, state))
