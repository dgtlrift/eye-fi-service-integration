import pytest

from _fakes import fake_session
from wifi_geolocation_core.models import AccessPoint, Coordinates
from wifi_geolocation_core.unwired_labs import (
    UNWIRED_LABS_DEFAULT_URL,
    UnwiredLabsGeolocationBackend,
)

AP = [AccessPoint(bssid="0018560304f8", signal_strength_dbm=-65)]


@pytest.mark.asyncio
async def test_unwired_labs_sends_token_in_body_and_wifi_bssid_signal_shape():
    session = fake_session(200, {"status": "ok", "lat": 1.0, "lon": 2.0, "accuracy": 20.0})
    backend = UnwiredLabsGeolocationBackend(api_key="tok", session=session)

    result = await backend.resolve(AP)

    assert result == Coordinates(latitude=1.0, longitude=2.0, accuracy_m=20.0)
    request = session.requests[0]
    assert request["url"] == UNWIRED_LABS_DEFAULT_URL
    assert request["json"] == {
        "token": "tok",
        "wifi": [{"bssid": "00:18:56:03:04:f8", "signal": -65}],
    }


@pytest.mark.asyncio
async def test_unwired_labs_respects_custom_base_url():
    session = fake_session(200, {"status": "ok", "lat": 1.0, "lon": 2.0})
    backend = UnwiredLabsGeolocationBackend(
        api_key="tok", session=session, base_url="https://eu1.unwiredlabs.com/v2/process.php"
    )
    await backend.resolve(AP)
    assert session.requests[0]["url"] == "https://eu1.unwiredlabs.com/v2/process.php"


@pytest.mark.asyncio
async def test_unwired_labs_returns_none_on_non_ok_status():
    session = fake_session(200, {"status": "error", "message": "bad token"})
    backend = UnwiredLabsGeolocationBackend(api_key="bad", session=session)
    assert await backend.resolve(AP) is None
