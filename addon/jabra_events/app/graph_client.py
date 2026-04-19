from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp

log = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL_TMPL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
DEFAULT_SCOPE = "https://graph.microsoft.com/.default"


class GraphAuthError(RuntimeError):
    pass


class GraphClient:
    """Microsoft Graph client using client-credentials flow.

    Token acquisition is done via direct HTTP (keeps the dependency surface
    small). Swap to `msal` later if we need caching or certificate auth.
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        session: aiohttp.ClientSession,
    ) -> None:
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._session = session
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    async def _fetch_token(self) -> None:
        if not (self._tenant_id and self._client_id and self._client_secret):
            raise GraphAuthError("Graph credentials are not configured")
        url = TOKEN_URL_TMPL.format(tenant_id=self._tenant_id)
        data = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "grant_type": "client_credentials",
            "scope": DEFAULT_SCOPE,
        }
        async with self._session.post(url, data=data) as resp:
            payload = await resp.json()
            if resp.status != 200:
                raise GraphAuthError(f"Token request failed: {payload}")
            self._token = payload["access_token"]
            # Refresh ~60s before expiry.
            self._token_expires_at = time.time() + int(payload.get("expires_in", 3600)) - 60
            log.info("Acquired Graph token, valid for %ss", payload.get("expires_in"))

    async def _auth_header(self) -> dict[str, str]:
        if self._token is None or time.time() >= self._token_expires_at:
            await self._fetch_token()
        return {"Authorization": f"Bearer {self._token}"}

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = await self._auth_header()
        url = f"{GRAPH_BASE}{path}"
        async with self._session.get(url, headers=headers, params=params) as resp:
            payload = await resp.json()
            if resp.status >= 400:
                raise GraphAuthError(f"GET {path} failed ({resp.status}): {payload}")
            return payload

    async def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {**await self._auth_header(), "Content-Type": "application/json"}
        url = f"{GRAPH_BASE}{path}"
        async with self._session.post(url, headers=headers, json=body) as resp:
            payload = await resp.json() if resp.content_length else {}
            if resp.status >= 400:
                raise GraphAuthError(f"POST {path} failed ({resp.status}): {payload}")
            return payload
