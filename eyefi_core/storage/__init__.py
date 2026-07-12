"""Pluggable storage backend interface, dispatch, and a spool/retry wrapper.

Every backend implements the same tiny async ``store()`` contract so
swapping destinations never touches the upload/geotagging pipeline, and
never needs to know about Home Assistant.
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any, Protocol

_LOGGER = logging.getLogger(__name__)


class StorageError(RuntimeError):
    """Raised by a backend's ``store()`` when the destination is
    unreachable or rejects the upload. Treated as retryable by
    :class:`SpoolingStorageBackend`."""


class StorageBackend(Protocol):
    async def store(self, image_path: Path, metadata: dict[str, Any]) -> None: ...


class SpoolingStorageBackend:
    """Wraps another backend: on :class:`StorageError`, copies the file and
    its metadata into a flat spool directory instead of losing it. Call
    :meth:`retry_spool` periodically (e.g. from a HA time interval) to
    flush anything that accumulated while the destination was unreachable.
    """

    def __init__(self, backend: StorageBackend, spool_dir: Path) -> None:
        self._backend = backend
        self._spool_dir = spool_dir

    async def store(self, image_path: Path, metadata: dict[str, Any]) -> None:
        try:
            await self._backend.store(image_path, metadata)
        except StorageError:
            _LOGGER.warning("Store failed for %s, spooling for retry", image_path)
            self._spool(image_path, metadata)

    def _spool(self, image_path: Path, metadata: dict[str, Any]) -> None:
        self._spool_dir.mkdir(parents=True, exist_ok=True)
        spool_id = uuid.uuid4().hex
        spooled_image = self._spool_dir / f"{spool_id}_{image_path.name}"
        shutil.copy2(image_path, spooled_image)
        (self._spool_dir / f"{spool_id}.json").write_text(
            json.dumps({"image": spooled_image.name, "metadata": metadata})
        )

    async def retry_spool(self) -> None:
        if not self._spool_dir.is_dir():
            return
        for meta_path in sorted(self._spool_dir.glob("*.json")):
            entry = json.loads(meta_path.read_text())
            image_path = self._spool_dir / entry["image"]
            if not image_path.exists():
                meta_path.unlink(missing_ok=True)
                continue
            try:
                await self._backend.store(image_path, entry["metadata"])
            except StorageError:
                continue  # still unreachable; leave it spooled
            image_path.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)


def create_backend(destination: str, config: dict[str, Any]) -> StorageBackend:
    """Dispatch a destination name (as chosen in the HA config flow) to its
    backend implementation. ``config`` holds only plain dicts/strings —
    this module and everything it imports has zero ``homeassistant.*``
    dependencies."""
    if destination == "local_nas":
        from eyefi_core.storage.local_nas import LocalNasBackend

        return LocalNasBackend(root=Path(config["path"]))

    if destination == "remote_nas":
        from eyefi_core.storage.remote_nas import RemoteNasBackend

        return RemoteNasBackend.from_config(config)

    if destination == "apple_dropfolder":
        from eyefi_core.storage.apple_dropfolder import AppleDropFolderBackend

        return AppleDropFolderBackend.from_config(config)

    if destination == "google_photos":
        from eyefi_core.storage.google_photos import GooglePhotosBackend

        return GooglePhotosBackend(**config)

    if destination == "onedrive":
        from eyefi_core.storage.onedrive import OneDriveBackend

        return OneDriveBackend(**config)

    if destination == "smugmug":
        from eyefi_core.storage.smugmug import SmugMugBackend

        return SmugMugBackend(**config)

    if destination == "backblaze":
        from eyefi_core.storage.backblaze import BackblazeBackend

        return BackblazeBackend(**config)

    if destination == "pcloud":
        from eyefi_core.storage.pcloud import PCloudBackend

        return PCloudBackend(**config)

    raise ValueError(f"Unknown storage destination: {destination!r}")
