"""Google Geolocation API backend."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import aiohttp

from wifi_geolocation_core.models import AccessPoint, Coordinates, format_bssid

_LOGGER = logging.getLogger(__name__)

GOOGLE_GEOLOCATION_URL = "https://www.googleapis.com/geolocation/v1/geolocate"


@dataclass(frozen=True, slots=True)
class GoogleGeolocationBackend:
    """POSTs to Google's Geolocation API. Paid past the free tier — this is
    what pre-existing Eye-Fi server forks used (via the now-deprecated
    ``browserlocation`` endpoint; this targets its documented successor)."""

    api_key: str
    session: aiohttp.ClientSession

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
        try:
            async with self.session.post(
                GOOGLE_GEOLOCATION_URL,
                params={"key": self.api_key},
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning("Google Geolocation API returned %s", resp.status)
                    return None
                body = await resp.json()
        except aiohttp.ClientError:
            _LOGGER.exception("Google Geolocation API request failed")
            return None

        location = body.get("location")
        if not location:
            return None
        return Coordinates(
            latitude=location["lat"],
            longitude=location["lng"],
            accuracy_m=body.get("accuracy"),
        )
