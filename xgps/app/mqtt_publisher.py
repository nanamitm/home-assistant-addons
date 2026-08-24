"""Home Assistant MQTT Discovery publisher for xgps Web."""
from __future__ import annotations

import json
import logging
import os
import threading
import contextlib
from copy import deepcopy
from typing import Any

import paho.mqtt.client as mqtt

LOGGER = logging.getLogger(__name__)
DOP_FIELDS = ("hdop", "pdop", "vdop", "gdop")


def positioning_quality(pdop: float | int) -> str:
    """Classify PDOP using simple, stable thresholds for automation use."""
    if pdop < 1:
        return "excellent"
    if pdop < 2:
        return "good"
    if pdop < 5:
        return "moderate"
    return "poor"


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


class MqttPublisher:
    """Publish one retained state document and Home Assistant discovery configs."""

    def __init__(self) -> None:
        self.enabled = env_bool("MQTT_ENABLED")
        self.host = os.getenv("MQTT_HOST", "")
        self.port = int(os.getenv("MQTT_PORT", "1883"))
        self.username = os.getenv("MQTT_USER", "")
        self.password = os.getenv("MQTT_PASS", "")
        self.discovery_prefix = os.getenv("DISCOVERY_PREFIX", "homeassistant").strip("/")
        self.device_name = os.getenv("DEVICE_NAME", "xgps Web")
        self.device_id = os.getenv("DEVICE_ID", "xgps_web")
        self.tracker_enabled = env_bool("DEVICE_TRACKER")
        self.base_topic = f"xgps_web/{self.device_id}"
        self.state_topic = f"{self.base_topic}/state"
        self.availability_topic = f"{self.base_topic}/availability"
        self.tracker_topic = f"{self.base_topic}/tracker"
        self._state: dict[str, Any] = {
            "gpsd_connected": False,
            "fix_mode": "No fix",
            "fix_unavailable": True,
            "data_stale": True,
            "satellites_visible": 0,
            "satellites_used": 0,
            "reconnect_count": 0,
        }
        self._lock = threading.Lock()
        self._client: mqtt.Client | None = None

    def start(self) -> None:
        if not self.enabled:
            LOGGER.info("Home Assistant MQTT entities are disabled")
            return
        kwargs: dict[str, Any] = {"client_id": f"xgps-web-{self.device_id}", "clean_session": True}
        if hasattr(mqtt, "CallbackAPIVersion"):
            kwargs["callback_api_version"] = mqtt.CallbackAPIVersion.VERSION2
        self._client = mqtt.Client(**kwargs)
        if self.username:
            self._client.username_pw_set(self.username, self.password)
        self._client.will_set(self.availability_topic, "offline", qos=1, retain=True)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        LOGGER.info("Connecting to MQTT broker at %s:%s", self.host, self.port)
        self._client.connect_async(self.host, self.port, keepalive=60)
        self._client.loop_start()

    def stop(self) -> None:
        if self._client is None:
            return
        with contextlib.suppress(RuntimeError, ValueError):
            self._client.publish(self.availability_topic, "offline", qos=1, retain=True).wait_for_publish(timeout=2)
        self._client.disconnect()
        self._client.loop_stop()
        self._client = None

    def update_status(self, connected: bool, connection_generation: int) -> None:
        self.update(
            {
                "gpsd_connected": connected,
                "reconnect_count": max(connection_generation - 1, 0),
            }
        )

    def update_diagnostics(self, data_age: int | None) -> None:
        self.update(
            {
                "data_age": data_age,
                "data_stale": data_age is None or data_age > 15,
            }
        )

    def update_device(self, device: dict[str, Any]) -> None:
        details = {
            key: device[key]
            for key in ("path", "driver", "subtype", "subtype1", "activated", "bps")
            if isinstance(device.get(key), (str, int, float))
        }
        name = details.get("subtype") or details.get("driver") or details.get("path")
        if name:
            self.update({"receiver_name": name, "receiver": details})

    def update_sky(self, sky: dict[str, Any]) -> None:
        values: dict[str, Any] = {}
        satellites = sky.get("satellites")
        if isinstance(satellites, list):
            values.update(
                {
                    "satellites_visible": len(satellites),
                    "satellites_used": sum(
                        bool(satellite.get("used"))
                        for satellite in satellites
                        if isinstance(satellite, dict)
                    ),
                }
            )
        for field in DOP_FIELDS:
            value = sky.get(field)
            if isinstance(value, (int, float)):
                values[field] = value
        if "pdop" in values:
            values["positioning_quality"] = positioning_quality(values["pdop"])
            values["quality_degraded"] = values["positioning_quality"] in {"moderate", "poor"}
        if values:
            self.update(values)

    def update_tpv(self, tpv: dict[str, Any], received_at: str) -> None:
        mode = tpv.get("mode")
        values: dict[str, Any] = {
            "fix_mode": {2: "2D", 3: "3D"}.get(mode, "No fix"),
            "fix_unavailable": mode not in {2, 3},
            "last_update": received_at,
        }
        fields = {
            "lat": "latitude",
            "lon": "longitude",
            "altMSL": "altitude",
            "alt": "altitude",
            "speed": "speed",
            "track": "track",
            "hdop": "hdop",
            "eph": "horizontal_error",
        }
        for source, target in fields.items():
            value = tpv.get(source)
            if isinstance(value, (int, float)) and target not in values:
                values[target] = value
        self.update(values)

    def update(self, values: dict[str, Any]) -> None:
        with self._lock:
            if all(self._state.get(key) == value for key, value in values.items()):
                return
            self._state.update(values)
            state = deepcopy(self._state)
        if self._client is not None and self._client.is_connected():
            self._publish_state(state)

    def _on_connect(self, client: mqtt.Client, _userdata: Any, _flags: Any, reason_code: Any, _properties: Any = None) -> None:
        if reason_code != 0:
            LOGGER.error("MQTT connection rejected: %s", reason_code)
            return
        LOGGER.info("Connected to MQTT broker; publishing Home Assistant discovery")
        self._publish_discovery(client)
        client.publish(self.availability_topic, "online", qos=1, retain=True)
        with self._lock:
            state = deepcopy(self._state)
        self._publish_state(state)

    def _on_disconnect(self, _client: mqtt.Client, _userdata: Any, *args: Any) -> None:
        # Paho 1.x passes only the result code; Paho 2.x also passes flags and properties.
        reason_code = args[-2] if len(args) >= 2 else args[-1]
        if reason_code != 0:
            LOGGER.warning("Unexpected MQTT disconnection: %s", reason_code)

    def _publish_state(self, state: dict[str, Any]) -> None:
        assert self._client is not None
        self._client.publish(self.state_topic, json.dumps(state, separators=(",", ":")), qos=1, retain=True)
        if self.tracker_enabled and "latitude" in state and "longitude" in state:
            tracker = {
                "state": "not_home",
                "latitude": state["latitude"],
                "longitude": state["longitude"],
                "gps_accuracy": state.get("horizontal_error", 0),
            }
            self._client.publish(self.tracker_topic, json.dumps(tracker, separators=(",", ":")), qos=1, retain=True)

    def _publish_discovery(self, client: mqtt.Client) -> None:
        device = {
            "identifiers": [self.device_id],
            "name": self.device_name,
            "manufacturer": "nanamitm",
            "model": "xgps Web",
            "sw_version": "0.6.0",
        }
        common = {
            "state_topic": self.state_topic,
            "availability_topic": self.availability_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": device,
            "origin": {"name": "xgps Web", "sw_version": "0.6.0", "support_url": "https://github.com/nanamitm/home-assistant-addons"},
        }
        entities = {
            "connection": ("binary_sensor", {"name": "GPSD connection", "device_class": "connectivity", "value_template": "{{ value_json.gpsd_connected }}", "payload_on": "True", "payload_off": "False"}),
            "data_stale": ("binary_sensor", {"name": "Data stale", "device_class": "problem", "value_template": "{{ value_json.data_stale }}", "payload_on": "True", "payload_off": "False", "entity_category": "diagnostic"}),
            "fix_unavailable": ("binary_sensor", {"name": "Fix unavailable", "device_class": "problem", "value_template": "{{ value_json.fix_unavailable }}", "payload_on": "True", "payload_off": "False", "entity_category": "diagnostic"}),
            "quality_degraded": ("binary_sensor", {"name": "Positioning quality degraded", "device_class": "problem", "value_template": "{{ value_json.quality_degraded | default(false) }}", "payload_on": "True", "payload_off": "False", "entity_category": "diagnostic"}),
            "fix_mode": ("sensor", {"name": "Fix mode", "value_template": "{{ value_json.fix_mode }}", "icon": "mdi:crosshairs-gps"}),
            "satellites_visible": ("sensor", {"name": "Satellites visible", "value_template": "{{ value_json.satellites_visible }}", "state_class": "measurement", "icon": "mdi:satellite-variant"}),
            "satellites_used": ("sensor", {"name": "Satellites used", "value_template": "{{ value_json.satellites_used }}", "state_class": "measurement", "icon": "mdi:satellite-uplink"}),
            "latitude": ("sensor", {"name": "Latitude", "value_template": "{{ value_json.latitude | default(none) }}", "unit_of_measurement": "°", "icon": "mdi:latitude"}),
            "longitude": ("sensor", {"name": "Longitude", "value_template": "{{ value_json.longitude | default(none) }}", "unit_of_measurement": "°", "icon": "mdi:longitude"}),
            "altitude": ("sensor", {"name": "Altitude", "value_template": "{{ value_json.altitude | default(none) }}", "device_class": "distance", "unit_of_measurement": "m", "state_class": "measurement"}),
            "speed": ("sensor", {"name": "Speed", "value_template": "{{ value_json.speed | default(none) }}", "device_class": "speed", "unit_of_measurement": "m/s", "state_class": "measurement"}),
            "track": ("sensor", {"name": "Track", "value_template": "{{ value_json.track | default(none) }}", "unit_of_measurement": "°", "icon": "mdi:compass"}),
            "hdop": ("sensor", {"name": "HDOP", "value_template": "{{ value_json.hdop | default(none) }}", "state_class": "measurement", "icon": "mdi:map-marker-radius"}),
            "pdop": ("sensor", {"name": "PDOP", "value_template": "{{ value_json.pdop | default(none) }}", "state_class": "measurement", "icon": "mdi:crosshairs-question"}),
            "vdop": ("sensor", {"name": "VDOP", "value_template": "{{ value_json.vdop | default(none) }}", "state_class": "measurement", "icon": "mdi:arrow-up-down"}),
            "gdop": ("sensor", {"name": "GDOP", "value_template": "{{ value_json.gdop | default(none) }}", "state_class": "measurement", "icon": "mdi:target"}),
            "positioning_quality": ("sensor", {"name": "Positioning quality", "value_template": "{{ value_json.positioning_quality | default(none) }}", "device_class": "enum", "options": ["excellent", "good", "moderate", "poor"], "icon": "mdi:signal"}),
            "horizontal_error": ("sensor", {"name": "Horizontal error", "value_template": "{{ value_json.horizontal_error | default(none) }}", "device_class": "distance", "unit_of_measurement": "m", "state_class": "measurement"}),
            "last_update": ("sensor", {"name": "Last update", "value_template": "{{ value_json.last_update | default(none) }}", "device_class": "timestamp"}),
            "data_age": ("sensor", {"name": "Data age", "value_template": "{{ value_json.data_age | default(none) }}", "device_class": "duration", "unit_of_measurement": "s", "state_class": "measurement", "entity_category": "diagnostic"}),
            "reconnect_count": ("sensor", {"name": "GPSD reconnect count", "value_template": "{{ value_json.reconnect_count }}", "state_class": "total_increasing", "icon": "mdi:restart", "entity_category": "diagnostic"}),
            "receiver": ("sensor", {"name": "Receiver", "value_template": "{{ value_json.receiver_name | default(none) }}", "json_attributes_topic": self.state_topic, "json_attributes_template": "{{ value_json.receiver | default({}) | tojson }}", "icon": "mdi:developer-board", "entity_category": "diagnostic"}),
        }
        for object_id, (component, entity) in entities.items():
            config = common | entity | {"unique_id": f"{self.device_id}_{object_id}"}
            topic = f"{self.discovery_prefix}/{component}/{self.device_id}/{object_id}/config"
            client.publish(topic, json.dumps(config, separators=(",", ":")), qos=1, retain=True)
        if self.tracker_enabled:
            tracker_config = common | {
                "state_topic": self.tracker_topic,
                "json_attributes_topic": self.tracker_topic,
                "value_template": "{{ value_json.state }}",
                "source_type": "gps",
                "name": "Position",
                "unique_id": f"{self.device_id}_position",
            }
            topic = f"{self.discovery_prefix}/device_tracker/{self.device_id}/position/config"
            client.publish(topic, json.dumps(tracker_config, separators=(",", ":")), qos=1, retain=True)
        else:
            # Remove a retained tracker discovery config if the option was disabled.
            topic = f"{self.discovery_prefix}/device_tracker/{self.device_id}/position/config"
            client.publish(topic, "", qos=1, retain=True)
