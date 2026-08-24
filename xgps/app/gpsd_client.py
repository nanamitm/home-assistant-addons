"""Asynchronous gpsd JSON client with reconnect and state fan-out."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections import deque
from typing import Any, Awaitable, Callable

LOGGER = logging.getLogger(__name__)
PacketHandler = Callable[[dict[str, Any], str], Awaitable[None]]


class GpsdClient:
    def __init__(self, host: str, port: int, reconnect_interval: float, packet_handler: PacketHandler) -> None:
        self.host = host
        self.port = port
        self.reconnect_interval = reconnect_interval
        self.packet_handler = packet_handler
        self.connected = False
        self.status = "Starting"
        self.status_code = "starting"
        self.raw_lines: deque[str] = deque(maxlen=500)
        self._stopping = asyncio.Event()
        self._writer: asyncio.StreamWriter | None = None

    async def run(self) -> None:
        while not self._stopping.is_set():
            try:
                self.status = f"Connecting to {self.host}:{self.port}"
                self.status_code = "connecting"
                reader, self._writer = await asyncio.open_connection(self.host, self.port)
                self.connected = True
                self.status = f"Connected to {self.host}:{self.port}"
                self.status_code = "connected"
                LOGGER.info(self.status)
                self._writer.write(b'?WATCH={"enable":true,"json":true,"scaled":true};\n')
                await self._writer.drain()
                await self._read_packets(reader)
            except asyncio.CancelledError:
                raise
            except (OSError, asyncio.TimeoutError) as err:
                self.status = f"gpsd connection error: {err}"
                self.status_code = "connection_error"
                LOGGER.warning(self.status)
            finally:
                self.connected = False
                if self._writer is not None:
                    self._writer.close()
                    with contextlib.suppress(OSError):
                        await self._writer.wait_closed()
                    self._writer = None
            if not self._stopping.is_set():
                try:
                    await asyncio.wait_for(self._stopping.wait(), timeout=self.reconnect_interval)
                except asyncio.TimeoutError:
                    pass

    async def stop(self) -> None:
        self._stopping.set()
        if self._writer is not None:
            self._writer.close()

    async def _read_packets(self, reader: asyncio.StreamReader) -> None:
        while not self._stopping.is_set():
            line_bytes = await reader.readline()
            if not line_bytes:
                self.status = "gpsd closed the connection"
                self.status_code = "connection_closed"
                return
            line = line_bytes.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            self.raw_lines.append(line)
            try:
                packet = json.loads(line)
            except json.JSONDecodeError:
                LOGGER.debug("Ignored invalid gpsd JSON")
                continue
            if isinstance(packet, dict):
                await self.packet_handler(packet, line)
