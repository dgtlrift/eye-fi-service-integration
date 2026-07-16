"""Config flow for the WiFi Geolocation integration.

Single-instance: whichever backend(s) get configured here serve any
number of consumer integrations (eyefi, potentially others later) via the
``wifi_geolocation.resolve`` service — nobody else needs to hold a
Google/WiGLE/Combain/HERE/Unwired Labs/Mozilla API key.

Backend selection *and* priority order both come from one
``SelectSelector`` field (``multiple=True``): the order the user picks
them in becomes the order they're tried in at runtime (see
``__init__.py``'s ``_build_backend``) — no separate "priority" field,
since the selection order already carries that. This is a first-class HA
Selector class, not a bare custom function, so it doesn't repeat the real
bug this project already hit (a schema validator ``voluptuous_serialize``
couldn't handle, causing a 500 on every "Add Integration" attempt) — see
``custom_components/eyefi/config_flow.py``'s docstring for that story.

Selected backends are then configured one at a time via a single reused
step_id (``backend_config``), whose schema/description changes each time
based on which backend is next in the queue -- avoids a fixed step method
per backend. The options flow (``Configure`` on an existing entry) reruns
the same selection+reorder step and the same per-backend credential step,
but skips re-prompting for credentials of backends that stay enabled and
already have them stored.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
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


def _backend_select_schema(*, default: list[str]) -> vol.Schema:
    options = [
        selector.SelectOptionDict(value=backend, label=BACKEND_LABELS[backend])
        for backend in BACKEND_PRIORITY_ORDER
    ]
    return vol.Schema(
        {
            vol.Optional(CONF_BACKENDS, default=default): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            )
        }
    )


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
            selected = user_input[CONF_BACKENDS]
            if not selected:
                errors["base"] = "no_backend_selected"
            else:
                self._data[CONF_BACKENDS] = selected
                self._pending = [b for b in selected if b in _CREDENTIAL_SCHEMAS]
                return await self._async_step_next_backend()

        return self.async_show_form(
            step_id="user",
            data_schema=_backend_select_schema(default=[BACKEND_GOOGLE]),
            errors=errors,
        )

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

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "WifiGeolocationOptionsFlow":
        return WifiGeolocationOptionsFlow(config_entry)


class WifiGeolocationOptionsFlow(config_entries.OptionsFlow):
    """Change which backends are enabled and/or reorder their priority.

    Reruns the same backend-selection + per-backend credential steps as
    initial setup, but carries over credentials for any backend that's
    still enabled and already configured -- only newly-added backends (or
    ones with no credentials to begin with) get prompted again.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._data: dict[str, Any] = dict(config_entry.data)
        self._pending: list[str] = []

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            selected = user_input[CONF_BACKENDS]
            if not selected:
                errors["base"] = "no_backend_selected"
            else:
                self._data[CONF_BACKENDS] = selected
                for backend in list(_CREDENTIAL_SCHEMAS):
                    if backend not in selected:
                        self._data.pop(backend, None)
                self._pending = [
                    b for b in selected if b in _CREDENTIAL_SCHEMAS and b not in self._data
                ]
                return await self._async_step_next_backend()

        return self.async_show_form(
            step_id="init",
            data_schema=_backend_select_schema(
                default=self._config_entry.data.get(CONF_BACKENDS, [BACKEND_GOOGLE])
            ),
            errors=errors,
        )

    async def _async_step_next_backend(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None and self._pending:
            backend = self._pending.pop(0)
            self._data[backend] = user_input

        if not self._pending:
            self.hass.config_entries.async_update_entry(self._config_entry, data=self._data)
            return self.async_create_entry(title="", data={})

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
