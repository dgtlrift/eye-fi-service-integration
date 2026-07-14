"""Thin HA adapter around eyefi_core.

This module's only jobs: turn config-entry data into the plain dicts
eyefi_core's public API expects, start/stop eyefi_core embedded in HA's
event loop, and translate eyefi_core's pub/sub events into
``hass.bus`` events. No protocol, geotag, or storage logic lives here —
that's all in eyefi_core.

Geotagging never holds a geolocation API key itself: if the sibling
``wifi_geolocation`` integration is loaded, ``_ServiceBackedGeolocationBackend``
below calls its ``resolve`` service; if not, geotagging is silently
skipped (eyefi_core already treats "backend couldn't resolve" as a normal,
non-fatal outcome).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from eyefi_core.events import Event, EventType
from eyefi_core.geotag import AccessPoint, Coordinates
from eyefi_core.soap_server import EyeFiSoapServer
from eyefi_core.storage import SpoolingStorageBackend, create_backend

from .const import (
    CONF_CARDS,
    CONF_DESTINATION,
    CONF_DESTINATION_CONFIG,
    CONF_DOWNLOAD_DIR,
    CONF_MAC,
    CONF_PORT,
    CONF_UPLOAD_KEY,
    DESTINATION_LOCAL_NAS,
    DOMAIN,
    EVENT_IMAGE_GEOTAGGED,
    EVENT_IMAGE_RECEIVED,
    EVENT_IMAGE_STORED,
    WIFI_GEOLOCATION_DOMAIN,
    WIFI_GEOLOCATION_SERVICE_RESOLVE,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["camera"]

_SPOOL_RETRY_INTERVAL = timedelta(minutes=5)

_HA_EVENT_MAP = {
    EventType.IMAGE_RECEIVED: EVENT_IMAGE_RECEIVED,
    EventType.IMAGE_GEOTAGGED: EVENT_IMAGE_GEOTAGGED,
    EventType.IMAGE_STORED: EVENT_IMAGE_STORED,
}


@dataclass(frozen=True, slots=True)
class _ServiceBackedGeolocationBackend:
    """Satisfies eyefi_core.geotag.GeolocationBackend by delegating to the
    wifi_geolocation integration's service, if it's loaded. No import of
    wifi_geolocation_core needed here -- only the HA service-call JSON
    contract is shared between the two integrations."""

    hass: HomeAssistant

    async def resolve(self, access_points: list[AccessPoint]) -> Coordinates | None:
        if WIFI_GEOLOCATION_DOMAIN not in self.hass.config.components:
            return None

        response = await self.hass.services.async_call(
            WIFI_GEOLOCATION_DOMAIN,
            WIFI_GEOLOCATION_SERVICE_RESOLVE,
            {
                "access_points": [
                    {"bssid": ap.bssid, "signal_strength_dbm": ap.signal_strength_dbm}
                    for ap in access_points
                ]
            },
            blocking=True,
            return_response=True,
        )
        if not response or not response.get("resolved"):
            return None
        return Coordinates(
            latitude=response["latitude"],
            longitude=response["longitude"],
            accuracy_m=response.get("accuracy_m"),
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = entry.data
    cards = {card[CONF_MAC]: card[CONF_UPLOAD_KEY] for card in data[CONF_CARDS]}
    download_dir = Path(data[CONF_DOWNLOAD_DIR])

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
        geotag_backend=_ServiceBackedGeolocationBackend(hass=hass),
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
    return unload_ok
