import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "xgps" / "app"))
from gpsd_client import GpsdClient


def test_gpsd_watch_and_packet_delivery():
    asyncio.run(_exercise_client())


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
