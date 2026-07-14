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
CONF_GEOTAG_BACKEND = "geotag_backend"
CONF_GEOTAG_CONFIG = "geotag_config"
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

GEOTAG_BACKEND_NONE = "none"
GEOTAG_BACKEND_GOOGLE = "google"
GEOTAG_BACKEND_WIGLE = "wigle"

GEOTAG_BACKENDS = [GEOTAG_BACKEND_NONE, GEOTAG_BACKEND_GOOGLE, GEOTAG_BACKEND_WIGLE]

EVENT_IMAGE_RECEIVED = "eyefi_image_received"
EVENT_IMAGE_GEOTAGGED = "eyefi_image_geotagged"
EVENT_IMAGE_STORED = "eyefi_image_stored"

SIGNAL_NEW_IMAGE = f"{DOMAIN}_new_image"
