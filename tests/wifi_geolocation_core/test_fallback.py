import pytest

from wifi_geolocation_core.fallback import FallbackGeolocationBackend
from wifi_geolocation_core.models import AccessPoint, Coordinates

AP = [AccessPoint(bssid="0018560304f8", signal_strength_dbm=-70)]


class _FakeBackend:
    def __init__(self, result=None, raises=False):
        self._result = result
        self._raises = raises
        self.called = False

    async def resolve(self, access_points):
        self.called = True
        if self._raises:
            raise RuntimeError("backend blew up")
        return self._result


@pytest.mark.asyncio
async def test_returns_first_non_none_result():
    first = _FakeBackend(result=None)
    second = _FakeBackend(result=Coordinates(latitude=1.0, longitude=2.0))
    third = _FakeBackend(result=Coordinates(latitude=9.0, longitude=9.0))

    backend = FallbackGeolocationBackend(backends=(first, second, third))
    result = await backend.resolve(AP)

    assert result == Coordinates(latitude=1.0, longitude=2.0)
    assert first.called
    assert second.called
    assert not third.called  # stopped once second resolved


@pytest.mark.asyncio
async def test_skips_a_backend_that_raises():
    broken = _FakeBackend(raises=True)
    working = _FakeBackend(result=Coordinates(latitude=5.0, longitude=6.0))

    backend = FallbackGeolocationBackend(backends=(broken, working))
    result = await backend.resolve(AP)

    assert result == Coordinates(latitude=5.0, longitude=6.0)


@pytest.mark.asyncio
async def test_returns_none_if_all_backends_fail_or_are_empty():
    backend = FallbackGeolocationBackend(
        backends=(_FakeBackend(result=None), _FakeBackend(raises=True))
    )
    assert await backend.resolve(AP) is None
