"""Combain Positioning API — Ichnaea/Google-shaped request+response, API
key as a query parameter."""

from __future__ import annotations

from dataclasses import dataclass

import aiohttp

from wifi_geolocation_core.ichnaea_compatible import IchnaeaCompatibleBackend
from wifi_geolocation_core.models import AccessPoint, Coordinates

COMBAIN_URL = "https://apiv2.combain.com"


@dataclass(frozen=True, slots=True)
class CombainGeolocationBackend:
    api_key: str
    session: aiohttp.ClientSession

    async def resolve(self, access_points: list[AccessPoint]) -> Coordinates | None:
        return await IchnaeaCompatibleBackend(
            url=COMBAIN_URL,
            session=self.session,
            api_key=self.api_key,
            service_name="Combain Positioning API",
        ).resolve(access_points)
