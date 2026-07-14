import pytest

from _fakes import fake_session
from wifi_geolocation_core.here import HERE_POSITIONING_URL, HereGeolocationBackend
from wifi_geolocation_core.models import AccessPoint, Coordinates

AP = [AccessPoint(bssid="0018560304f8", signal_strength_dbm=-65)]


@pytest.mark.asyncio
async def test_here_sends_wlan_mac_rss_shape_and_api_key():
    session = fake_session(200, {"location": {"lat": 1.0, "lng": 2.0, "accuracy": 15.0}})
    backend = HereGeolocationBackend(api_key="k", session=session)

    result = await backend.resolve(AP)

    assert result == Coordinates(latitude=1.0, longitude=2.0, accuracy_m=15.0)
    request = session.requests[0]
    assert request["url"] == HERE_POSITIONING_URL
    assert request["params"] == {"apiKey": "k"}
    assert request["json"] == {"wlan": [{"mac": "0018560304F8", "rss": -65}]}


@pytest.mark.asyncio
async def test_here_returns_none_on_missing_location():
    session = fake_session(200, {})
    backend = HereGeolocationBackend(api_key="k", session=session)
    assert await backend.resolve(AP) is None


@pytest.mark.asyncio
async def test_here_returns_none_on_non_200():
    session = fake_session(500, {})
    backend = HereGeolocationBackend(api_key="k", session=session)
    assert await backend.resolve(AP) is None
