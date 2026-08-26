import asyncio
import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "xgps" / "app"))
from server import XgpsService


class FakeMqtt:
    def update_sky(self, _packet):
        pass

    def update_status(self, _connected, _generation):
        pass

    def update_diagnostics(self, _data_age):
        pass


def test_sky_dop_is_in_live_message_and_snapshot():
    async def exercise():
        service = XgpsService()
        service.mqtt = FakeMqtt()
        messages = []

        async def capture(message):
            messages.append(message)

        service.broadcast = capture
        await service.on_packet(
            {"class": "SKY", "hdop": 0.7, "pdop": 1.1, "vdop": 0.9, "gdop": 1.3, "satellites": [{"PRN": 1, "used": True}]},
            "sky-with-satellites",
        )
        await service.on_packet({"class": "SKY", "hdop": 0.5}, "dop-only")

        assert messages[-1]["hdop"] == 0.5
        assert messages[-1]["pdop"] == 1.1
        assert messages[-1]["positioningQuality"] == "good"
        assert messages[-1]["satellites"] == [{"PRN": 1, "used": True}]
        assert service.snapshot()["hdop"] == 0.5
        assert service.snapshot()["vdop"] == 0.9

    asyncio.run(exercise())


def test_status_loop_survives_a_broadcast_failure():
    async def exercise():
        service = XgpsService()
        service.mqtt = FakeMqtt()
        calls = []

        async def broken(message):
            calls.append(message)
            raise RuntimeError("broadcast is broken")

        service.broadcast = broken
        task = asyncio.create_task(service._status_loop())
        for _ in range(200):
            if calls:
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        assert not task.done()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert calls

    asyncio.run(exercise())


def test_health_fails_after_a_background_task_dies():
    async def exercise():
        service = XgpsService()

        async def boom():
            raise RuntimeError("task is broken")

        task = service._supervise(asyncio.create_task(boom()), "gpsd")
        with contextlib.suppress(RuntimeError):
            await task
        await asyncio.sleep(0)
        assert service.failed_task == "gpsd"

    asyncio.run(exercise())
