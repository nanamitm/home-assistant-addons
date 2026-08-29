"""Config flow for JK EPG."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import JkEpgApi
from .const import DEFAULT_URL, DOMAIN


class JkEpgConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure JK EPG."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            url = user_input["url"].rstrip("/")
            try:
                await JkEpgApi(async_get_clientsession(self.hass), url).health()
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id("jk_epg_addon")
                self._abort_if_unique_id_configured(updates={"url": url})
                return self.async_create_entry(title="JK EPG", data={"url": url})
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required("url", default=DEFAULT_URL): str}),
            errors=errors,
        )
