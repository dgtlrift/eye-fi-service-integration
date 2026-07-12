"""Local filesystem storage backend.

Covers both truly-local storage and a remote NAS that's already mounted at
the OS level (SMB/NFS) — from this module's point of view it's just a
directory path. ``apple_dropfolder`` reuses this backend directly.
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eyefi_core.storage import StorageError


@dataclass(frozen=True, slots=True)
class LocalNasBackend:
    root: Path

    async def store(self, image_path: Path, metadata: dict[str, Any]) -> None:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._copy, image_path)
        except OSError as exc:
            raise StorageError(f"failed writing {image_path.name} to {self.root}") from exc

    def _copy(self, image_path: Path) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(image_path, self.root / image_path.name)
