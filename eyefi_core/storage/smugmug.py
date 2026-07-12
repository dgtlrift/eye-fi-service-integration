"""SmugMug backend: REST API v2 image upload, OAuth 1.0a.

Implements OAuth 1.0a request signing directly (HMAC-SHA1) with the stdlib
rather than pulling in ``requests_oauthlib``, since aiohttp needs the
``Authorization`` header built up-front rather than via a requests
auth hook.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp

from eyefi_core.storage import StorageError

UPLOAD_URL = "https://upload.smugmug.com/"


@dataclass(frozen=True, slots=True)
class SmugMugBackend:
    consumer_key: str
    consumer_secret: str
    access_token: str
    access_token_secret: str
    album_uri: str

    def _oauth_header(self, method: str, url: str) -> str:
        oauth_params = {
            "oauth_consumer_key": self.consumer_key,
            "oauth_token": self.access_token,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_nonce": secrets.token_hex(16),
            "oauth_version": "1.0",
        }

        base_params = "&".join(
            f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
            for k, v in sorted(oauth_params.items())
        )
        base_string = "&".join(
            urllib.parse.quote(part, safe="")
            for part in (method.upper(), url, base_params)
        )
        signing_key = (
            f"{urllib.parse.quote(self.consumer_secret, safe='')}&"
            f"{urllib.parse.quote(self.access_token_secret, safe='')}"
        )
        signature = base64.b64encode(
            hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
        ).decode()
        oauth_params["oauth_signature"] = signature

        return "OAuth " + ", ".join(
            f'{k}="{urllib.parse.quote(v, safe="")}"' for k, v in oauth_params.items()
        )

    async def store(self, image_path: Path, metadata: dict[str, Any]) -> None:
        headers = {
            "Authorization": self._oauth_header("POST", UPLOAD_URL),
            "X-Smug-AlbumUri": self.album_uri,
            "X-Smug-ResponseType": "JSON",
            "X-Smug-Version": "v2",
            "X-Smug-FileName": image_path.name,
            "Content-MD5": hashlib.md5(image_path.read_bytes()).hexdigest(),
            "Content-Type": "application/octet-stream",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                UPLOAD_URL, headers=headers, data=image_path.read_bytes()
            ) as resp:
                if resp.status != 200:
                    raise StorageError(f"SmugMug upload failed: HTTP {resp.status}")
                body = await resp.json()
                if body.get("stat") != "ok":
                    raise StorageError(f"SmugMug upload rejected: {body}")
