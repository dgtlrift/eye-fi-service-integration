"""Apple ecosystem "destination" — really just an alias over
:mod:`eyefi_core.storage.local_nas` / :mod:`eyefi_core.storage.remote_nas`,
pointed at a folder one of the user's Apple devices can also reach.

This module has no visibility into which on-device automation (Mac Folder
Action vs. iOS Shortcuts) picks up files from that folder — see
``docs/apple-ecosystem-setup.md`` for the user-facing setup instructions
for both paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eyefi_core.storage import StorageBackend


@dataclass(frozen=True, slots=True)
class AppleDropFolderBackend:
    _delegate: StorageBackend

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "AppleDropFolderBackend":
        if config.get("mount") == "remote":
            from eyefi_core.storage.remote_nas import RemoteNasBackend

            return cls(_delegate=RemoteNasBackend.from_config(config))

        from eyefi_core.storage.local_nas import LocalNasBackend

        return cls(_delegate=LocalNasBackend(root=Path(config["path"])))

    async def store(self, image_path: Path, metadata: dict[str, Any]) -> None:
        await self._delegate.store(image_path, metadata)
