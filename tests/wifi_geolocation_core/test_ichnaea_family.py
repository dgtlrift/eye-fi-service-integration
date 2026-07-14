import pytest

from _fakes import fake_session
from wifi_geolocation_core.beacondb import BEACONDB_URL, BeaconDbGeolocationBackend
from wifi_geolocation_core.combain import COMBAIN_URL, CombainGeolocationBackend
from wifi_geolocation_core.models import AccessPoint, Coordinates
from wifi_geolocation_core.mozilla import MOZILLA_MLS_URL, MozillaGeolocationBackend

AP = [AccessPoint(bssid="0018560304f8", signal_strength_dbm=-65)]


@pytest.mark.asyncio
async def test_combain_resolves_and_sends_api_key():
    session = fake_session(200, {"location": {"lat": 1.0, "lng": 2.0}, "accuracy": 10.0})
    backend = CombainGeolocationBackend(api_key="k", session=session)

    result = await backend.resolve(AP)

    assert result == Coordinates(latitude=1.0, longitude=2.0, accuracy_m=10.0)
    assert session.requests[0]["url"] == COMBAIN_URL
    assert session.requests[0]["params"] == {"key": "k"}


@pytest.mark.asyncio
async def test_beacondb_resolves_without_api_key():
    session = fake_session(200, {"location": {"lat": 3.0, "lng": 4.0}})
    backend = BeaconDbGeolocationBackend(session=session)

    result = await backend.resolve(AP)

    assert result == Coordinates(latitude=3.0, longitude=4.0, accuracy_m=None)
    assert session.requests[0]["url"] == BEACONDB_URL
    assert session.requests[0]["params"] == {}  # no key sent


@pytest.mark.asyncio
async def test_mozilla_defaults_to_public_url_but_is_overridable():
    session = fake_session(200, {"location": {"lat": 5.0, "lng": 6.0}})
    backend = MozillaGeolocationBackend(session=session)
    assert backend.base_url == MOZILLA_MLS_URL

    custom = MozillaGeolocationBackend(session=session, base_url="https://my-ichnaea.example/v1/geolocate")
    result = await custom.resolve(AP)

    assert result == Coordinates(latitude=5.0, longitude=6.0, accuracy_m=None)
    assert session.requests[0]["url"] == "https://my-ichnaea.example/v1/geolocate"


@pytest.mark.asyncio
async def test_ichnaea_family_returns_none_on_missing_location():
    session = fake_session(200, {})
    assert await CombainGeolocationBackend(api_key="k", session=session).resolve(AP) is None


@pytest.mark.asyncio
async def test_ichnaea_family_returns_none_on_non_200():
    session = fake_session(403, {})
    assert await CombainGeolocationBackend(api_key="k", session=session).resolve(AP) is None
