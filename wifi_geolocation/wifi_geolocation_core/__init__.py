"""wifi_geolocation_core: async, framework-agnostic WiFi-AP-to-lat/long
resolution behind one normalized interface.

Consumers (e.g. the eyefi integration's geotagging step) depend only on
the ``GeolocationBackend`` Protocol's shape, never on which concrete
backend (Google Geolocation API, WiGLE, a future SkyHook backend, ...) is
actually configured or which API key it needs.
"""

__version__ = "0.1.0"
