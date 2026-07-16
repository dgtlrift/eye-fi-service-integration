"""Constants for the WiFi Geolocation HA integration."""

DOMAIN = "wifi_geolocation"

BACKEND_GOOGLE = "google"
BACKEND_WIGLE = "wigle"
BACKEND_COMBAIN = "combain"
BACKEND_HERE = "here"
BACKEND_UNWIRED_LABS = "unwired_labs"
BACKEND_BEACONDB = "beacondb"
BACKEND_MOZILLA = "mozilla"

# Canonical listing order (free/open services first, then paid ones, then
# WiGLE) -- only used to break ties when two backends are given the same
# priority number in the config flow, and to order the priority-field form.
# Not an enforced fallback order; the user's own priority numbers are.
BACKEND_PRIORITY_ORDER = [
    BACKEND_BEACONDB,
    BACKEND_MOZILLA,
    BACKEND_GOOGLE,
    BACKEND_HERE,
    BACKEND_COMBAIN,
    BACKEND_UNWIRED_LABS,
    BACKEND_WIGLE,
]

BACKEND_LABELS = {
    BACKEND_GOOGLE: "Google Geolocation API",
    BACKEND_WIGLE: "WiGLE",
    BACKEND_COMBAIN: "Combain Positioning API",
    BACKEND_HERE: "HERE Technologies Positioning API",
    BACKEND_UNWIRED_LABS: "Unwired Labs LocationAPI",
    BACKEND_BEACONDB: "BeaconDB (free, no account needed)",
    BACKEND_MOZILLA: "Mozilla Location Service / self-hosted Ichnaea",
}

CONF_BACKENDS = "backends"  # stored in the config entry: list[str], in priority order
CONF_PRIORITY_PREFIX = "priority_"  # form field per backend; 0 = disabled

CONF_GOOGLE_API_KEY = "google_api_key"
CONF_WIGLE_API_NAME = "wigle_api_name"
CONF_WIGLE_API_TOKEN = "wigle_api_token"
CONF_COMBAIN_API_KEY = "combain_api_key"
CONF_HERE_API_KEY = "here_api_key"
CONF_UNWIRED_LABS_API_KEY = "unwired_labs_api_key"
CONF_UNWIRED_LABS_BASE_URL = "unwired_labs_base_url"
CONF_MOZILLA_API_KEY = "mozilla_api_key"
CONF_MOZILLA_BASE_URL = "mozilla_base_url"

SERVICE_RESOLVE = "resolve"
