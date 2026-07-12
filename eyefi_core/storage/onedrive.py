"""Microsoft OneDrive backend via the Microsoft Graph API.

OAuth2 token acquisition/refresh is handled by the HA adapter's config-flow
auth step; this backend only ever sees a currently-valid access token
(refreshed by the caller before ``store()`` if needed).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp

from eyefi_core.storage import StorageError

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SIMPLE_UPLOAD_LIMIT = 4 * 1024 * 1024  # Graph requires an upload session above 4 MiB


@dataclass(frozen=True, slots=True)
class OneDriveBackend:
    access_token: str
    remote_folder: str = "/Eye-Fi"

    async def store(self, image_path: Path, metadata: dict[str, Any]) -> None:
        data = image_path.read_bytes()
        async with aiohttp.ClientSession() as session:
            if len(data) <= SIMPLE_UPLOAD_LIMIT:
                await self._simple_upload(session, image_path.name, data)
            else:
                await self._resumable_upload(session, image_path.name, data)

    async def _simple_upload(
        self, session: aiohttp.ClientSession, filename: str, data: bytes
    ) -> None:
        url = f"{GRAPH_BASE}/me/drive/root:{self.remote_folder}/{filename}:/content"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/octet-stream",
        }
        async with session.put(url, headers=headers, data=data) as resp:
            if resp.status not in (200, 201):
                raise StorageError(f"OneDrive upload failed: HTTP {resp.status}")

    async def _resumable_upload(
        self, session: aiohttp.ClientSession, filename: str, data: bytes
    ) -> None:
        session_url = f"{GRAPH_BASE}/me/drive/root:{self.remote_folder}/{filename}:/createUploadSession"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with session.post(session_url, headers=headers, json={}) as resp:
            if resp.status != 200:
                raise StorageError(f"OneDrive upload session creation failed: HTTP {resp.status}")
            upload_url = (await resp.json())["uploadUrl"]

        chunk_size = 5 * 1024 * 1024
        total = len(data)
        for start in range(0, total, chunk_size):
            chunk = data[start : start + chunk_size]
            end = start + len(chunk) - 1
            chunk_headers = {
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {start}-{end}/{total}",
            }
            async with session.put(upload_url, headers=chunk_headers, data=chunk) as resp:
                if resp.status not in (200, 201, 202):
                    raise StorageError(f"OneDrive chunk upload failed: HTTP {resp.status}")
