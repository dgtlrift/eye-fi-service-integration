from wifi_geolocation_core.models import format_bssid


def test_format_bssid_inserts_colons():
    assert format_bssid("0018560304f8") == "00:18:56:03:04:f8"
