"""Base entity for JK EPG."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class JkEpgEntity(CoordinatorEntity):
    """Base coordinated entity."""

    _attr_has_entity_name = True

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "addon")},
            name="JK EPG",
            manufacturer="nanamitm",
            model="Home Assistant Add-on",
        )
