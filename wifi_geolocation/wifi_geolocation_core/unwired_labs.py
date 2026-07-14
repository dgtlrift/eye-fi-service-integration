"""Unwired Labs LocationAPI backend.

Different shape from the Ichnaea family: auth token goes in the JSON body
(not a query param), the AP list key is "wifi" with colon-separated
"bssid"/"signal" fields, and the response is a flat {"lat", "lon",
"accuracy"} rather than a nested "location" object. Region-specific
subdomains exist (us1/us2/eu1/...); ``base_url`` defaults to us1.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import aiohttp

from wifi_geolocation_core.models import AccessPoint, Coordinates, format_bssid

_LOGGER = logging.getLogger(__name__)

UNWIRED_LABS_DEFAULT_URL = "https://us1.unwiredlabs.com/v2/process.php"


@dataclass(frozen=True, slots=True)
class UnwiredLabsGeolocationBackend:
    api_key: str
    session: aiohttp.ClientSession
    base_url: str = UNWIRED_LABS_DEFAULT_URL

    async def resolve(self, access_points: list[AccessPoint]) -> Coordinates | None:
        payload = {
            "token": self.api_key,
            "wifi": [
                {"bssid": format_bssid(ap.bssid), "signal": ap.signal_strength_dbm}
                for ap in access_points
            ],
        }
        try:
            async with self.session.post(
                self.base_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning("Unwired Labs LocationAPI returned HTTP %s", resp.status)
                    return None
                body = await resp.json()
        except aiohttp.ClientError:
            _LOGGER.exception("Unwired Labs LocationAPI request failed")
            return None

        if body.get("status") != "ok" or "lat" not in body or "lon" not in body:
            return None
        return Coordinates(
            latitude=body["lat"],
            longitude=body["lon"],
            accuracy_m=body.get("accuracy"),
        )
