import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "xgps" / "app"))
from server import XgpsService


class FakeMqtt:
    def update_sky(self, _packet):
        pass


def test_sky_hdop_is_in_live_message_and_snapshot():
    async def exercise():
        service = XgpsService()
        service.mqtt = FakeMqtt()
        messages = []

        async def capture(message):
            messages.append(message)

        service.broadcast = capture
        await service.on_packet(
            {"class": "SKY", "hdop": 0.7, "satellites": [{"PRN": 1, "used": True}]},
            "sky-with-satellites",
        )
        await service.on_packet({"class": "SKY", "hdop": 0.5}, "dop-only")

        assert messages[-1]["hdop"] == 0.5
        assert messages[-1]["satellites"] == [{"PRN": 1, "used": True}]
        assert service.snapshot()["hdop"] == 0.5

    asyncio.run(exercise())
