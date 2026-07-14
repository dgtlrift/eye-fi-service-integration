"""HERE Technologies Positioning API backend.

Different request shape than the Ichnaea family: a "wlan" array of
{"mac", "rss"} rather than "wifiAccessPoints" of {"macAddress",
"signalStrength"}. Verify field casing/response shape against HERE's
current API docs before relying on this in production -- implemented from
documented parameter names, not tested against a live HERE account.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import aiohttp

from wifi_geolocation_core.models import AccessPoint, Coordinates

_LOGGER = logging.getLogger(__name__)

HERE_POSITIONING_URL = "https://pos.ls.hereapi.com/positioning/v1/locate"


@dataclass(frozen=True, slots=True)
class HereGeolocationBackend:
    api_key: str
    session: aiohttp.ClientSession

    async def resolve(self, access_points: list[AccessPoint]) -> Coordinates | None:
        payload = {
            "wlan": [
                {"mac": ap.bssid.replace(":", "").upper(), "rss": ap.signal_strength_dbm}
                for ap in access_points
            ]
        }
        try:
            async with self.session.post(
                HERE_POSITIONING_URL,
                params={"apiKey": self.api_key},
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning("HERE Positioning API returned HTTP %s", resp.status)
                    return None
                body = await resp.json()
        except aiohttp.ClientError:
            _LOGGER.exception("HERE Positioning API request failed")
            return None

        location = body.get("location")
        if not location:
            return None
        return Coordinates(
            latitude=location["lat"],
            longitude=location["lng"],
            accuracy_m=location.get("accuracy"),
        )
