"""Current-program sensors for JK EPG."""

from datetime import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .entity import JkEpgEntity


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(JkEpgProgramSensor(coordinator, channel["video"]) for channel in coordinator.data["channels"])


class JkEpgProgramSensor(JkEpgEntity, SensorEntity):
    """Current and next program for one channel."""

    def __init__(self, coordinator, video: str) -> None:
        super().__init__(coordinator)
        self._video = video
        channel = self._channel
        self._attr_unique_id = f"jk_epg_{video}"
        self._attr_name = channel["name"]
        self._attr_icon = "mdi:television-guide"

    @property
    def _channel(self) -> dict:
        return next(channel for channel in self.coordinator.data["channels"] if channel["video"] == self._video)

    def _current_next(self):
        now = datetime.now().astimezone()
        programs = sorted(self._channel["programs"], key=lambda item: item["startAt"])
        current = next((item for item in programs if _parse(item["startAt"]) <= now < _parse(item["endAt"])), None)
        upcoming = next((item for item in programs if _parse(item["startAt"]) > now), None)
        return current, upcoming

    @property
    def native_value(self):
        current, _ = self._current_next()
        return current["title"] if current else None

    @property
    def extra_state_attributes(self):
        current, upcoming = self._current_next()
        return {
            "channel": self._channel["name"],
            "video": self._video,
            "start_at": current["startAt"] if current else None,
            "end_at": current["endAt"] if current else None,
            "genre": current.get("genreName") if current else None,
            "next_program": upcoming["title"] if upcoming else None,
            "next_start_at": upcoming["startAt"] if upcoming else None,
        }
