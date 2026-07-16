"""WiGLE community-database backend."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import aiohttp

from wifi_geolocation_core.cooldown import RateLimitCooldown
from wifi_geolocation_core.models import AccessPoint, Coordinates, format_bssid

_LOGGER = logging.getLogger(__name__)

WIGLE_SEARCH_URL = "https://api.wigle.net/api/v2/network/search"


@dataclass(frozen=True, slots=True)
class WigleGeolocationBackend:
    """Free-tier fallback using WiGLE's community-sourced BSSID database.

    WiGLE has no built-in multilateration endpoint, so this looks up each
    BSSID's last-known location individually and returns the
    signal-strength-weighted centroid of whichever BSSIDs it recognizes.

    WiGLE's free tier has a daily query quota; a 429 response means every
    other lookup this call (and any call for the rest of the day) will
    also fail, so one 429 pauses all WiGLE lookups for 24h instead of
    burning through the remaining access points -- and every subsequent
    call -- against a quota that's already exhausted.
    """

    api_name: str
    api_token: str
    session: aiohttp.ClientSession
    _cooldown: RateLimitCooldown = field(default_factory=RateLimitCooldown, compare=False)

    async def resolve(self, access_points: list[AccessPoint]) -> Coordinates | None:
        if self._cooldown.active():
            _LOGGER.debug(
                "Skipping WiGLE lookup: rate-limited for another %.0f minute(s)",
                self._cooldown.remaining_seconds() / 60,
            )
            return None

        auth = aiohttp.BasicAuth(self.api_name, self.api_token)
        weighted_points: list[tuple[float, float, float]] = []

        for ap in access_points:
            try:
                async with self.session.get(
                    WIGLE_SEARCH_URL,
                    params={"netid": format_bssid(ap.bssid)},
                    auth=auth,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 429:
                        self._cooldown.trigger()
                        _LOGGER.warning(
                            "WiGLE rate-limited (HTTP 429): %s -- pausing WiGLE "
                            "lookups for %.0f hour(s)",
                            (await resp.text())[:500],
                            self._cooldown.duration_seconds / 3600,
                        )
                        break
                    if resp.status != 200:
                        _LOGGER.warning(
                            "WiGLE lookup for %s returned HTTP %d: %s",
                            ap.bssid,
                            resp.status,
                            (await resp.text())[:500],
                        )
                        continue
                    body = await resp.json()
            except aiohttp.ClientError:
                _LOGGER.exception("WiGLE lookup failed for %s", ap.bssid)
                continue

            results = body.get("results") or []
            if not results:
                _LOGGER.debug("WiGLE has no record of %s", ap.bssid)
                continue
            best = results[0]
            if "trilat" not in best or "trilong" not in best:
                continue

            # Stronger (less negative) signal -> higher weight.
            weight = 10 ** (ap.signal_strength_dbm / 10)
            weighted_points.append((best["trilat"], best["trilong"], weight))

        if not weighted_points:
            return None

        total_weight = sum(w for _, _, w in weighted_points)
        lat = sum(lat * w for lat, _, w in weighted_points) / total_weight
        lon = sum(lon * w for _, lon, w in weighted_points) / total_weight
        return Coordinates(latitude=lat, longitude=lon)
