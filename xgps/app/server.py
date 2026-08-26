"""xgps Web HTTP and WebSocket service."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web
from gpsd_client import GpsdClient
from mqtt_publisher import DOP_FIELDS, MqttPublisher, env_bool, positioning_quality

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
LOGGER = logging.getLogger("xgps")
STATIC_DIR = Path(__file__).with_name("static")
INDEX_HTML = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
# A browser that stops reading must not hold the gpsd read loop open forever.
SEND_TIMEOUT = 5.0


class XgpsService:
    def __init__(self) -> None:
        self.allow_raw = env_bool("RAW_JSON")
        self.satellites: list[dict[str, Any]] = []
        self.tpv: dict[str, Any] = {}
        self.dop: dict[str, float | int | str | None] = {field: None for field in DOP_FIELDS}
        self.dop["positioningQuality"] = None
        self.last_packet_at: str | None = None
        self.last_packet_monotonic: float | None = None
        self.clients: set[web.WebSocketResponse] = set()
        self._closing: set[asyncio.Task[None]] = set()
        self.mqtt = MqttPublisher()
        self.gpsd = GpsdClient(
            os.getenv("GPSD_HOST", "127.0.0.1"),
            int(os.getenv("GPSD_PORT", "2947")),
            float(os.getenv("RECONNECT_INTERVAL", "5")),
            self.on_packet,
            keep_raw=self.allow_raw,
        )
        self.gpsd_task: asyncio.Task[None] | None = None
        self.status_task: asyncio.Task[None] | None = None
        self.failed_task: str | None = None

    async def start(self, _app: web.Application) -> None:
        self.mqtt.start()
        self.gpsd_task = self._supervise(asyncio.create_task(self.gpsd.run()), "gpsd")
        self.status_task = self._supervise(asyncio.create_task(self._status_loop()), "status")

    def _supervise(self, task: asyncio.Task[None], name: str) -> asyncio.Task[None]:
        """Surface a background task that ends on its own, so /health can fail."""

        def finished(completed: asyncio.Task[None]) -> None:
            if completed.cancelled():
                return
            error = completed.exception()
            LOGGER.error("The %s task stopped unexpectedly", name, exc_info=error)
            self.failed_task = name

        task.add_done_callback(finished)
        return task

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
        self.mqtt.stop()

    async def _status_loop(self) -> None:
        previous: tuple[bool, str, str, int] | None = None
        while True:
            try:
                current = (self.gpsd.connected, self.gpsd.status_code, self.gpsd.status, self.gpsd.connection_generation)
                if current != previous:
                    self.mqtt.update_status(current[0], current[3])
                    await self.broadcast(
                        {"type": "status", "connected": current[0], "statusCode": current[1], "detail": current[2]}
                    )
                    previous = current
                data_age = None
                if self.last_packet_monotonic is not None:
                    data_age = max(0, int(asyncio.get_running_loop().time() - self.last_packet_monotonic))
                self.mqtt.update_diagnostics(data_age)
            except asyncio.CancelledError:
                raise
            except Exception:
                # One bad iteration must not stop status and diagnostic updates.
                LOGGER.exception("Status update failed")
            await asyncio.sleep(1)

    async def on_packet(self, packet: dict[str, Any], raw: str) -> None:
        self.last_packet_at = datetime.now(timezone.utc).isoformat()
        self.last_packet_monotonic = asyncio.get_running_loop().time()
        packet_class = packet.get("class")
        message: dict[str, Any] | None = None
        if packet_class == "SKY":
            self.mqtt.update_sky(packet)
            for field in DOP_FIELDS:
                if isinstance(packet.get(field), (int, float)):
                    self.dop[field] = packet[field]
            if isinstance(self.dop["pdop"], (int, float)):
                self.dop["positioningQuality"] = positioning_quality(self.dop["pdop"])
            if isinstance(packet.get("satellites"), list):
                self.satellites = [item for item in packet["satellites"] if isinstance(item, dict)]
            message = {
                "type": "sky",
                "satellites": self.satellites,
                **self.dop,
                "receivedAt": self.last_packet_at,
            }
        elif packet_class == "TPV":
            self.tpv = packet
            message = {"type": "tpv", "tpv": self.tpv, "receivedAt": self.last_packet_at}
            self.mqtt.update_tpv(self.tpv, self.last_packet_at)
        elif packet_class == "DEVICE":
            self.mqtt.update_device(packet)
        elif packet_class == "DEVICES" and isinstance(packet.get("devices"), list):
            device = next((item for item in packet["devices"] if isinstance(item, dict)), None)
            if device is not None:
                self.mqtt.update_device(device)
        if message is not None:
            await self.broadcast(message)
        if self.allow_raw:
            await self.broadcast({"type": "raw", "line": raw})

    async def _send(self, client: web.WebSocketResponse, payload: str) -> web.WebSocketResponse | None:
        """Send to one client, returning it when it should be dropped."""
        try:
            await asyncio.wait_for(client.send_str(payload), timeout=SEND_TIMEOUT)
        except asyncio.TimeoutError:
            LOGGER.warning("Dropping a WebSocket client that stopped reading")
        except (ConnectionError, RuntimeError):
            pass
        except Exception:
            LOGGER.exception("Unexpected WebSocket send failure")
        else:
            return None
        return client

    async def broadcast(self, message: dict[str, Any]) -> None:
        clients = tuple(self.clients)
        if not clients:
            return
        payload = json.dumps(message, separators=(",", ":"))
        # Send concurrently. Awaiting one client at a time let a single stalled
        # browser block every other client and the gpsd read loop behind it.
        results = await asyncio.gather(*(self._send(client, payload) for client in clients))
        stale = [client for client in results if client is not None]
        if not stale:
            return
        self.clients.difference_update(stale)
        for client in stale:
            task = asyncio.create_task(client.close())
            self._closing.add(task)
            task.add_done_callback(self._closing.discard)

    def snapshot(self) -> dict[str, Any]:
        return {
            "type": "snapshot",
            "connected": self.gpsd.connected,
            "statusCode": self.gpsd.status_code,
            "detail": self.gpsd.status,
            "gpsdHost": self.gpsd.host,
            "gpsdPort": self.gpsd.port,
            "lastPacketAt": self.last_packet_at,
            "satellites": self.satellites,
            "tpv": self.tpv,
            **self.dop,
            "rawEnabled": self.allow_raw,
            "raw": list(self.gpsd.raw_lines),
        }


service = XgpsService()


async def index(request: web.Request) -> web.Response:
    """Serve the page with a <base> element pinned to the ingress path.

    Ingress serves the add-on under a per-session path, and the relative asset
    URLs in the page resolve against the request path. Requested without its
    trailing slash, that path loses its last segment and every asset 404s. The
    Supervisor tells us the real base in X-Ingress-Path, so use it.
    """
    ingress_path = request.headers.get("X-Ingress-Path", "").rstrip("/")
    html = INDEX_HTML
    if ingress_path:
        html = html.replace("<head>", f'<head>\n  <base href="{escape(ingress_path)}/">', 1)
    return web.Response(text=html, content_type="text/html")


async def health(_request: web.Request) -> web.Response:
    """Report process health without treating a remote gpsd outage as fatal."""
    payload: dict[str, Any] = {
        "status": "ok",
        "gpsd_connected": service.gpsd.connected,
        "gpsd_status": service.gpsd.status,
    }
    if service.failed_task is not None:
        # A dead background task cannot recover on its own, so fail the
        # Supervisor watchdog and let it restart the add-on.
        payload["status"] = "error"
        payload["failed_task"] = service.failed_task
        return web.json_response(payload, status=503)
    return web.json_response(payload)


async def websocket(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    service.clients.add(ws)
    await ws.send_json(service.snapshot())
    try:
        async for message in ws:
            if message.type == WSMsgType.TEXT:
                try:
                    command = json.loads(message.data)
                except json.JSONDecodeError:
                    continue
                if command.get("action") == "reconnect":
                    await service.gpsd.reconnect()
                    await ws.send_json(
                        {
                            "type": "status",
                            "connected": False,
                            "statusCode": "reconnecting",
                            "detail": service.gpsd.status,
                        }
                    )
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
