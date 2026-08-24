"""xgps Web HTTP and WebSocket service."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web
from gpsd_client import GpsdClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
LOGGER = logging.getLogger("xgps")
STATIC_DIR = Path(__file__).with_name("static")


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


class XgpsService:
    def __init__(self) -> None:
        self.allow_raw = env_bool("RAW_JSON")
        self.satellites: list[dict[str, Any]] = []
        self.tpv: dict[str, Any] = {}
        self.clients: set[web.WebSocketResponse] = set()
        self.gpsd = GpsdClient(
            os.getenv("GPSD_HOST", "127.0.0.1"),
            int(os.getenv("GPSD_PORT", "2947")),
            float(os.getenv("RECONNECT_INTERVAL", "5")),
            self.on_packet,
        )
        self.gpsd_task: asyncio.Task[None] | None = None
        self.status_task: asyncio.Task[None] | None = None

    async def start(self, _app: web.Application) -> None:
        self.gpsd_task = asyncio.create_task(self.gpsd.run())
        self.status_task = asyncio.create_task(self._status_loop())

    async def stop(self, _app: web.Application) -> None:
        await self.gpsd.stop()
        if self.gpsd_task is not None:
            self.gpsd_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.gpsd_task
        if self.status_task is not None:
            self.status_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.status_task

    async def _status_loop(self) -> None:
        previous: tuple[bool, str] | None = None
        while True:
            current = (self.gpsd.connected, self.gpsd.status)
            if current != previous:
                await self.broadcast(
                    {"type": "status", "connected": current[0], "status": current[1]}
                )
                previous = current
            await asyncio.sleep(1)

    async def on_packet(self, packet: dict[str, Any], raw: str) -> None:
        packet_class = packet.get("class")
        message: dict[str, Any] | None = None
        if packet_class == "SKY" and isinstance(packet.get("satellites"), list):
            self.satellites = [item for item in packet["satellites"] if isinstance(item, dict)]
            message = {"type": "sky", "satellites": self.satellites}
        elif packet_class == "TPV":
            self.tpv = packet
            message = {"type": "tpv", "tpv": self.tpv}
        if message is not None:
            await self.broadcast(message)
        if self.allow_raw:
            await self.broadcast({"type": "raw", "line": raw})

    async def broadcast(self, message: dict[str, Any]) -> None:
        stale = []
        payload = json.dumps(message, separators=(",", ":"))
        for client in tuple(self.clients):
            try:
                await client.send_str(payload)
            except (ConnectionError, RuntimeError):
                stale.append(client)
        self.clients.difference_update(stale)

    def snapshot(self) -> dict[str, Any]:
        return {"type":"snapshot", "connected":self.gpsd.connected, "status":self.gpsd.status, "satellites":self.satellites, "tpv":self.tpv, "rawEnabled":self.allow_raw, "raw":list(self.gpsd.raw_lines) if self.allow_raw else []}


service = XgpsService()


async def index(_request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


async def health(_request: web.Request) -> web.Response:
    """Report process health without treating a remote gpsd outage as fatal."""
    return web.json_response(
        {
            "status": "ok",
            "gpsd_connected": service.gpsd.connected,
            "gpsd_status": service.gpsd.status,
        }
    )


async def websocket(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    service.clients.add(ws)
    await ws.send_json(service.snapshot())
    try:
        async for message in ws:
            if message.type == WSMsgType.ERROR:
                LOGGER.debug("WebSocket error: %s", ws.exception())
                break
    finally:
        service.clients.discard(ws)
    return ws


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/ws", websocket)
    app.router.add_static("/static", STATIC_DIR, append_version=True)
    app.on_startup.append(service.start)
    app.on_cleanup.append(service.stop)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="127.0.0.1", port=8098, print=None)
