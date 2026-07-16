"""WiFi Geolocation: a thin HA adapter around wifi_geolocation_core.

Registers a single ``wifi_geolocation.resolve`` service so any other
integration (eyefi, or anything else in the future) can resolve WiFi AP
sightings to a lat/long without holding any of these backends' API keys
itself — only this integration's config entry does.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.helpers import config_validation as cv

from wifi_geolocation_core.beacondb import BeaconDbGeolocationBackend
from wifi_geolocation_core.combain import CombainGeolocationBackend
from wifi_geolocation_core.fallback import FallbackGeolocationBackend
from wifi_geolocation_core.google import GoogleGeolocationBackend
from wifi_geolocation_core.here import HereGeolocationBackend
from wifi_geolocation_core.models import AccessPoint, GeolocationBackend
from wifi_geolocation_core.mozilla import MozillaGeolocationBackend
from wifi_geolocation_core.unwired_labs import UnwiredLabsGeolocationBackend
from wifi_geolocation_core.wifidb import WifiDbGeolocationBackend
from wifi_geolocation_core.wigle import WigleGeolocationBackend

from .const import (
    BACKEND_BEACONDB,
    BACKEND_COMBAIN,
    BACKEND_GOOGLE,
    BACKEND_HERE,
    BACKEND_MOZILLA,
    BACKEND_UNWIRED_LABS,
    BACKEND_WIFIDB,
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
    SERVICE_RESOLVE,
)

_LOGGER = logging.getLogger(__name__)

_ACCESS_POINT_SCHEMA = vol.Schema(
    {
        vol.Required("bssid"): str,
        vol.Required("signal_strength_dbm"): vol.Coerce(int),
    }
)

_RESOLVE_SERVICE_SCHEMA = vol.Schema(
    {vol.Required("access_points"): vol.All(cv.ensure_list, [_ACCESS_POINT_SCHEMA])}
)


def _build_one_backend(
    backend: str, data: dict[str, Any], session: aiohttp.ClientSession
) -> GeolocationBackend:
    if backend == BACKEND_GOOGLE:
        return GoogleGeolocationBackend(api_key=data[CONF_GOOGLE_API_KEY], session=session)
    if backend == BACKEND_WIGLE:
        return WigleGeolocationBackend(
            api_name=data[CONF_WIGLE_API_NAME],
            api_token=data[CONF_WIGLE_API_TOKEN],
            session=session,
        )
    if backend == BACKEND_COMBAIN:
        return CombainGeolocationBackend(api_key=data[CONF_COMBAIN_API_KEY], session=session)
    if backend == BACKEND_HERE:
        return HereGeolocationBackend(api_key=data[CONF_HERE_API_KEY], session=session)
    if backend == BACKEND_UNWIRED_LABS:
        return UnwiredLabsGeolocationBackend(
            api_key=data[CONF_UNWIRED_LABS_API_KEY],
            base_url=data[CONF_UNWIRED_LABS_BASE_URL],
            session=session,
        )
    if backend == BACKEND_MOZILLA:
        return MozillaGeolocationBackend(
            session=session,
            base_url=data[CONF_MOZILLA_BASE_URL],
            api_key=data[CONF_MOZILLA_API_KEY] or None,
        )
    if backend == BACKEND_BEACONDB:
        return BeaconDbGeolocationBackend(session=session)
    if backend == BACKEND_WIFIDB:
        return WifiDbGeolocationBackend(session=session)
    raise ValueError(f"Unknown backend {backend!r}")


def _build_backend(data: dict[str, Any], session: aiohttp.ClientSession) -> GeolocationBackend:
    # data[CONF_BACKENDS] is already in the user's chosen priority order --
    # see config_flow.py's _backend_select_schema.
    backends = tuple(_build_one_backend(b, data.get(b, {}), session) for b in data[CONF_BACKENDS])
    if len(backends) == 1:
        return backends[0]
    return FallbackGeolocationBackend(backends=backends)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = aiohttp.ClientSession()
    backend = _build_backend(entry.data, session)

    async def _handle_resolve(call: ServiceCall) -> ServiceResponse:
        access_points = [
            AccessPoint(bssid=ap["bssid"], signal_strength_dbm=ap["signal_strength_dbm"])
            for ap in call.data["access_points"]
        ]
        try:
            coordinates = await backend.resolve(access_points)
        except Exception:
            _LOGGER.exception("Resolving %d access point(s) failed", len(access_points))
            return {"resolved": False, "latitude": None, "longitude": None, "accuracy_m": None}

        if coordinates is None:
            _LOGGER.info("No backend resolved a location for %d access point(s)", len(access_points))
            return {"resolved": False, "latitude": None, "longitude": None, "accuracy_m": None}

        _LOGGER.info(
            "Resolved %d access point(s) to %s, %s",
            len(access_points),
            coordinates.latitude,
            coordinates.longitude,
        )
        return {
            "resolved": True,
            "latitude": coordinates.latitude,
            "longitude": coordinates.longitude,
            "accuracy_m": coordinates.accuracy_m,
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESOLVE,
        _handle_resolve,
        schema=_RESOLVE_SERVICE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"session": session}
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options changes (e.g. reordering/adding backends via Configure)
    rebuild the backend chain by reloading the whole entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.services.async_remove(DOMAIN, SERVICE_RESOLVE)
    stored = hass.data[DOMAIN].pop(entry.entry_id)
    await stored["session"].close()
    return True
