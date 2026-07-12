"""pCloud backend: REST API, OAuth2 bearer token."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp

from eyefi_core.storage import StorageError

UPLOAD_URL = "https://api.pcloud.com/uploadfile"


@dataclass(frozen=True, slots=True)
class PCloudBackend:
    access_token: str
    remote_folder: str = "/Eye-Fi"

    async def store(self, image_path: Path, metadata: dict[str, Any]) -> None:
        form = aiohttp.FormData()
        form.add_field(
            "file",
            image_path.read_bytes(),
            filename=image_path.name,
            content_type="application/octet-stream",
        )
        params = {
            "access_token": self.access_token,
            "path": self.remote_folder,
            "filename": image_path.name,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(UPLOAD_URL, params=params, data=form) as resp:
                if resp.status != 200:
                    raise StorageError(f"pCloud upload failed: HTTP {resp.status}")
                body = await resp.json()
                if body.get("result") != 0:
                    raise StorageError(f"pCloud upload rejected: {body}")
