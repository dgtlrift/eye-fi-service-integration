"""Geotagging pipeline: parse the card's WiFi-scan ``.log`` sidecar,
resolve a lat/long via a pluggable geolocation backend, and write the
result into the JPEG's EXIF GPS tags with ``piexif``.

``.log`` format (one CSV-ish record per line, ported from
``dgrant/eyefiserver2``'s ``parselog``/``getphotoaps`` — read-only
reference, not copied verbatim)::

    <time>,<timestamp>,<ACTION>,<arg1>,<arg2>,...

Known actions:

- ``AP`` / ``NEWAP`` — args: ``bssid, signal`` — a WiFi AP the card saw at
  ``<time>``, with the card's raw (non-dBm) signal reading.
- ``NEWPHOTO`` — args: ``filename`` — marks ``<time>`` as the moment the
  named photo (base filename, no extension) was taken.
- ``POWERON`` — marks the start of a new card power cycle. A single
  ``.log`` file can span multiple power cycles; once a target photo's
  ``NEWPHOTO`` has been seen, the *next* ``POWERON`` ends that session.

Only AP sightings within ``geotag_lag`` seconds of the shot are considered
for resolution, each weighted toward the reading closest in time.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import aiohttp
import piexif

_LOGGER = logging.getLogger(__name__)

DEFAULT_GEOTAG_LAG_SECONDS = 30


@dataclass(frozen=True, slots=True)
class ApSighting:
    bssid: str
    time: int
    pwr: int


@dataclass(frozen=True, slots=True)
class AccessPoint:
    """An AP sighting selected as relevant to a specific shot, with its raw
    reading converted to an approximate dBm signal strength."""

    bssid: str
    signal_strength_dbm: int


@dataclass(frozen=True, slots=True)
class Coordinates:
    latitude: float
    longitude: float
    accuracy_m: float | None = None


def parse_log(log_text: str, image_stem: str) -> tuple[int, dict[str, list[ApSighting]]] | None:
    """Return ``(shot_time, {bssid: [sightings]})`` for the power-on session
    containing ``image_stem``'s ``NEWPHOTO`` marker, or ``None`` if not
    found."""
    shot_time = 0
    aps: dict[str, list[ApSighting]] = {}

    for line in log_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            time_str, _timestamp, rest = line.split(",", 2)
        except ValueError:
            continue

        fields = rest.split(",")
        action, args = fields[0], fields[1:]
        time_val = int(time_str)

        if action in ("AP", "NEWAP") and len(args) >= 2:
            bssid, pwr = args[0], args[1]
            aps.setdefault(bssid, []).append(
                ApSighting(bssid=bssid, time=time_val, pwr=int(pwr))
            )
        elif action == "NEWPHOTO" and args:
            if args[0] == image_stem:
                shot_time = time_val
        elif action == "POWERON":
            if shot_time > 0:
                return shot_time, aps
            shot_time = 0
            aps = {}

    if shot_time > 0:
        return shot_time, aps
    return None


def _pwr_to_dbm(pwr: int) -> int:
    """Approximate the card's raw signal reading as dBm, matching the
    conversion used by prior Eye-Fi servers against Google's geolocation
    APIs."""
    return int(math.log10(pwr / 100.0) * 10 - 50)


def select_access_points(
    shot_time: int,
    aps: dict[str, list[ApSighting]],
    *,
    geotag_lag: int = DEFAULT_GEOTAG_LAG_SECONDS,
) -> list[AccessPoint]:
    """Pick, for each BSSID, the sighting closest in time to the shot,
    dropping any farther than ``geotag_lag`` seconds away."""
    selected: list[AccessPoint] = []
    for bssid, sightings in aps.items():
        closest = min(sightings, key=lambda s: abs(s.time - shot_time))
        if abs(closest.time - shot_time) <= geotag_lag:
            selected.append(
                AccessPoint(bssid=bssid, signal_strength_dbm=_pwr_to_dbm(closest.pwr))
            )
    return selected


def format_bssid(bssid_hex: str) -> str:
    """``"0018560304f8"`` -> ``"00:18:56:03:04:f8"``."""
    return ":".join(bssid_hex[i : i + 2] for i in range(0, len(bssid_hex), 2)).lower()


class GeolocationBackend(Protocol):
    async def resolve(self, access_points: list[AccessPoint]) -> Coordinates | None: ...


GOOGLE_GEOLOCATION_URL = "https://www.googleapis.com/geolocation/v1/geolocate"


@dataclass(frozen=True, slots=True)
class GoogleGeolocationBackend:
    """POSTs to Google's Geolocation API. Paid past the free tier — this is
    what the pre-existing Eye-Fi server forks used (via the now-deprecated
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


WIGLE_SEARCH_URL = "https://api.wigle.net/api/v2/network/search"


@dataclass(frozen=True, slots=True)
class WigleGeolocationBackend:
    """Free-tier fallback using WiGLE's community-sourced BSSID database.

    WiGLE has no built-in multilateration endpoint, so this looks up each
    BSSID's last-known location individually and returns the
    signal-strength-weighted centroid of whichever BSSIDs it recognizes.
    """

    api_name: str
    api_token: str
    session: aiohttp.ClientSession

    async def resolve(self, access_points: list[AccessPoint]) -> Coordinates | None:
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
                    if resp.status != 200:
                        continue
                    body = await resp.json()
            except aiohttp.ClientError:
                _LOGGER.exception("WiGLE lookup failed for %s", ap.bssid)
                continue

            results = body.get("results") or []
            if not results:
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


def _to_dms_rational(value: float) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    """Decimal degrees -> piexif's ((deg,1),(min,1),(sec_num,sec_den)) form."""
    value = abs(value)
    degrees = int(value)
    minutes_float = (value - degrees) * 60
    minutes = int(minutes_float)
    seconds = round((minutes_float - minutes) * 60 * 100)
    return (degrees, 1), (minutes, 1), (seconds, 100)


def write_gps_exif(image_path: Path, coordinates: Coordinates) -> None:
    """Write GPSLatitude/GPSLongitude(+Ref) into ``image_path``'s EXIF,
    preserving any other EXIF data already present. Synchronous/CPU-bound —
    run via an executor from async callers.
    """
    try:
        exif_dict = piexif.load(str(image_path))
    except Exception:
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

    lat_ref = "N" if coordinates.latitude >= 0 else "S"
    lon_ref = "E" if coordinates.longitude >= 0 else "W"

    exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = lat_ref
    exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = _to_dms_rational(coordinates.latitude)
    exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = lon_ref
    exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = _to_dms_rational(coordinates.longitude)
    if coordinates.accuracy_m is not None:
        exif_dict["GPS"][piexif.GPSIFD.GPSHPositioningError] = (
            round(coordinates.accuracy_m * 100),
            100,
        )

    exif_bytes = piexif.dump(exif_dict)
    piexif.insert(exif_bytes, str(image_path))


async def geotag_image(
    *,
    image_path: Path,
    log_path: Path,
    backend: GeolocationBackend,
    geotag_lag: int = DEFAULT_GEOTAG_LAG_SECONDS,
) -> Coordinates | None:
    """Parse the sidecar log, resolve coordinates, and write EXIF GPS tags.

    Returns the resolved coordinates, or ``None`` if the log had no usable
    AP data or the backend couldn't resolve a location — callers should
    treat that as "photo delivered, geotagging skipped," never as a
    failure of the upload itself.
    """
    loop = asyncio.get_running_loop()
    log_text = await loop.run_in_executor(None, log_path.read_text)

    parsed = parse_log(log_text, image_path.stem)
    if parsed is None:
        _LOGGER.debug("No NEWPHOTO marker for %s in %s", image_path.stem, log_path)
        return None

    shot_time, aps = parsed
    access_points = select_access_points(shot_time, aps, geotag_lag=geotag_lag)
    if not access_points:
        _LOGGER.debug("No AP sightings near shot time for %s", image_path.stem)
        return None

    coordinates = await backend.resolve(access_points)
    if coordinates is None:
        _LOGGER.debug("Geolocation backend could not resolve %s", image_path.stem)
        return None

    await loop.run_in_executor(None, write_gps_exif, image_path, coordinates)
    return coordinates
