import pytest

from _fakes import RaisingSession, fake_session
from wifi_geolocation_core.models import AccessPoint, Coordinates
from wifi_geolocation_core.wifidb import DEFAULT_ACCURACY_M, WifiDbGeolocationBackend

AP = [AccessPoint(bssid="0018560304f8", signal_strength_dbm=-65)]


@pytest.mark.asyncio
async def test_wifidb_resolves_from_matching_result():
    session = fake_session(200, [{"lat": "1.0", "long": "2.0", "LA": "2026-06-04 20:11:09.000"}])
    backend = WifiDbGeolocationBackend(session=session)

    result = await backend.resolve(AP)

    assert result == Coordinates(latitude=1.0, longitude=2.0, accuracy_m=DEFAULT_ACCURACY_M)


@pytest.mark.asyncio
async def test_wifidb_returns_none_when_no_results():
    session = fake_session(200, [])
    backend = WifiDbGeolocationBackend(session=session)

    assert await backend.resolve(AP) is None


@pytest.mark.asyncio
async def test_wifidb_returns_none_for_not_found_string_response():
    # "Not found" is a bare JSON string ("No AP's Found"), not an empty
    # array -- confirmed against the live API. Must not crash trying to
    # treat its characters as records.
    session = fake_session(200, "No AP's Found")
    backend = WifiDbGeolocationBackend(session=session)

    assert await backend.resolve(AP) is None


@pytest.mark.asyncio
async def test_wifidb_picks_most_recently_seen_record_among_duplicates():
    session = fake_session(
        200,
        [
            {"lat": "1.0", "long": "2.0", "LA": "2020-01-01 00:00:00.000"},
            {"lat": "9.0", "long": "9.0", "LA": "2026-06-04 20:11:09.000"},
            {"lat": "5.0", "long": "5.0", "LA": "2023-05-05 00:00:00.000"},
        ],
    )
    backend = WifiDbGeolocationBackend(session=session)

    result = await backend.resolve(AP)

    assert result == Coordinates(latitude=9.0, longitude=9.0, accuracy_m=DEFAULT_ACCURACY_M)


@pytest.mark.asyncio
async def test_wifidb_handles_explicit_null_la_without_crashing():
    # Some real WifiDB records carry "LA": null rather than omitting the
    # key entirely (confirmed against the live API) -- must not crash
    # when comparing against records that do have a real LA timestamp.
    session = fake_session(
        200,
        [
            {"lat": "1.0", "long": "2.0", "LA": None},
            {"lat": "9.0", "long": "9.0", "LA": "2026-06-04 20:11:09.000"},
        ],
    )
    backend = WifiDbGeolocationBackend(session=session)

    result = await backend.resolve(AP)

    assert result == Coordinates(latitude=9.0, longitude=9.0, accuracy_m=DEFAULT_ACCURACY_M)


@pytest.mark.asyncio
async def test_wifidb_429_triggers_cooldown_and_returns_none():
    session = fake_session(429, {"error": "rate limited"})
    backend = WifiDbGeolocationBackend(session=session)

    assert await backend.resolve(AP) is None
    assert backend._cooldown.active() is True


@pytest.mark.asyncio
async def test_wifidb_skips_lookup_entirely_while_in_cooldown():
    session = fake_session(429, {"error": "rate limited"})
    backend = WifiDbGeolocationBackend(session=session)

    await backend.resolve(AP)  # triggers the cooldown
    request_count_after_first_call = len(session.requests)

    result = await backend.resolve(AP)

    assert result is None
    assert len(session.requests) == request_count_after_first_call


@pytest.mark.asyncio
async def test_wifidb_timeout_on_one_ap_does_not_crash_resolve():
    # aiohttp.ClientTimeout(total=...) raises a bare TimeoutError, not an
    # aiohttp.ClientError subclass -- confirmed live against WifiDB's real
    # (single-maintainer, beta, no SLA) API. resolve() must survive it and
    # keep trying remaining access points instead of propagating.
    many_aps = [
        AccessPoint(bssid="0018560304f8", signal_strength_dbm=-65),
        AccessPoint(bssid="001122334455", signal_strength_dbm=-70),
    ]
    session = RaisingSession(TimeoutError())
    backend = WifiDbGeolocationBackend(session=session)

    result = await backend.resolve(many_aps)

    assert result is None
    assert len(session.requests) == 2  # kept going past the timeout


@pytest.mark.asyncio
async def test_wifidb_429_stops_trying_remaining_access_points():
    many_aps = [
        AccessPoint(bssid="0018560304f8", signal_strength_dbm=-65),
        AccessPoint(bssid="001122334455", signal_strength_dbm=-70),
    ]
    session = fake_session(429, {"error": "rate limited"})
    backend = WifiDbGeolocationBackend(session=session)

    await backend.resolve(many_aps)

    assert len(session.requests) == 1
