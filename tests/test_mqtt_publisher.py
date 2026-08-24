import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "xgps" / "app"))
from mqtt_publisher import MqttPublisher


class PublishResult:
    def wait_for_publish(self, timeout=None):
        return None


class FakeClient:
    def __init__(self):
        self.messages = []
        self.connected = True

    def publish(self, topic, payload, qos=0, retain=False):
        self.messages.append((topic, payload, qos, retain))
        return PublishResult()

    def is_connected(self):
        return self.connected


def publisher(monkeypatch):
    monkeypatch.setenv("MQTT_ENABLED", "true")
    monkeypatch.setenv("DEVICE_ID", "roof_gps")
    monkeypatch.setenv("DEVICE_NAME", "Roof GPS")
    result = MqttPublisher()
    result._client = FakeClient()
    return result


def test_state_combines_sky_and_tpv(monkeypatch):
    result = publisher(monkeypatch)
    result.update_status(True)
    result.update_sky([{"used": True}, {"used": False}, {}])
    result.update_tpv(
        {"mode": 3, "lat": 35.1, "lon": 139.2, "altMSL": 12.5, "speed": 1.2, "track": 90, "hdop": 0.8, "eph": 2.1},
        "2026-08-24T12:00:00+00:00",
    )

    topic, payload, qos, retained = result._client.messages[-1]
    state = json.loads(payload)
    assert topic == "xgps_web/roof_gps/state"
    assert (qos, retained) == (1, True)
    assert state["gpsd_connected"] is True
    assert state["fix_mode"] == "3D"
    assert state["satellites_visible"] == 3
    assert state["satellites_used"] == 1
    assert state["latitude"] == 35.1
    assert state["altitude"] == 12.5


def test_discovery_groups_entities_under_one_device(monkeypatch):
    result = publisher(monkeypatch)
    client = result._client
    result._publish_discovery(client)

    configs = [(topic, json.loads(payload)) for topic, payload, _, _ in client.messages]
    assert len(configs) == 12
    connection = next(config for topic, config in configs if "/binary_sensor/" in topic)
    assert connection["unique_id"] == "roof_gps_connection"
    assert connection["device"]["identifiers"] == ["roof_gps"]
    assert all(config["availability_topic"] == "xgps_web/roof_gps/availability" for _, config in configs)


def test_tracker_is_opt_in(monkeypatch):
    monkeypatch.setenv("DEVICE_TRACKER", "true")
    result = publisher(monkeypatch)
    result.update_tpv({"mode": 2, "lat": 35.1, "lon": 139.2, "eph": 3.0}, "now")
    tracker = next(json.loads(payload) for topic, payload, _, _ in result._client.messages if topic.endswith("/tracker"))
    assert tracker == {"state": "not_home", "latitude": 35.1, "longitude": 139.2, "gps_accuracy": 3.0}
