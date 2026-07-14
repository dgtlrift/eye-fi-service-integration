"""Config flow for the Eye-Fi integration.

Collects the first card (mac + upload key), the storage destination (and
that destination's own config), and an optional geotagging backend. The
options flow lets the user add further cards afterward — eyefi_core takes
all of them as a single ``{mac: upload_key}`` dict, mirroring the shape
used by prior Eye-Fi servers.

This step only builds plain dicts/strings and hands them to eyefi_core via
``async_setup_entry`` — it never imports eyefi_core's protocol/geotag/
storage internals directly.
"""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_CARDS,
    CONF_DESTINATION,
    CONF_DESTINATION_CONFIG,
    CONF_DOWNLOAD_DIR,
    CONF_GEOTAG_BACKEND,
    CONF_GEOTAG_CONFIG,
    CONF_MAC,
    CONF_PORT,
    CONF_UPLOAD_KEY,
    DEFAULT_PORT,
    DESTINATION_APPLE_DROPFOLDER,
    DESTINATION_BACKBLAZE,
    DESTINATION_GOOGLE_PHOTOS,
    DESTINATION_LOCAL_NAS,
    DESTINATION_ONEDRIVE,
    DESTINATION_PCLOUD,
    DESTINATION_REMOTE_NAS,
    DESTINATION_SMUGMUG,
    DESTINATIONS,
    DOMAIN,
    GEOTAG_BACKEND_GOOGLE,
    GEOTAG_BACKEND_NONE,
    GEOTAG_BACKEND_WIGLE,
    GEOTAG_BACKENDS,
)

_MAC_RE = re.compile(r"^[0-9a-f]{12}$")
_UPLOAD_KEY_RE = re.compile(r"^[0-9a-f]{32}$")


def _normalize_mac(value: str) -> str | None:
    """Card utilities (e.g. eyefi-config -m) print the MAC colon-separated
    (``00:18:56:41:25:f5``), but the wire protocol's <macaddress> element —
    and eyefi_core's card lookup — uses the bare 12-hex-char form with no
    separators. Strip separators here so either form works.

    Done as a plain function called from the step handler, NOT as a
    voluptuous validator on the schema — ``voluptuous_serialize`` (which HA
    uses to turn the schema into a frontend form spec) can't serialize an
    arbitrary custom function and raises ValueError if one is used there.
    """
    normalized = re.sub(r"[:\-\s]", "", value).lower()
    return normalized if _MAC_RE.match(normalized) else None


def _normalize_upload_key(value: str) -> str | None:
    normalized = re.sub(r"[\-\s]", "", value).lower()
    return normalized if _UPLOAD_KEY_RE.match(normalized) else None


_CARD_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MAC): str,
        vol.Required(CONF_UPLOAD_KEY): str,
        vol.Required(CONF_DOWNLOAD_DIR): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_DESTINATION, default=DESTINATION_LOCAL_NAS): vol.In(DESTINATIONS),
        vol.Optional(CONF_GEOTAG_BACKEND, default=GEOTAG_BACKEND_NONE): vol.In(GEOTAG_BACKENDS),
    }
)

_DESTINATION_SCHEMAS: dict[str, vol.Schema] = {
    DESTINATION_LOCAL_NAS: vol.Schema({vol.Required("path"): str}),
    DESTINATION_APPLE_DROPFOLDER: vol.Schema({vol.Required("path"): str}),
    DESTINATION_REMOTE_NAS: vol.Schema(
        {
            vol.Required("protocol"): vol.In(["smb", "sftp"]),
            vol.Required("host"): str,
            vol.Required("remote_path"): str,
            vol.Required("username"): str,
            vol.Optional("password"): str,
            vol.Optional("port"): int,
        }
    ),
    DESTINATION_GOOGLE_PHOTOS: vol.Schema(
        {vol.Required("access_token"): str, vol.Optional("album_id"): str}
    ),
    DESTINATION_ONEDRIVE: vol.Schema(
        {vol.Required("access_token"): str, vol.Optional("remote_folder", default="/Eye-Fi"): str}
    ),
    DESTINATION_SMUGMUG: vol.Schema(
        {
            vol.Required("consumer_key"): str,
            vol.Required("consumer_secret"): str,
            vol.Required("access_token"): str,
            vol.Required("access_token_secret"): str,
            vol.Required("album_uri"): str,
        }
    ),
    DESTINATION_BACKBLAZE: vol.Schema(
        {
            vol.Required("key_id"): str,
            vol.Required("application_key"): str,
            vol.Required("bucket_id"): str,
        }
    ),
    DESTINATION_PCLOUD: vol.Schema(
        {vol.Required("access_token"): str, vol.Optional("remote_folder", default="/Eye-Fi"): str}
    ),
}

_GEOTAG_SCHEMAS: dict[str, vol.Schema] = {
    GEOTAG_BACKEND_GOOGLE: vol.Schema({vol.Required("api_key"): str}),
    GEOTAG_BACKEND_WIGLE: vol.Schema(
        {vol.Required("api_name"): str, vol.Required("api_token"): str}
    ),
}


class EyeFiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            mac = _normalize_mac(user_input[CONF_MAC])
            upload_key = _normalize_upload_key(user_input[CONF_UPLOAD_KEY])
            if mac is None:
                errors[CONF_MAC] = "invalid_mac"
            if upload_key is None:
                errors[CONF_UPLOAD_KEY] = "invalid_upload_key"

            if not errors:
                self._data = {
                    CONF_CARDS: [{CONF_MAC: mac, CONF_UPLOAD_KEY: upload_key}],
                    CONF_DOWNLOAD_DIR: user_input[CONF_DOWNLOAD_DIR],
                    CONF_PORT: user_input[CONF_PORT],
                    CONF_DESTINATION: user_input[CONF_DESTINATION],
                    CONF_GEOTAG_BACKEND: user_input[CONF_GEOTAG_BACKEND],
                }
                return await self.async_step_destination()

        return self.async_show_form(step_id="user", data_schema=_CARD_SCHEMA, errors=errors)

    async def async_step_destination(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        destination = self._data[CONF_DESTINATION]
        schema = _DESTINATION_SCHEMAS[destination]

        if user_input is not None:
            self._data[CONF_DESTINATION_CONFIG] = user_input
            return await self.async_step_geotag()

        return self.async_show_form(step_id="destination", data_schema=schema)

    async def async_step_geotag(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        backend = self._data[CONF_GEOTAG_BACKEND]
        if backend == GEOTAG_BACKEND_NONE:
            self._data[CONF_GEOTAG_CONFIG] = {}
            return self._create_entry()

        schema = _GEOTAG_SCHEMAS[backend]
        if user_input is not None:
            self._data[CONF_GEOTAG_CONFIG] = user_input
            return self._create_entry()

        return self.async_show_form(step_id="geotag", data_schema=schema)

    def _create_entry(self) -> FlowResult:
        title = f"Eye-Fi ({self._data[CONF_CARDS][0][CONF_MAC]})"
        return self.async_create_entry(title=title, data=self._data)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "EyeFiOptionsFlow":
        return EyeFiOptionsFlow(config_entry)


class EyeFiOptionsFlow(config_entries.OptionsFlow):
    """Add further cards to an existing Eye-Fi config entry."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            mac = _normalize_mac(user_input[CONF_MAC])
            upload_key = _normalize_upload_key(user_input[CONF_UPLOAD_KEY])
            if mac is None:
                errors[CONF_MAC] = "invalid_mac"
            if upload_key is None:
                errors[CONF_UPLOAD_KEY] = "invalid_upload_key"

            if not errors:
                cards = list(self._config_entry.data.get(CONF_CARDS, []))
                cards.append({CONF_MAC: mac, CONF_UPLOAD_KEY: upload_key})
                new_data = {**self._config_entry.data, CONF_CARDS: cards}
                self.hass.config_entries.async_update_entry(self._config_entry, data=new_data)
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_MAC): str, vol.Required(CONF_UPLOAD_KEY): str}
            ),
            errors=errors,
        )
