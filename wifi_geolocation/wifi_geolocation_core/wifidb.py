"""WifiDB community WiFi geolocation database backend."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import aiohttp

from wifi_geolocation_core.cooldown import RateLimitCooldown
from wifi_geolocation_core.models import AccessPoint, Coordinates, format_bssid

_LOGGER = logging.getLogger(__name__)

WIFIDB_SEARCH_URL = "https://wifidb.net/api/search.php"

# search.php never returns an accuracy figure at all, unlike every other
# backend here. 100m is a conservative (worst-case) estimate for typical
# WiFi AP propagation range -- consumer 2.4GHz APs typically reach
# roughly 30m indoors and up to ~90-100m outdoors in unobstructed line of
# sight; using the outdoor figure as a pessimistic upper bound means
# callers never overstate confidence in a location WifiDB itself gives
# no confidence data for.
DEFAULT_ACCURACY_M = 100.0


@dataclass(frozen=True, slots=True)
class WifiDbGeolocationBackend:
    """Free, keyless lookup against WifiDB's community WiFi geolocation
    database (https://wifidb.net, https://github.com/acalcutt/WifiDB).

    Uses ``/api/search.php``, not the documented-but-effectively-dead
    ``/api/locate.php`` (which queries a table WifiDB's own live scanner
    no longer populates, confirmed by reading its source). No built-in
    multilateration endpoint exists here -- like WiGLE, this looks up
    each BSSID individually and returns the signal-strength-weighted
    centroid of whichever ones it recognizes.

    A single-maintainer "Beta" project with no documented SLA or rate
    limit -- reusing RateLimitCooldown (see wigle.py) defensively in case
    it ever starts rate limiting, even though none is documented today.
    """

    session: aiohttp.ClientSession
    _cooldown: RateLimitCooldown = field(default_factory=RateLimitCooldown, compare=False)

    async def resolve(self, access_points: list[AccessPoint]) -> Coordinates | None:
        if self._cooldown.active():
            _LOGGER.debug(
                "Skipping WifiDB lookup: rate-limited for another %.0f minute(s)",
                self._cooldown.remaining_seconds() / 60,
            )
            return None

        weighted_points: list[tuple[float, float, float]] = []

        for ap in access_points:
            try:
                async with self.session.get(
                    WIFIDB_SEARCH_URL,
                    params={"mac": format_bssid(ap.bssid)},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 429:
                        self._cooldown.trigger()
                        _LOGGER.warning(
                            "WifiDB rate-limited (HTTP 429): %s -- pausing WifiDB "
                            "lookups for %.0f hour(s)",
                            (await resp.text())[:500],
                            self._cooldown.duration_seconds / 3600,
                        )
                        break
                    if resp.status != 200:
                        _LOGGER.warning(
                            "WifiDB lookup for %s returned HTTP %d: %s",
                            ap.bssid,
                            resp.status,
                            (await resp.text())[:500],
                        )
                        continue
                    # WifiDB's search.php sends Content-Type: text/html for
                    # what is genuinely a JSON body -- a real quirk of the
                    # live service, confirmed by hand; content_type=None
                    # tells aiohttp not to reject it over the wrong header.
                    records = await resp.json(content_type=None)
            except aiohttp.ClientError:
                _LOGGER.exception("WifiDB lookup failed for %s", ap.bssid)
                continue

            # "Not found" is a bare JSON string ("No AP's Found"), not an
            # empty array, confirmed against the live API -- guard against
            # treating its characters as records.
            if not isinstance(records, list) or not records:
                _LOGGER.debug("WifiDB has no record of %s", ap.bssid)
                continue

            # Multiple sightings can come back for the same BSSID; prefer
            # the most recently-confirmed one ("LA" = last-added/-seen).
            # Some records carry an explicit `"LA": null` rather than
            # omitting the key, so `or ""` (not just `.get(..., "")`) is
            # needed to keep those sorting first-to-lose, not crashing.
            best = max(records, key=lambda r: r.get("LA") or "")
            try:
                lat = float(best["lat"])
                lon = float(best["long"])
            except (KeyError, TypeError, ValueError):
                continue

            # Stronger (less negative) signal -> higher weight.
            weight = 10 ** (ap.signal_strength_dbm / 10)
            weighted_points.append((lat, lon, weight))

        if not weighted_points:
            return None

        total_weight = sum(w for _, _, w in weighted_points)
        lat = sum(lat * w for lat, _, w in weighted_points) / total_weight
        lon = sum(lon * w for _, lon, w in weighted_points) / total_weight
        return Coordinates(latitude=lat, longitude=lon, accuracy_m=DEFAULT_ACCURACY_M)
