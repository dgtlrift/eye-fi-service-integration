"""Mozilla Location Service (Ichnaea) backend.

Mozilla shut down the public MLS instance (location.services.mozilla.com)
in 2024 — the historical URL is kept here only as a default for anyone
pointing this at a still-running self-hosted Ichnaea instance (Ichnaea
itself, https://ichnaea.readthedocs.io/, remains open source and
self-hostable). ``base_url`` is a constructor argument specifically so
this isn't hardcoded to a dead endpoint; the HA config flow's default
value carries the same caveat in its field description.
"""

from __future__ import annotations

from dataclasses import dataclass

import aiohttp

from wifi_geolocation_core.ichnaea_compatible import IchnaeaCompatibleBackend
from wifi_geolocation_core.models import AccessPoint, Coordinates

MOZILLA_MLS_URL = "https://location.services.mozilla.com/v1/geolocate"


@dataclass(frozen=True, slots=True)
class MozillaGeolocationBackend:
    session: aiohttp.ClientSession
    base_url: str = MOZILLA_MLS_URL
    api_key: str | None = None

    async def resolve(self, access_points: list[AccessPoint]) -> Coordinates | None:
        return await IchnaeaCompatibleBackend(
            url=self.base_url,
            session=self.session,
            api_key=self.api_key,
            service_name="Mozilla Location Service / Ichnaea",
        ).resolve(access_points)
