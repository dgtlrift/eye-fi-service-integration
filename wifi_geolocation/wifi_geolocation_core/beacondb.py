"""BeaconDB — free, open, community-run Ichnaea-compatible geolocation
service (spiritually a successor to Mozilla's discontinued MLS). No API
key required."""

from __future__ import annotations

from dataclasses import dataclass

import aiohttp

from wifi_geolocation_core.ichnaea_compatible import IchnaeaCompatibleBackend
from wifi_geolocation_core.models import AccessPoint, Coordinates

BEACONDB_URL = "https://api.beacondb.net/v1/geolocate"


@dataclass(frozen=True, slots=True)
class BeaconDbGeolocationBackend:
    session: aiohttp.ClientSession

    async def resolve(self, access_points: list[AccessPoint]) -> Coordinates | None:
        return await IchnaeaCompatibleBackend(
            url=BEACONDB_URL,
            session=self.session,
            api_key=None,
            service_name="BeaconDB",
        ).resolve(access_points)
