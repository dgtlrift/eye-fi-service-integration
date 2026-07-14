"""Constants for the Eye-Fi HA adapter.

Everything here is HA-facing config-entry shape only. eyefi_core never
sees these names — the adapter translates config-entry data into the
plain dicts eyefi_core's public API expects.
"""

DOMAIN = "eyefi"

CONF_CARDS = "cards"  # list[{mac, upload_key}]
CONF_MAC = "mac"
CONF_UPLOAD_KEY = "upload_key"
CONF_DOWNLOAD_DIR = "download_dir"
CONF_DESTINATION = "destination"
CONF_DESTINATION_CONFIG = "destination_config"
CONF_PORT = "port"

DEFAULT_PORT = 59278
DEFAULT_DOWNLOAD_DIR = "/config/eyefi_downloads"
DEFAULT_LOCAL_STORAGE_SUBDIR = "photos"

DESTINATION_LOCAL_NAS = "local_nas"
DESTINATION_REMOTE_NAS = "remote_nas"
DESTINATION_APPLE_DROPFOLDER = "apple_dropfolder"
DESTINATION_GOOGLE_PHOTOS = "google_photos"
DESTINATION_ONEDRIVE = "onedrive"
DESTINATION_SMUGMUG = "smugmug"
DESTINATION_BACKBLAZE = "backblaze"
DESTINATION_PCLOUD = "pcloud"

DESTINATIONS = [
    DESTINATION_LOCAL_NAS,
    DESTINATION_REMOTE_NAS,
    DESTINATION_APPLE_DROPFOLDER,
    DESTINATION_GOOGLE_PHOTOS,
    DESTINATION_ONEDRIVE,
    DESTINATION_SMUGMUG,
    DESTINATION_BACKBLAZE,
    DESTINATION_PCLOUD,
]

EVENT_IMAGE_RECEIVED = "eyefi_image_received"
EVENT_IMAGE_GEOTAGGED = "eyefi_image_geotagged"
EVENT_IMAGE_STORED = "eyefi_image_stored"

SIGNAL_NEW_IMAGE = f"{DOMAIN}_new_image"

# Optional sibling integration: if loaded, its "resolve" service is used
# for geotagging. If not installed/loaded, geotagging is silently skipped
# -- eyefi never holds a geolocation API key itself. See
# custom_components/wifi_geolocation/.
WIFI_GEOLOCATION_DOMAIN = "wifi_geolocation"
WIFI_GEOLOCATION_SERVICE_RESOLVE = "resolve"
