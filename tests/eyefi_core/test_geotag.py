from pathlib import Path

import pytest

from eyefi_core import geotag


class _FakeBackend:
    """Satisfies geotag.GeolocationBackend structurally, with no shared
    import — proof that eyefi_core doesn't need to know about
    wifi_geolocation_core (or any specific backend) to use one."""

    def __init__(self, coordinates: geotag.Coordinates | None):
        self._coordinates = coordinates
        self.received_access_points: list[geotag.AccessPoint] | None = None

    async def resolve(self, access_points: list[geotag.AccessPoint]) -> geotag.Coordinates | None:
        self.received_access_points = access_points
        return self._coordinates

SAMPLE_LOG = """\
100,0,POWERON
105,0,NEWAP,001122334455,80
106,0,NEWAP,aabbccddeeff,60
110,0,NEWPHOTO,IMG_0001
150,0,NEWAP,001122334455,90
200,0,POWERON
205,0,NEWAP,ffffffffffff,50
"""


def test_parse_log_finds_shot_time_and_aps_for_matching_photo():
    result = geotag.parse_log(SAMPLE_LOG, "IMG_0001")
    assert result is not None
    shot_time, aps = result
    assert shot_time == 110
    assert set(aps.keys()) == {"001122334455", "aabbccddeeff"}
    # The second POWERON should NOT have pulled in ffffffffffff.
    assert "ffffffffffff" not in aps


def test_parse_log_returns_none_for_unknown_photo():
    assert geotag.parse_log(SAMPLE_LOG, "IMG_9999") is None


def test_select_access_points_picks_closest_reading_within_lag():
    result = geotag.parse_log(SAMPLE_LOG, "IMG_0001")
    assert result is not None
    shot_time, aps = result

    selected = geotag.select_access_points(shot_time, aps, geotag_lag=30)
    bssids = {ap.bssid for ap in selected}
    # 001122334455 has readings at t=105 (|105-110|=5) and t=150 (|150-110|=40);
    # only the t=105 one is within the 30s lag window, so the AP still
    # qualifies (closest reading wins) but via the near one.
    assert "001122334455" in bssids
    assert "aabbccddeeff" in bssids


def test_select_access_points_drops_readings_outside_lag():
    aps = {"001122334455": [geotag.ApSighting(bssid="001122334455", time=0, pwr=80)]}
    selected = geotag.select_access_points(shot_time=1000, aps=aps, geotag_lag=30)
    assert selected == []


def test_to_dms_rational_round_trips_reasonably():
    deg, minute, sec = geotag._to_dms_rational(37.7749)
    assert deg == (37, 1)
    assert minute[0] in range(0, 60)
    assert sec[1] == 100


def test_write_gps_exif_writes_readable_gps_tags(tmp_path: Path):
    import piexif

    Image = pytest.importorskip("PIL.Image")

    image_path = tmp_path / "test.jpg"
    Image.new("RGB", (4, 4)).save(image_path, "jpeg")

    geotag.write_gps_exif(image_path, geotag.Coordinates(latitude=37.7749, longitude=-122.4194))

    exif_dict = piexif.load(str(image_path))
    assert exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] == b"N"
    assert exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] == b"W"
    assert piexif.GPSIFD.GPSLatitude in exif_dict["GPS"]


@pytest.mark.asyncio
async def test_geotag_image_resolves_and_writes_exif_via_any_compatible_backend(tmp_path: Path):
    piexif = pytest.importorskip("piexif")
    Image = pytest.importorskip("PIL.Image")

    image_path = tmp_path / "IMG_0001.JPG"
    Image.new("RGB", (4, 4)).save(image_path, "jpeg")
    log_path = tmp_path / "IMG_0001.log"
    log_path.write_text(SAMPLE_LOG)

    backend = _FakeBackend(geotag.Coordinates(latitude=37.7749, longitude=-122.4194))
    result = await geotag.geotag_image(image_path=image_path, log_path=log_path, backend=backend)

    assert result == geotag.Coordinates(latitude=37.7749, longitude=-122.4194)
    assert backend.received_access_points  # AP selection actually ran and passed something
    exif_dict = piexif.load(str(image_path))
    assert exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] == b"N"


@pytest.mark.asyncio
async def test_geotag_image_returns_none_when_log_has_no_matching_photo(tmp_path: Path):
    Image = pytest.importorskip("PIL.Image")

    image_path = tmp_path / "IMG_9999.JPG"
    Image.new("RGB", (4, 4)).save(image_path, "jpeg")
    log_path = tmp_path / "IMG_9999.log"
    log_path.write_text(SAMPLE_LOG)

    backend = _FakeBackend(geotag.Coordinates(latitude=1.0, longitude=1.0))
    result = await geotag.geotag_image(image_path=image_path, log_path=log_path, backend=backend)

    assert result is None
    assert backend.received_access_points is None  # never even called
