"""Constants for the WiFi Geolocation HA integration."""

DOMAIN = "wifi_geolocation"

BACKEND_GOOGLE = "google"
BACKEND_WIGLE = "wigle"
BACKEND_COMBAIN = "combain"
BACKEND_HERE = "here"
BACKEND_UNWIRED_LABS = "unwired_labs"
BACKEND_BEACONDB = "beacondb"
BACKEND_MOZILLA = "mozilla"

# Default/suggested listing order for the config flow's backend selector
# (free/open services first, then paid ones, then WiGLE) -- shown for
# unselected options. The user's own selection *order* is what actually
# controls priority at runtime (see wifi_geolocation/__init__.py's
# _build_backend); this is not an enforced fallback order.
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
