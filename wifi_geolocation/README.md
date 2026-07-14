# wifi-geolocation-core

Async, framework-agnostic WiFi-access-point-to-lat/long resolution behind
one normalized interface (`GeolocationBackend.resolve()`), with pluggable
backends:

- `google.py` — Google Geolocation API (paid past the free tier).
- `wigle.py` — WiGLE's free-tier, community-sourced BSSID database.
- `fallback.py` — tries multiple backends in priority order, returning the
  first one that resolves.

This package has no Home Assistant dependency. It's consumed by
`custom_components/wifi_geolocation` (a thin HA integration exposing a
`wifi_geolocation.resolve` service), which is how the sibling `eyefi`
integration resolves coordinates without ever holding a Google/WiGLE API
key itself — see the root [README](../README.md) for the full
architecture.

MIT licensed — see the repo root [LICENSE](../LICENSE).
