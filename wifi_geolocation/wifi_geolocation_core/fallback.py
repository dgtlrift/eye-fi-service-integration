"""Try multiple backends in priority order.

Lets a consumer configure e.g. Google as primary with WiGLE as a free
fallback (or the reverse), without the caller needing to know which one
actually answered a given request.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from wifi_geolocation_core.models import AccessPoint, Coordinates, GeolocationBackend

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FallbackGeolocationBackend:
    backends: tuple[GeolocationBackend, ...]

    async def resolve(self, access_points: list[AccessPoint]) -> Coordinates | None:
        for backend in self.backends:
            try:
                coordinates = await backend.resolve(access_points)
            except Exception:
                _LOGGER.exception("%s raised while resolving", type(backend).__name__)
                continue
            if coordinates is not None:
                return coordinates
        return None
