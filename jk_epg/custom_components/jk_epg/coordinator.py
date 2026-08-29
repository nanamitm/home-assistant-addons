"""Coordinator for JK EPG."""

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import JkEpgApi
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class JkEpgCoordinator(DataUpdateCoordinator[dict]):
    """Poll the current broadcast-day schedule."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: JkEpgApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(minutes=1),
        )
        self.api = api

    async def _async_update_data(self) -> dict:
        try:
            return await self.api.schedule()
        except Exception as error:
            raise UpdateFailed(f"Unable to read JK EPG: {error}") from error
