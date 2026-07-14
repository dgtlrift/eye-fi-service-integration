"""Shared implementation for geolocation APIs that speak the
Ichnaea/Google Geolocation API request+response shape::

    POST {url}?key={api_key}          (api_key omitted if not required)
    {"considerIp": false, "wifiAccessPoints": [{"macAddress": "..", "signalStrength": -70}]}

    -> {"location": {"lat": .., "lng": ..}, "accuracy": ..}

Google, Combain, BeaconDB, and Mozilla Location Service (Ichnaea) all use
this same contract, so each of those modules is a thin named wrapper
around this one implementation rather than duplicating it four times.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import aiohttp

from wifi_geolocation_core.models import AccessPoint, Coordinates, format_bssid

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IchnaeaCompatibleBackend:
    url: str
    session: aiohttp.ClientSession
    api_key: str | None = None
    api_key_param: str = "key"
    service_name: str = "Ichnaea-compatible service"

    async def resolve(self, access_points: list[AccessPoint]) -> Coordinates | None:
        payload = {
            "considerIp": False,
            "wifiAccessPoints": [
                {
                    "macAddress": format_bssid(ap.bssid),
                    "signalStrength": ap.signal_strength_dbm,
                }
                for ap in access_points
            ],
        }
        params = {self.api_key_param: self.api_key} if self.api_key else {}

        try:
            async with self.session.post(
                self.url,
                params=params,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning("%s returned HTTP %s", self.service_name, resp.status)
                    return None
                body = await resp.json()
        except aiohttp.ClientError:
            _LOGGER.exception("%s request failed", self.service_name)
            return None

        location = body.get("location")
        if not location:
            return None
        return Coordinates(
            latitude=location["lat"],
            longitude=location["lng"],
            accuracy_m=body.get("accuracy"),
        )
