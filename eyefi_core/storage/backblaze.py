"""Backblaze B2 backend: native B2 API, application-key auth."""

from __future__ import annotations

import hashlib
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp

from eyefi_core.storage import StorageError

AUTHORIZE_URL = "https://api.backblazeb2.com/b2api/v2/b2_authorize_account"


@dataclass(frozen=True, slots=True)
class BackblazeBackend:
    key_id: str
    application_key: str
    bucket_id: str

    async def store(self, image_path: Path, metadata: dict[str, Any]) -> None:
        async with aiohttp.ClientSession() as session:
            api_url, auth_token = await self._authorize(session)
            upload_url, upload_auth_token = await self._get_upload_url(
                session, api_url, auth_token
            )
            await self._upload(session, upload_url, upload_auth_token, image_path)

    async def _authorize(self, session: aiohttp.ClientSession) -> tuple[str, str]:
        auth = aiohttp.BasicAuth(self.key_id, self.application_key)
        async with session.get(AUTHORIZE_URL, auth=auth) as resp:
            if resp.status != 200:
                raise StorageError(f"B2 authorize_account failed: HTTP {resp.status}")
            body = await resp.json()
            return body["apiUrl"], body["authorizationToken"]

    async def _get_upload_url(
        self, session: aiohttp.ClientSession, api_url: str, auth_token: str
    ) -> tuple[str, str]:
        url = f"{api_url}/b2api/v2/b2_get_upload_url"
        headers = {"Authorization": auth_token}
        async with session.post(url, headers=headers, json={"bucketId": self.bucket_id}) as resp:
            if resp.status != 200:
                raise StorageError(f"B2 get_upload_url failed: HTTP {resp.status}")
            body = await resp.json()
            return body["uploadUrl"], body["authorizationToken"]

    async def _upload(
        self,
        session: aiohttp.ClientSession,
        upload_url: str,
        upload_auth_token: str,
        image_path: Path,
    ) -> None:
        data = image_path.read_bytes()
        headers = {
            "Authorization": upload_auth_token,
            "X-Bz-File-Name": urllib.parse.quote(image_path.name),
            "Content-Type": "b2/x-auto",
            "Content-Length": str(len(data)),
            "X-Bz-Content-Sha1": hashlib.sha1(data).hexdigest(),
        }
        async with session.post(upload_url, headers=headers, data=data) as resp:
            if resp.status != 200:
                raise StorageError(f"B2 upload failed: HTTP {resp.status}")
