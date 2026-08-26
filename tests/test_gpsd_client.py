import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "xgps" / "app"))
from gpsd_client import GpsdClient


def test_gpsd_watch_and_packet_delivery():
    asyncio.run(_exercise_client())


def test_silent_socket_times_out_and_reconnects():
    async def exercise():
        done = asyncio.Event()

        async def silent_gpsd(reader, writer):
            await reader.readline()
            await done.wait()

        async def handler(_packet, _raw):
            pass

        server = await asyncio.start_server(silent_gpsd, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        client = GpsdClient("127.0.0.1", port, 60, handler, read_timeout=0.05)
        task = asyncio.create_task(client.run())
        for _ in range(100):
            if client.status_code == "read_timeout":
                break
            await asyncio.sleep(0.01)
        await client.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        done.set()
        server.close()
        await server.wait_closed()

        assert client.status_code == "read_timeout"
        assert client.connected is False

    asyncio.run(exercise())


def test_handler_error_does_not_end_the_client():
    async def exercise():
        attempts = []

        async def failing_gpsd(reader, writer):
            attempts.append(await reader.readline())
            writer.write(b'{"class":"SKY"}\n')
            await writer.drain()
            await asyncio.sleep(0.2)

        async def handler(_packet, _raw):
            raise ValueError("handler is broken")

        server = await asyncio.start_server(failing_gpsd, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        client = GpsdClient("127.0.0.1", port, 0.01, handler)
        task = asyncio.create_task(client.run())
        for _ in range(200):
            if len(attempts) >= 2:
                break
            await asyncio.sleep(0.01)
        await client.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        server.close()
        await server.wait_closed()

        # run() survived the handler error and reconnected instead of ending.
        assert len(attempts) >= 2
        assert client.status_code == "client_error"

    asyncio.run(exercise())


def test_manual_reconnect_sets_state():
    async def exercise():
        async def handler(_packet, _raw):
            pass

        client = GpsdClient("gpsd.local", 2947, 5, handler)
        await client.reconnect()
        assert client.status_code == "reconnecting"
        assert client._reconnect.is_set()

    asyncio.run(exercise())


async def _exercise_client():
    received = []
    watch = asyncio.Future()

    async def fake_gpsd(reader, writer):
        watch.set_result(await reader.readline())
        writer.write(b'{"class":"SKY","satellites":[{"PRN":1}]}\n')
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def handler(packet, raw):
        received.append((packet, raw))

    server = await asyncio.start_server(fake_gpsd, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = GpsdClient("127.0.0.1", port, 60, handler)
    task = asyncio.create_task(client.run())
    await asyncio.wait_for(watch, 1)
    for _ in range(20):
        if received:
            break
        await asyncio.sleep(0.01)
    await client.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    server.close()
    await server.wait_closed()

    assert b'"enable":true' in watch.result()
    assert received[0][0]["class"] == "SKY"
    assert json.loads(received[0][1])["satellites"][0]["PRN"] == 1
    assert client.connection_generation == 1
    assert client.status_code in {"connected", "connection_closed"}
