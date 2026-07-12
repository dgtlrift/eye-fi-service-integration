"""Remote NAS backend for hosts without an OS-level SMB/NFS mount.

Two protocols, selected via config's ``protocol`` key:

- ``"smb"`` — pure-Python SMB2/3 via ``smbprotocol``'s ``smbclient``
  convenience layer. That library is synchronous, so calls run in a thread
  executor to stay off the event loop.
- ``"sftp"`` — ``asyncssh``, which is natively async.

Avoids shelling out to ``smbclient``/``rsync`` so everything stays inside
the asyncio runtime.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eyefi_core.storage import StorageError


@dataclass(frozen=True, slots=True)
class RemoteNasBackend:
    protocol: str  # "smb" | "sftp"
    host: str
    remote_path: str
    username: str
    password: str | None = None
    port: int | None = None

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "RemoteNasBackend":
        return cls(
            protocol=config["protocol"],
            host=config["host"],
            remote_path=config["remote_path"],
            username=config["username"],
            password=config.get("password"),
            port=config.get("port"),
        )

    async def store(self, image_path: Path, metadata: dict[str, Any]) -> None:
        if self.protocol == "smb":
            await self._store_smb(image_path)
        elif self.protocol == "sftp":
            await self._store_sftp(image_path)
        else:
            raise StorageError(f"unknown remote_nas protocol {self.protocol!r}")

    async def _store_smb(self, image_path: Path) -> None:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._store_smb_sync, image_path)
        except Exception as exc:  # smbprotocol raises its own exception hierarchy
            raise StorageError(f"SMB upload of {image_path.name} failed") from exc

    def _store_smb_sync(self, image_path: Path) -> None:
        import smbclient

        smbclient.register_session(
            self.host, username=self.username, password=self.password, port=self.port or 445
        )
        remote_file = f"\\\\{self.host}\\{self.remote_path.rstrip('/')}\\{image_path.name}"
        with open(image_path, "rb") as src, smbclient.open_file(remote_file, mode="wb") as dst:
            dst.write(src.read())

    async def _store_sftp(self, image_path: Path) -> None:
        import asyncssh

        try:
            async with asyncssh.connect(
                self.host,
                port=self.port or 22,
                username=self.username,
                password=self.password,
                known_hosts=None,
            ) as conn:
                async with conn.start_sftp_client() as sftp:
                    remote_file = f"{self.remote_path.rstrip('/')}/{image_path.name}"
                    await sftp.put(str(image_path), remote_file)
        except (asyncssh.Error, OSError) as exc:
            raise StorageError(f"SFTP upload of {image_path.name} failed") from exc
