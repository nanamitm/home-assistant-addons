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
    result.update_status(True, 3)
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
    assert state["reconnect_count"] == 2
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
    assert state["quality_degraded"] is False
    assert state["fix_unavailable"] is False


def test_dop_only_sky_packet_updates_hdop_without_resetting_counts(monkeypatch):
    result = publisher(monkeypatch)
    result.update_sky({"hdop": 0.7, "satellites": [{"used": True}, {"used": False}]})
    result.update_sky({"hdop": 0.5})

    assert result._state["hdop"] == 0.5
    assert result._state["satellites_visible"] == 2
    assert result._state["satellites_used"] == 1


def test_altitude_prefers_mean_sea_level(monkeypatch):
    result = publisher(monkeypatch)
    result.update_tpv({"mode": 3, "altHAE": 51.4, "altMSL": 12.5, "alt": 12.5}, "now")
    assert result._state["altitude"] == 12.5

    result = publisher(monkeypatch)
    result.update_tpv({"mode": 3, "altHAE": 51.4}, "now")
    assert result._state["altitude"] == 51.4


def test_sky_hdop_wins_over_the_tpv_copy(monkeypatch):
    result = publisher(monkeypatch)
    result.update_sky({"hdop": 0.6})
    result.update_tpv({"mode": 3, "hdop": 0.9, "lat": 35.1, "lon": 139.2}, "now")
    assert result._state["hdop"] == 0.6

    published = len(result._client.messages)
    result.update_tpv({"mode": 3, "hdop": 0.9, "lat": 35.1, "lon": 139.2}, "now")
    assert len(result._client.messages) == published


def test_tpv_hdop_is_used_when_sky_never_reports_one(monkeypatch):
    result = publisher(monkeypatch)
    result.update_sky({"pdop": 1.2})
    result.update_tpv({"mode": 3, "hdop": 0.9}, "now")
    assert result._state["hdop"] == 0.9


def test_satellite_counts_by_system(monkeypatch):
    result = publisher(monkeypatch)
    result.update_sky(
        {
            "satellites": [
                {"gnssid": 0, "used": True},
                {"gnssid": 0, "used": False},
                {"gnssid": 1, "used": False},
                {"gnssid": 1, "used": True},
                {"gnssid": 2, "used": True},
                {"gnssid": 3, "used": True},
                {"gnssid": 5, "used": True},
                {"gnssid": 6, "used": True},
                {"gnssid": 6, "used": False},
            ]
        }
    )

    assert result._state["gps_satellites_used"] == 1
    assert result._state["sbas_satellites_visible"] == 2
    assert result._state["galileo_satellites_used"] == 1
    assert result._state["beidou_satellites_used"] == 1
    assert result._state["qzss_satellites_used"] == 1
    assert result._state["glonass_satellites_used"] == 1


def test_positioning_quality_thresholds(monkeypatch):
    result = publisher(monkeypatch)
    expected = [(0.9, "excellent"), (1.0, "good"), (2.0, "moderate"), (5.0, "poor")]
    for pdop, quality in expected:
        result.update_sky({"pdop": pdop})
        assert result._state["positioning_quality"] == quality
        assert result._state["quality_degraded"] is (quality in {"moderate", "poor"})


def test_diagnostics_and_receiver(monkeypatch):
    result = publisher(monkeypatch)
    result.update_diagnostics(None)
    assert result._state["data_stale"] is True
    result.update_diagnostics(15)
    assert result._state["data_stale"] is False
    result.update_diagnostics(16)
    assert result._state["data_age"] == 16
    assert result._state["data_stale"] is True

    result.update_device(
        {"path": "/dev/ttyACM0", "driver": "u-blox", "subtype": "ZED-F9P", "bps": 115200, "ignored": [1]}
    )
    assert result._state["receiver_name"] == "ZED-F9P"
    assert result._state["receiver"] == {
        "path": "/dev/ttyACM0",
        "driver": "u-blox",
        "subtype": "ZED-F9P",
        "bps": 115200,
    }


def test_ticking_data_age_does_not_republish_every_second(monkeypatch):
    result = publisher(monkeypatch)
    result.update_diagnostics(0)
    published = len(result._client.messages)

    # A gpsd outage makes data_age tick once a second. The first tick crosses
    # the stale threshold and must be published; the rest must stay quiet.
    for data_age in range(1, 60):
        result.update_diagnostics(data_age)

    assert result._state["data_age"] == 59
    assert result._state["data_stale"] is True
    assert len(result._client.messages) == published + 1

    state = json.loads(result._client.messages[-1][1])
    assert state["data_stale"] is True


def test_data_age_is_refreshed_on_a_slow_cadence(monkeypatch):
    result = publisher(monkeypatch)
    result.update_diagnostics(0)
    result.update_diagnostics(20)
    published = len(result._client.messages)

    result._data_age_published_at -= 31
    result.update_diagnostics(21)

    assert len(result._client.messages) == published + 1
    assert json.loads(result._client.messages[-1][1])["data_age"] == 21


def test_unchanged_state_is_not_republished(monkeypatch):
    result = publisher(monkeypatch)
    result.update_diagnostics(0)
    published = len(result._client.messages)
    result.update_diagnostics(0)
    assert len(result._client.messages) == published


def test_discovery_groups_entities_under_one_device(monkeypatch):
    result = publisher(monkeypatch)
    client = result._client
    result._publish_discovery(client)

    configs = [(topic, json.loads(payload)) for topic, payload, _, _ in client.messages if payload]
    assert len(configs) == 28
    connection = next(config for topic, config in configs if "/binary_sensor/" in topic)
    assert connection["unique_id"] == "roof_gps_connection"
    assert connection["device"]["identifiers"] == ["roof_gps"]
    assert all(config["availability_topic"] == "xgps_web/roof_gps/availability" for _, config in configs)
    receiver = next(config for topic, config in configs if topic.endswith("/receiver/config"))
    assert receiver["entity_category"] == "diagnostic"
    assert "json_attributes_template" in receiver
    assert any(topic.endswith("/device_tracker/roof_gps/position/config") and payload == "" for topic, payload, _, _ in client.messages)


def test_version_comes_from_the_image_build(monkeypatch):
    monkeypatch.setenv("XGPS_VERSION", "1.1.0")
    result = publisher(monkeypatch)
    result._publish_discovery(result._client)
    config = next(json.loads(payload) for _, payload, _, _ in result._client.messages if payload)
    assert config["device"]["sw_version"] == "1.1.0"
    assert config["origin"]["sw_version"] == "1.1.0"


def test_version_is_omitted_when_the_build_did_not_supply_one(monkeypatch):
    monkeypatch.delenv("XGPS_VERSION", raising=False)
    result = publisher(monkeypatch)
    result._publish_discovery(result._client)
    config = next(json.loads(payload) for _, payload, _, _ in result._client.messages if payload)
    assert "sw_version" not in config["device"]
    assert "sw_version" not in config["origin"]


def test_tracker_is_opt_in(monkeypatch):
    monkeypatch.setenv("DEVICE_TRACKER", "true")
    result = publisher(monkeypatch)
    result.update_tpv({"mode": 2, "lat": 35.1, "lon": 139.2, "eph": 3.0}, "now")
    tracker = next(json.loads(payload) for topic, payload, _, _ in result._client.messages if topic.endswith("/tracker"))
    assert tracker == {"latitude": 35.1, "longitude": 139.2, "gps_accuracy": 3.0}


def test_tracker_omits_unknown_accuracy(monkeypatch):
    monkeypatch.setenv("DEVICE_TRACKER", "true")
    result = publisher(monkeypatch)
    result.update_tpv({"mode": 2, "lat": 35.1, "lon": 139.2}, "now")
    tracker = next(json.loads(payload) for topic, payload, _, _ in result._client.messages if topic.endswith("/tracker"))
    assert tracker == {"latitude": 35.1, "longitude": 139.2}


def test_tracker_discovery_leaves_zone_detection_to_home_assistant(monkeypatch):
    monkeypatch.setenv("DEVICE_TRACKER", "true")
    result = publisher(monkeypatch)
    result._publish_discovery(result._client)

    config = next(
        json.loads(payload)
        for topic, payload, _, _ in result._client.messages
        if topic.endswith("/device_tracker/roof_gps/position/config")
    )
    # A state topic would set location_name, which overrides zone detection.
    assert "state_topic" not in config
    assert "value_template" not in config
    assert config["json_attributes_topic"] == "xgps_web/roof_gps/tracker"
    assert config["source_type"] == "gps"
