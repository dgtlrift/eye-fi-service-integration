"""Retroactively geotag already-uploaded photos.

Extraction leaves each JPEG's ``.log`` sidecar sitting next to it in
``<download_dir>/<macaddress>/`` permanently (nothing deletes it), so any
photo that missed geotagging at upload time -- because the backend wasn't
configured yet, a bug in the matching logic, or the lag window was too
tight -- can be revisited later with whatever backend is configured *now*.
Reuses the exact same :func:`eyefi_core.geotag.geotag_image` and
``storage_backend.store()`` calls the live upload path uses, so fixing
either and re-running this catches up anything missed, uniformly across
every storage destination (local or remote).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

import piexif

from eyefi_core import geotag
from eyefi_core.storage import StorageBackend

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BackfillSummary:
    processed: int = 0
    tagged: int = 0
    already_tagged: int = 0
    unresolved: int = 0
    errors: int = 0

    def __add__(self, other: "BackfillSummary") -> "BackfillSummary":
        return BackfillSummary(
            processed=self.processed + other.processed,
            tagged=self.tagged + other.tagged,
            already_tagged=self.already_tagged + other.already_tagged,
            unresolved=self.unresolved + other.unresolved,
            errors=self.errors + other.errors,
        )


def _has_gps_tags(image_path: Path) -> bool:
    try:
        exif_dict = piexif.load(str(image_path))
    except Exception:
        return False
    return piexif.GPSIFD.GPSLatitude in exif_dict.get("GPS", {})


async def backfill_geotags(
    *,
    download_dir: Path,
    geotag_backend: geotag.GeolocationBackend,
    storage_backend: StorageBackend,
    geotag_lag: int = geotag.DEFAULT_GEOTAG_LAG_SECONDS,
) -> BackfillSummary:
    """Scan every ``<download_dir>/<mac>/*.log`` sidecar and geotag+re-store
    whichever matching JPEGs don't already carry GPS EXIF tags."""
    loop = asyncio.get_running_loop()
    summary = BackfillSummary()

    for log_path in sorted(download_dir.glob("*/*.log")):
        image_path = log_path.with_suffix("")
        if not image_path.is_file():
            continue

        summary += BackfillSummary(processed=1)

        try:
            already_tagged = await loop.run_in_executor(None, _has_gps_tags, image_path)
            if already_tagged:
                summary += BackfillSummary(already_tagged=1)
                continue

            coordinates = await geotag.geotag_image(
                image_path=image_path,
                log_path=log_path,
                backend=geotag_backend,
                geotag_lag=geotag_lag,
            )
        except Exception:
            _LOGGER.exception("Backfill geotagging failed for %s", image_path)
            summary += BackfillSummary(errors=1)
            continue

        if coordinates is None:
            summary += BackfillSummary(unresolved=1)
            continue

        metadata = {
            "macaddress": log_path.parent.name,
            "filename": image_path.name,
            "latitude": coordinates.latitude,
            "longitude": coordinates.longitude,
        }
        try:
            await storage_backend.store(image_path, metadata)
        except Exception:
            _LOGGER.exception("Backfill re-store failed for %s", image_path)
            summary += BackfillSummary(errors=1)
            continue

        _LOGGER.info(
            "Backfilled GPS for %s: %s, %s", image_path.name, coordinates.latitude, coordinates.longitude
        )
        summary += BackfillSummary(tagged=1)

    return summary
