"""Read-only EPG calendar for Home Assistant."""

from datetime import timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .entity import JkEpgEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([JkEpgCalendar(hass.data[DOMAIN][entry.entry_id])])


class JkEpgCalendar(JkEpgEntity, CalendarEntity):
    """Calendar containing programs from every channel."""

    _attr_name = "番組表"
    _attr_unique_id = "jk_epg_calendar"
    _attr_icon = "mdi:calendar-blank-multiple"
    _attr_initial_color = "#22d3ee"

    @staticmethod
    def _events(data: dict) -> list[CalendarEvent]:
        return sorted(
            (
                CalendarEvent(
                    start=dt_util.parse_datetime(program["startAt"]),
                    end=dt_util.parse_datetime(program["endAt"]),
                    summary=program["title"],
                    description=program.get("genreName") or program.get("source"),
                    location=channel["name"],
                    uid=f"{channel['video']}:{program['startAt']}",
                )
                for channel in data["channels"]
                for program in channel["programs"]
            ),
            key=lambda event: event.start,
        )

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        return next((event for event in self._events(self.coordinator.data) if event.end > now), None)

    async def async_get_events(self, hass, start_date, end_date) -> list[CalendarEvent]:
        events = {}
        day = (start_date - timedelta(days=1)).date()
        while day <= end_date.date():
            data = await self.coordinator.api.schedule(day)
            for event in self._events(data):
                if event.end > start_date and event.start < end_date:
                    events[event.uid] = event
            day += timedelta(days=1)
        return sorted(events.values(), key=lambda event: event.start)
