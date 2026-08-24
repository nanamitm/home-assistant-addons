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
    result.update_sky({"hdop": 0.6, "pdop": 1.2, "vdop": 1.0, "gdop": 1.4, "satellites": [{"used": True}, {"used": False}, {}]})
    result.update_tpv(
        {"mode": 3, "lat": 35.1, "lon": 139.2, "altMSL": 12.5, "speed": 1.2, "track": 90, "eph": 2.1},
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
    assert state["hdop"] == 0.6
    assert state["pdop"] == 1.2
    assert state["vdop"] == 1.0
    assert state["gdop"] == 1.4
    assert state["positioning_quality"] == "good"


def test_dop_only_sky_packet_updates_hdop_without_resetting_counts(monkeypatch):
    result = publisher(monkeypatch)
    result.update_sky({"hdop": 0.7, "satellites": [{"used": True}, {"used": False}]})
    result.update_sky({"hdop": 0.5})

    assert result._state["hdop"] == 0.5
    assert result._state["satellites_visible"] == 2
    assert result._state["satellites_used"] == 1


def test_positioning_quality_thresholds(monkeypatch):
    result = publisher(monkeypatch)
    expected = [(0.9, "excellent"), (1.0, "good"), (2.0, "moderate"), (5.0, "poor")]
    for pdop, quality in expected:
        result.update_sky({"pdop": pdop})
        assert result._state["positioning_quality"] == quality


def test_discovery_groups_entities_under_one_device(monkeypatch):
    result = publisher(monkeypatch)
    client = result._client
    result._publish_discovery(client)

    configs = [(topic, json.loads(payload)) for topic, payload, _, _ in client.messages if payload]
    assert len(configs) == 16
    connection = next(config for topic, config in configs if "/binary_sensor/" in topic)
    assert connection["unique_id"] == "roof_gps_connection"
    assert connection["device"]["identifiers"] == ["roof_gps"]
    assert all(config["availability_topic"] == "xgps_web/roof_gps/availability" for _, config in configs)
    assert any(topic.endswith("/device_tracker/roof_gps/position/config") and payload == "" for topic, payload, _, _ in client.messages)


def test_tracker_is_opt_in(monkeypatch):
    monkeypatch.setenv("DEVICE_TRACKER", "true")
    result = publisher(monkeypatch)
    result.update_tpv({"mode": 2, "lat": 35.1, "lon": 139.2, "eph": 3.0}, "now")
    tracker = next(json.loads(payload) for topic, payload, _, _ in result._client.messages if topic.endswith("/tracker"))
    assert tracker == {"state": "not_home", "latitude": 35.1, "longitude": 139.2, "gps_accuracy": 3.0}
