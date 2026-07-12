"""Untar an UploadPhoto payload, verifying the INTEGRITYDIGEST multipart
field before touching disk.

Per the reference implementations, the UploadPhoto POST is
``multipart/form-data`` with (at least) three parts: ``SOAPENVELOPE`` (XML
metadata, see :mod:`eyefi_core.protocol`), ``FILENAME`` (the raw tar bytes —
JPEG + ``.log`` sidecar), and ``INTEGRITYDIGEST`` (hex MD5 the card computed
over the tar bytes + upload key, see
:func:`eyefi_core.protocol.calculate_integrity_digest`). aiohttp's multipart
reader handles the actual part splitting; this module only deals with the
tar bytes once extracted from the ``FILENAME`` part.
"""

from __future__ import annotations

import asyncio
import io
import tarfile
from dataclasses import dataclass
from pathlib import Path

from eyefi_core import protocol


class IntegrityError(ValueError):
    """The computed integrity digest didn't match the one the card sent."""


@dataclass(frozen=True, slots=True)
class ExtractedUpload:
    stem: str
    image_path: Path
    log_path: Path | None


def verify_integrity(tar_bytes: bytes, upload_key: str, expected_digest: str) -> None:
    actual_digest = protocol.calculate_integrity_digest(tar_bytes, upload_key)
    if actual_digest.lower() != expected_digest.lower():
        raise IntegrityError(
            f"integrity digest mismatch: computed {actual_digest}, "
            f"card sent {expected_digest}"
        )


def _extract_sync(tar_bytes: bytes, dest_dir: Path) -> list[ExtractedUpload]:
    dest_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tf:
        extract_kwargs = {}
        if hasattr(tarfile, "data_filter"):
            extract_kwargs["filter"] = "data"
        tf.extractall(dest_dir, **extract_kwargs)
        member_names = [m.name for m in tf.getmembers() if m.isfile()]

    logs: dict[str, Path] = {}
    images: dict[str, Path] = {}
    for name in member_names:
        path = dest_dir / name
        stem = path.stem
        if path.suffix.lower() == ".log":
            logs[stem] = path
        else:
            images[stem] = path

    return [
        ExtractedUpload(stem=stem, image_path=image_path, log_path=logs.get(stem))
        for stem, image_path in images.items()
    ]


async def extract_upload(
    tar_bytes: bytes,
    *,
    upload_key: str,
    expected_digest: str,
    dest_dir: Path,
) -> list[ExtractedUpload]:
    """Verify integrity and untar, returning each image paired with its
    ``.log`` sidecar (if the card sent one). Runs in a thread executor since
    both MD5-ing and untarring a multi-megabyte payload are CPU/IO-bound.
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, verify_integrity, tar_bytes, upload_key, expected_digest)
    return await loop.run_in_executor(None, _extract_sync, tar_bytes, dest_dir)
