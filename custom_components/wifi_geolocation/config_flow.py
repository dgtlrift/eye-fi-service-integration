"""Config flow for the WiFi Geolocation integration.

Single-instance: whichever backend(s) get configured here serve any
number of consumer integrations (eyefi, potentially others later) via the
``wifi_geolocation.resolve`` service — nobody else needs to hold a
Google/WiGLE/Combain/HERE/Unwired Labs/Mozilla API key.

The first step uses one plain boolean toggle per backend (not a
multi-select widget) deliberately: this project already hit a real bug
where a schema validator HA's frontend couldn't serialize caused a 500 on
every "Add Integration" attempt (see custom_components/eyefi/config_flow.py's
docstring). Plain ``bool`` fields carry zero risk of repeating that, at
the cost of a slightly longer form.

Selected backends are then configured one at a time via a single reused
step_id (``backend_config``), whose schema/description changes each time
based on which backend is next in the queue -- avoids a fixed step method
per backend.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    BACKEND_BEACONDB,
    BACKEND_COMBAIN,
    BACKEND_GOOGLE,
    BACKEND_HERE,
    BACKEND_LABELS,
    BACKEND_MOZILLA,
    BACKEND_PRIORITY_ORDER,
    BACKEND_UNWIRED_LABS,
    BACKEND_WIGLE,
    CONF_BACKENDS,
    CONF_COMBAIN_API_KEY,
    CONF_ENABLE_PREFIX,
    CONF_GOOGLE_API_KEY,
    CONF_HERE_API_KEY,
    CONF_MOZILLA_API_KEY,
    CONF_MOZILLA_BASE_URL,
    CONF_UNWIRED_LABS_API_KEY,
    CONF_UNWIRED_LABS_BASE_URL,
    CONF_WIGLE_API_NAME,
    CONF_WIGLE_API_TOKEN,
    DOMAIN,
)
from wifi_geolocation_core.mozilla import MOZILLA_MLS_URL
from wifi_geolocation_core.unwired_labs import UNWIRED_LABS_DEFAULT_URL

_MAIN_SCHEMA = vol.Schema(
    {
        vol.Optional(f"{CONF_ENABLE_PREFIX}{BACKEND_GOOGLE}", default=True): bool,
        vol.Optional(f"{CONF_ENABLE_PREFIX}{BACKEND_BEACONDB}", default=False): bool,
        vol.Optional(f"{CONF_ENABLE_PREFIX}{BACKEND_MOZILLA}", default=False): bool,
        vol.Optional(f"{CONF_ENABLE_PREFIX}{BACKEND_COMBAIN}", default=False): bool,
        vol.Optional(f"{CONF_ENABLE_PREFIX}{BACKEND_HERE}", default=False): bool,
        vol.Optional(f"{CONF_ENABLE_PREFIX}{BACKEND_UNWIRED_LABS}", default=False): bool,
        vol.Optional(f"{CONF_ENABLE_PREFIX}{BACKEND_WIGLE}", default=False): bool,
    }
)

# Backends with no credentials to collect (BeaconDB) are simply absent here.
_CREDENTIAL_SCHEMAS: dict[str, vol.Schema] = {
    BACKEND_GOOGLE: vol.Schema({vol.Required(CONF_GOOGLE_API_KEY): str}),
    BACKEND_WIGLE: vol.Schema(
        {vol.Required(CONF_WIGLE_API_NAME): str, vol.Required(CONF_WIGLE_API_TOKEN): str}
    ),
    BACKEND_COMBAIN: vol.Schema({vol.Required(CONF_COMBAIN_API_KEY): str}),
    BACKEND_HERE: vol.Schema({vol.Required(CONF_HERE_API_KEY): str}),
    BACKEND_UNWIRED_LABS: vol.Schema(
        {
            vol.Required(CONF_UNWIRED_LABS_API_KEY): str,
            vol.Optional(CONF_UNWIRED_LABS_BASE_URL, default=UNWIRED_LABS_DEFAULT_URL): str,
        }
    ),
    BACKEND_MOZILLA: vol.Schema(
        {
            vol.Optional(CONF_MOZILLA_API_KEY, default=""): str,
            vol.Optional(CONF_MOZILLA_BASE_URL, default=MOZILLA_MLS_URL): str,
        }
    ),
}


class WifiGeolocationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._pending: list[str] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}
        if user_input is not None:
            selected = [
                backend
                for backend in BACKEND_PRIORITY_ORDER
                if user_input.get(f"{CONF_ENABLE_PREFIX}{backend}")
            ]
            if not selected:
                errors["base"] = "no_backend_selected"
            else:
                self._data[CONF_BACKENDS] = selected
                self._pending = [b for b in selected if b in _CREDENTIAL_SCHEMAS]
                return await self._async_step_next_backend()

        return self.async_show_form(step_id="user", data_schema=_MAIN_SCHEMA, errors=errors)

    async def _async_step_next_backend(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None and self._pending:
            backend = self._pending.pop(0)
            self._data[backend] = user_input

        if not self._pending:
            return self.async_create_entry(title="WiFi Geolocation", data=self._data)

        next_backend = self._pending[0]
        return self.async_show_form(
            step_id="backend_config",
            data_schema=_CREDENTIAL_SCHEMAS[next_backend],
            description_placeholders={"backend": BACKEND_LABELS[next_backend]},
        )

    async def async_step_backend_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._async_step_next_backend(user_input)
