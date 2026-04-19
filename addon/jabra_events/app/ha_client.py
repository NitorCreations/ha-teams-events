from __future__ import annotations

import logging
from typing import Any

import aiohttp

log = logging.getLogger(__name__)


class HAClient:
    """Minimal Home Assistant REST client for calling services."""

    def __init__(self, base_url: str, token: str, session: aiohttp.ClientSession) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._session = session

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def call_service(
        self, domain: str, service: str, data: dict[str, Any] | None = None
    ) -> None:
        url = f"{self._base_url}/api/services/{domain}/{service}"
        async with self._session.post(url, headers=self._headers, json=data or {}) as resp:
            resp.raise_for_status()
            log.debug("HA service %s.%s returned %s", domain, service, resp.status)

    async def get_state(self, entity_id: str) -> dict[str, Any] | None:
        url = f"{self._base_url}/api/states/{entity_id}"
        async with self._session.get(url, headers=self._headers) as resp:
            if resp.status == 404:
                return None
            resp.raise_for_status()
            return await resp.json()

    async def run_room_mode(self, mode_id: str) -> None:
        await self.call_service("room_modes", "run_mode", {"mode_id": mode_id})
