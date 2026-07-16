from wifi_geolocation_core import cooldown as cooldown_module
from wifi_geolocation_core.cooldown import RateLimitCooldown


def test_not_active_until_triggered():
    c = RateLimitCooldown(duration_seconds=60)
    assert c.active() is False
    assert c.remaining_seconds() == 0.0


def test_active_immediately_after_trigger():
    c = RateLimitCooldown(duration_seconds=60)
    c.trigger()
    assert c.active() is True
    assert 0 < c.remaining_seconds() <= 60


def test_expires_after_duration(monkeypatch):
    fake_time = {"now": 1000.0}
    monkeypatch.setattr(cooldown_module.time, "monotonic", lambda: fake_time["now"])

    c = RateLimitCooldown(duration_seconds=60)
    c.trigger()
    assert c.active() is True

    fake_time["now"] += 61
    assert c.active() is False
    assert c.remaining_seconds() == 0.0


def test_retrigger_extends_cooldown(monkeypatch):
    fake_time = {"now": 1000.0}
    monkeypatch.setattr(cooldown_module.time, "monotonic", lambda: fake_time["now"])

    c = RateLimitCooldown(duration_seconds=60)
    c.trigger()
    fake_time["now"] += 59
    assert c.active() is True

    c.trigger()  # a fresh 429 while still in cooldown resets the clock
    fake_time["now"] += 59
    assert c.active() is True
