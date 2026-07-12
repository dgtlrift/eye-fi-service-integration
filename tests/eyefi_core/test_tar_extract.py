import io
import tarfile
from pathlib import Path

import pytest

from eyefi_core import protocol, tar_extract


def _make_tar(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, content in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def test_verify_integrity_accepts_matching_digest():
    upload_key = "00112233445566778899aabbccddeeff"[:32]
    data = b"hello world" * 100
    digest = protocol.calculate_integrity_digest(data, upload_key)
    tar_extract.verify_integrity(data, upload_key, digest)  # should not raise


def test_verify_integrity_rejects_mismatched_digest():
    upload_key = "00112233445566778899aabbccddeeff"[:32]
    data = b"hello world" * 100
    with pytest.raises(tar_extract.IntegrityError):
        tar_extract.verify_integrity(data, upload_key, "0" * 32)


@pytest.mark.asyncio
async def test_extract_upload_pairs_image_with_log_sidecar(tmp_path: Path):
    upload_key = "00112233445566778899aabbccddeeff"[:32]
    tar_bytes = _make_tar(
        {
            "IMG_0001.JPG": b"\xff\xd8\xff\xd9",  # minimal JPEG magic bytes
            "IMG_0001.log": b"100,0,POWERON\n",
        }
    )
    digest = protocol.calculate_integrity_digest(tar_bytes, upload_key)

    dest_dir = tmp_path / "out"
    results = await tar_extract.extract_upload(
        tar_bytes, upload_key=upload_key, expected_digest=digest, dest_dir=dest_dir
    )

    assert len(results) == 1
    item = results[0]
    assert item.stem == "IMG_0001"
    assert item.image_path.exists()
    assert item.log_path is not None
    assert item.log_path.exists()


@pytest.mark.asyncio
async def test_extract_upload_raises_on_bad_digest(tmp_path: Path):
    upload_key = "00112233445566778899aabbccddeeff"[:32]
    tar_bytes = _make_tar({"IMG_0002.JPG": b"data"})

    with pytest.raises(tar_extract.IntegrityError):
        await tar_extract.extract_upload(
            tar_bytes,
            upload_key=upload_key,
            expected_digest="deadbeef" * 4,
            dest_dir=tmp_path / "out",
        )
