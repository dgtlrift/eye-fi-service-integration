"""Thin HA adapter around eyefi_core.

This module's only jobs: turn config-entry data into the plain dicts
eyefi_core's public API expects, start/stop eyefi_core embedded in HA's
event loop, and translate eyefi_core's pub/sub events into
``hass.bus`` events. No protocol, geotag, or storage logic lives here —
that's all in eyefi_core.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from eyefi_core import geotag as geotag_module
from eyefi_core.events import Event, EventType
from eyefi_core.soap_server import EyeFiSoapServer
from eyefi_core.storage import SpoolingStorageBackend, create_backend

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
    DESTINATION_LOCAL_NAS,
    DOMAIN,
    EVENT_IMAGE_GEOTAGGED,
    EVENT_IMAGE_RECEIVED,
    EVENT_IMAGE_STORED,
    GEOTAG_BACKEND_GOOGLE,
    GEOTAG_BACKEND_NONE,
    GEOTAG_BACKEND_WIGLE,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["camera"]

_SPOOL_RETRY_INTERVAL = timedelta(minutes=5)

_HA_EVENT_MAP = {
    EventType.IMAGE_RECEIVED: EVENT_IMAGE_RECEIVED,
    EventType.IMAGE_GEOTAGGED: EVENT_IMAGE_GEOTAGGED,
    EventType.IMAGE_STORED: EVENT_IMAGE_STORED,
}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = entry.data
    cards = {card[CONF_MAC]: card[CONF_UPLOAD_KEY] for card in data[CONF_CARDS]}
    download_dir = Path(data[CONF_DOWNLOAD_DIR])

    session = aiohttp.ClientSession()
    geotag_backend = _build_geotag_backend(data, session)

    destination = data[CONF_DESTINATION]
    destination_config = dict(data[CONF_DESTINATION_CONFIG])
    if destination == DESTINATION_LOCAL_NAS:
        destination_config.setdefault("path", str(download_dir / "photos"))
    storage_backend = SpoolingStorageBackend(
        create_backend(destination, destination_config),
        spool_dir=download_dir / ".spool",
    )

    server = EyeFiSoapServer(
        cards=cards,
        download_dir=download_dir,
        storage_backend=storage_backend,
        geotag_backend=geotag_backend,
        port=data[CONF_PORT],
    )

    def _bridge_event(event: Event) -> None:
        hass.bus.async_fire(_HA_EVENT_MAP[event.type], event.data)

    for event_type in _HA_EVENT_MAP:
        server.event_bus.subscribe(event_type, _bridge_event)

    await server.start()

    async def _retry_spool(_now) -> None:
        await storage_backend.retry_spool()

    unsub_retry = async_track_time_interval(hass, _retry_spool, _SPOOL_RETRY_INTERVAL)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "server": server,
        "session": session,
        "unsub_retry": unsub_retry,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        stored = hass.data[DOMAIN].pop(entry.entry_id)
        stored["unsub_retry"]()
        await stored["server"].stop()
        await stored["session"].close()
    return unload_ok


def _build_geotag_backend(data: dict, session: aiohttp.ClientSession):
    backend_name = data.get(CONF_GEOTAG_BACKEND, GEOTAG_BACKEND_NONE)
    config = data.get(CONF_GEOTAG_CONFIG, {})

    if backend_name == GEOTAG_BACKEND_GOOGLE:
        return geotag_module.GoogleGeolocationBackend(api_key=config["api_key"], session=session)
    if backend_name == GEOTAG_BACKEND_WIGLE:
        return geotag_module.WigleGeolocationBackend(
            api_name=config["api_name"], api_token=config["api_token"], session=session
        )
    return None
