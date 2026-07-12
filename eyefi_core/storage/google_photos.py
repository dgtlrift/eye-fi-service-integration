"""Google Photos backend: ``photoslibrary.appendonly`` scope.

Upload-only by design — post-March-2025 API changes mean this scope can no
longer read back or manage the existing library, only content the app
itself created. Fine for "upload and forget"; not usable for dedup checks
against the existing library (see the project brief).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp

from eyefi_core.storage import StorageError

UPLOAD_URL = "https://photoslibrary.googleapis.com/v1/uploads"
BATCH_CREATE_URL = "https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate"


@dataclass(frozen=True, slots=True)
class GooglePhotosBackend:
    access_token: str
    album_id: str | None = None

    async def store(self, image_path: Path, metadata: dict[str, Any]) -> None:
        async with aiohttp.ClientSession() as session:
            upload_token = await self._upload_bytes(session, image_path)
            await self._create_media_item(session, upload_token, image_path.name)

    async def _upload_bytes(self, session: aiohttp.ClientSession, image_path: Path) -> str:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/octet-stream",
            "X-Goog-Upload-Protocol": "raw",
            "X-Goog-Upload-File-Name": image_path.name,
        }
        async with session.post(UPLOAD_URL, headers=headers, data=image_path.read_bytes()) as resp:
            if resp.status != 200:
                raise StorageError(f"Google Photos byte upload failed: HTTP {resp.status}")
            return await resp.text()

    async def _create_media_item(
        self, session: aiohttp.ClientSession, upload_token: str, filename: str
    ) -> None:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "newMediaItems": [
                {
                    "description": filename,
                    "simpleMediaItem": {"uploadToken": upload_token},
                }
            ]
        }
        if self.album_id:
            payload["albumId"] = self.album_id

        async with session.post(BATCH_CREATE_URL, headers=headers, json=payload) as resp:
            if resp.status != 200:
                raise StorageError(f"Google Photos batchCreate failed: HTTP {resp.status}")
            body = await resp.json()
            result = body.get("newMediaItemResults", [{}])[0]
            status = result.get("status", {})
            if status.get("code") not in (None, 0):
                raise StorageError(f"Google Photos batchCreate rejected: {status}")
