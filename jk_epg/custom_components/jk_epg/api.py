"""Async client for the JK EPG add-on."""

from __future__ import annotations

from datetime import date
from typing import Any

from aiohttp import ClientSession


class JkEpgApi:
    """Small JSON API client."""

    def __init__(self, session: ClientSession, base_url: str) -> None:
        self._session = session
        self.base_url = base_url.rstrip("/")

    async def _get(self, path: str) -> dict[str, Any]:
        async with self._session.get(f"{self.base_url}/{path}", timeout=20) as response:
            response.raise_for_status()
            return await response.json()

    async def health(self) -> None:
        await self._get("api/health")

    async def schedule(self, broadcast_date: date | None = None) -> dict[str, Any]:
        suffix = "" if broadcast_date is None else f"?date={broadcast_date.isoformat()}"
        return await self._get(f"api/programs/schedule{suffix}")
