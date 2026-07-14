"""Shared shapes for wifi_geolocation_core's backends.

Deliberately not shared by import with eyefi_core's own (structurally
identical) ``AccessPoint``/``Coordinates``/``GeolocationBackend`` — the two
packages are meant to stay independent, connected only through the
``wifi_geolocation.resolve`` HA service's JSON contract, not a shared
Python dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AccessPoint:
    bssid: str
    signal_strength_dbm: int


@dataclass(frozen=True, slots=True)
class Coordinates:
    latitude: float
    longitude: float
    accuracy_m: float | None = None


class GeolocationBackend(Protocol):
    async def resolve(self, access_points: list[AccessPoint]) -> Coordinates | None: ...


def format_bssid(bssid_hex: str) -> str:
    """``"0018560304f8"`` -> ``"00:18:56:03:04:f8"``."""
    return ":".join(bssid_hex[i : i + 2] for i in range(0, len(bssid_hex), 2)).lower()
