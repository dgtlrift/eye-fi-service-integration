from pathlib import Path

import pytest

from eyefi_core import backfill, geotag

SAMPLE_LOG = """\
100,0,POWERON
105,0,NEWAP,001122334455,80
106,0,NEWAP,aabbccddeeff,60
110,0,NEWPHOTO,{stem}.JPG
"""


class _FakeBackend:
    def __init__(self, coordinates: geotag.Coordinates | None):
        self._coordinates = coordinates

    async def resolve(self, access_points):
        return self._coordinates


class _FakeStorage:
    def __init__(self) -> None:
        self.stored: list[tuple[Path, dict]] = []

    async def store(self, image_path: Path, metadata: dict) -> None:
        self.stored.append((image_path, metadata))


def _make_photo(tmp_path: Path, mac: str, stem: str) -> None:
    Image = pytest.importorskip("PIL.Image")
    mac_dir = tmp_path / mac
    mac_dir.mkdir(exist_ok=True)
    Image.new("RGB", (4, 4)).save(mac_dir / f"{stem}.JPG", "jpeg")
    (mac_dir / f"{stem}.JPG.log").write_text(SAMPLE_LOG.format(stem=stem))


@pytest.mark.asyncio
async def test_backfill_tags_and_restores_untagged_photos(tmp_path: Path):
    pytest.importorskip("piexif")
    _make_photo(tmp_path, "0018564125f5", "IMG_0001")

    backend = _FakeBackend(geotag.Coordinates(latitude=37.7749, longitude=-122.4194))
    storage = _FakeStorage()

    summary = await backfill.backfill_geotags(
        download_dir=tmp_path, geotag_backend=backend, storage_backend=storage
    )

    assert summary == backfill.BackfillSummary(processed=1, tagged=1)
    assert len(storage.stored) == 1
    image_path, metadata = storage.stored[0]
    assert image_path.name == "IMG_0001.JPG"
    assert metadata["latitude"] == 37.7749
    assert metadata["macaddress"] == "0018564125f5"


@pytest.mark.asyncio
async def test_backfill_skips_already_tagged_photos(tmp_path: Path):
    pytest.importorskip("piexif")
    _make_photo(tmp_path, "0018564125f5", "IMG_0002")
    image_path = tmp_path / "0018564125f5" / "IMG_0002.JPG"
    geotag.write_gps_exif(image_path, geotag.Coordinates(latitude=1.0, longitude=2.0))

    backend = _FakeBackend(geotag.Coordinates(latitude=99.0, longitude=99.0))
    storage = _FakeStorage()

    summary = await backfill.backfill_geotags(
        download_dir=tmp_path, geotag_backend=backend, storage_backend=storage
    )

    assert summary == backfill.BackfillSummary(processed=1, already_tagged=1)
    assert storage.stored == []


@pytest.mark.asyncio
async def test_backfill_counts_unresolved_when_backend_finds_nothing(tmp_path: Path):
    pytest.importorskip("piexif")
    _make_photo(tmp_path, "0018564125f5", "IMG_0003")

    backend = _FakeBackend(None)
    storage = _FakeStorage()

    summary = await backfill.backfill_geotags(
        download_dir=tmp_path, geotag_backend=backend, storage_backend=storage
    )

    assert summary == backfill.BackfillSummary(processed=1, unresolved=1)
    assert storage.stored == []


@pytest.mark.asyncio
async def test_backfill_counts_errors_without_aborting_other_photos(tmp_path: Path):
    pytest.importorskip("piexif")
    _make_photo(tmp_path, "0018564125f5", "IMG_0004")
    _make_photo(tmp_path, "0018564125f5", "IMG_0005")

    class _RaisingBackend:
        async def resolve(self, access_points):
            raise RuntimeError("boom")

    storage = _FakeStorage()
    summary = await backfill.backfill_geotags(
        download_dir=tmp_path, geotag_backend=_RaisingBackend(), storage_backend=storage
    )

    assert summary == backfill.BackfillSummary(processed=2, errors=2)
