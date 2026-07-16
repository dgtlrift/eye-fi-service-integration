# Eye-Fi Home Assistant Integration

A Home Assistant custom integration that acts as an Eye-Fi card upload
server — running natively inside HA's asyncio event loop — with full
preservation of the card's WiFi-based geotagging feature (EXIF GPS tags
written locally, since Eye-Fi's own cloud/Skyhook geolocation service is
long dead).

This is a clean-room implementation: no code is forked from prior Eye-Fi
servers. Their source was read only to document the wire protocol and
`.log` sidecar format (see [Credits](#credits)), then re-implemented
async-native for Python 3 / asyncio.

## Architecture

The codebase is split into two independent core/adapter pairs, so neither
the upload protocol nor geotagging logic is ever trapped inside Home
Assistant's process model:

```
eyefi_core/                     framework-agnostic, installable, zero HA imports
├── protocol.py                 SOAP XML envelopes, credential MD5, integrity digest
├── soap_server.py              aiohttp server: StartSession/GetPhotoStatus/UploadPhoto/MarkLastPhotoInRoll
├── tar_extract.py              untar + integrity verification, JPEG + .log sidecar extraction
├── geotag.py                   .log parsing, EXIF GPS write (piexif); GeolocationBackend Protocol only --
│                                  concrete backends live in wifi_geolocation_core, not here
├── events.py                   pub/sub interface (in-process now; WebSocket-backed later, same shape)
└── storage/                    pluggable backends behind one async interface
    ├── local_nas.py            default — filesystem write (local or pre-mounted remote NAS)
    ├── remote_nas.py           smbprotocol (SMB2/3) or asyncssh (SFTP), no mount required
    ├── apple_dropfolder.py     alias over local_nas/remote_nas — see docs/apple-ecosystem-setup.md
    ├── google_photos.py        appendonly scope — upload-only, no read-back/dedup
    ├── onedrive.py             Microsoft Graph API
    ├── smugmug.py              REST API v2, OAuth 1.0a
    ├── backblaze.py            B2 native API
    └── pcloud.py                REST API, OAuth2

custom_components/eyefi/        thin HA adapter — no protocol/geotag/storage logic here
├── config_flow.py              card mac/upload-key + destination config UI (no geolocation API key -- see below)
├── __init__.py                 starts eyefi_core embedded, calls wifi_geolocation.resolve if that
│                                  integration is loaded, bridges events onto hass.bus
└── camera.py                   optional camera entity showing the latest received photo

wifi_geolocation/                a second, independent core package (its own pyproject.toml,
│                                  installed from this repo's #subdirectory=wifi_geolocation)
└── wifi_geolocation_core/       zero HA imports; one GeolocationBackend Protocol, N backends
    ├── models.py                AccessPoint, Coordinates, GeolocationBackend, format_bssid
    ├── ichnaea_compatible.py     shared impl for the Google-shaped JSON API (Google/Combain/BeaconDB/Mozilla)
    ├── google.py, combain.py, beacondb.py, mozilla.py   thin wrappers around ichnaea_compatible.py
    ├── here.py                  HERE Positioning API (different request shape)
    ├── unwired_labs.py          Unwired Labs LocationAPI (different request/response shape)
    ├── wigle.py                 WiGLE community BSSID database (its own bespoke shape)
    └── fallback.py               tries multiple backends in priority order

custom_components/wifi_geolocation/   thin HA adapter around wifi_geolocation_core
├── config_flow.py              pick any of the 7 backends (boolean toggles) + their credentials
├── __init__.py                 builds the configured backend(s), registers the wifi_geolocation.resolve service
└── services.yaml
```

**Why a separate `wifi_geolocation` integration instead of eyefi holding its
own Google/WiGLE config:** eyefi's config flow never asks for a geolocation
API key at all. If `wifi_geolocation` is installed and configured, eyefi's
adapter calls its `wifi_geolocation.resolve` service (see
`custom_components/eyefi/__init__.py`'s `_ServiceBackedGeolocationBackend`)
to turn WiFi AP sightings into coordinates; if it isn't installed,
geotagging is silently skipped, exactly like eyefi_core already treats any
unresolvable location. The two integrations share no Python imports —
only the service's JSON request/response contract — so `wifi_geolocation`
could serve other consumers later without eyefi knowing or caring.

Both `eyefi_core` and `wifi_geolocation_core` run **embedded** (imported
directly by their respective `custom_components/.../__init__.py`) for v1 —
simplest, lowest latency. Their public APIs are plain dicts/dataclasses in
and out, with zero `homeassistant.*` imports, so `eyefi_core` can later run
as a standalone daemon (`eyefi_core/service.py`, not yet built) exposing
`/config` `/status` `/events` over HTTP+WebSocket — at which point a future
Homebridge/HOOBS plugin becomes a thin client of the same running service
instead of a reimplementation from a spec.

## How it works

1. The card connects over WiFi and POSTs SOAP XML to
   `/api/soap/eyefilm/v1` on port 59278 (hardcoded in card firmware):
   `StartSession` → `GetPhotoStatus` → `UploadPhoto` → `MarkLastPhotoInRoll`.
2. `UploadPhoto`'s multipart body carries a tar archive: the JPEG plus a
   sidecar `.log` file recording every WiFi AP the card saw around the
   moment the photo was taken, verified against an MD5 integrity digest
   before anything touches disk.
3. If the `wifi_geolocation` integration is installed and configured, the
   `.log` is parsed for AP sightings near the shot time, resolved to a
   lat/long via whichever backend(s) you enabled there, and written into
   the JPEG's EXIF `GPSLatitude`/`GPSLongitude` tags — asynchronously,
   after the photo is already safely received, so a slow/failed lookup
   never blocks delivery. If it's not installed, this step is skipped.
4. The photo is handed to whichever storage backend you configured
   (local/remote NAS, a shared folder for the Apple ecosystem, or one of
   the cloud destinations), wrapped in a spool/retry queue so a
   temporarily unreachable destination doesn't lose the upload.
5. Three events fire along the way — `eyefi_image_received`,
   `eyefi_image_geotagged`, `eyefi_image_stored` — both on eyefi_core's
   internal pub/sub bus and (via the adapter) on `hass.bus`, so automations
   can react at any stage.

## Installation

Neither `eyefi_core` nor `wifi_geolocation_core` are on PyPI yet, so each
integration's `manifest.json` points its `requirements` entry at this repo
directly:

- `custom_components/eyefi/manifest.json` →
  `eyefi-core @ git+https://github.com/dgtlrift/eye-fi-service-integration.git@main`
- `custom_components/wifi_geolocation/manifest.json` →
  `wifi-geolocation-core @ git+https://github.com/dgtlrift/eye-fi-service-integration.git@main#subdirectory=wifi_geolocation`

Once published to PyPI, those `requirements` entries should point there
instead.

1. Copy `custom_components/eyefi/` into your HA config's
   `custom_components/` directory. If you want geotagging, also copy
   `custom_components/wifi_geolocation/` there.
2. Restart Home Assistant so it installs each integration's Python package
   via its manifest's `requirements`.
3. **(Optional, do this first if you want geotagging)** Settings → Devices
   & Services → **Add Integration** → **WiFi Geolocation** → enable
   whichever backend(s) you want and enter their credentials (see
   [Geotagging](#geotagging) below).
4. Settings → Devices & Services → **Add Integration** → **Eye-Fi**.
5. Enter the card's MAC address and upload key (found in Eye-Fi Manager's
   `Settings.xml`, or on the card packaging), a local download/spool
   directory, and pick a storage destination. There's no geolocation API
   key to enter here — eyefi automatically uses WiFi Geolocation if it's
   installed.
6. To add more cards later, open the Eye-Fi integration's **Configure**
   button — the options flow lets you add further mac/upload-key pairs to
   the same entry.

### Storage destinations

| Destination | Notes |
|---|---|
| `local_nas` (default) | Filesystem write — local disk or an SMB/NFS mount |
| `remote_nas` | SMB2/3 (`smbprotocol`) or SFTP (`asyncssh`) — no OS-level mount needed |
| `apple_dropfolder` | Writes to a shared folder; see [docs/apple-ecosystem-setup.md](docs/apple-ecosystem-setup.md) for the Mac Folder Action / iOS Shortcuts side |
| `google_photos` | `photoslibrary.appendonly` scope — upload-only since Google's March 2025 API changes |
| `onedrive` | Microsoft Graph API |
| `smugmug` | REST API v2, OAuth 1.0a |
| `backblaze` | B2 native API |
| `pcloud` | REST API, OAuth2 |

OAuth-based destinations currently expect a pre-obtained access token
pasted into the config flow rather than a full in-app OAuth2 redirect —
a reasonable v1 scope; HA's `application_credentials`/
`config_entry_oauth2_flow` helpers would be the natural next step for a
proper in-app authorization flow.

### Geotagging

Geotagging is handled entirely by the separate **WiFi Geolocation**
integration (`custom_components/wifi_geolocation`) — install it if you
want GPS coordinates resolved from the card's WiFi scan, skip it if you
don't. Its config flow lets you enable and order backends: normally a
draggable chip list (HA's frontend has supported this for the `select`
selector since 2023, but the Python-side schema never exposed it — see
`_selector_patch.py`'s docstring for the full story and the reason a
runtime patch is applied for it), falling back to one plain priority
number per backend (0 = disabled, 1+ = priority, lower tried first) if
that patch can't apply for any reason. Either way, they're tried in that
order at runtime, stopping at the first one that resolves a location.
Change it any time via the integration's **Configure** button —
reordering or adding/removing backends there doesn't require removing
and re-adding the integration.

| Backend | Notes |
|---|---|
| **BeaconDB** | Free, open, community-run — no account needed. |
| **Mozilla Location Service** | Ichnaea-compatible. Mozilla's own public instance was shut down in 2024 — only useful pointed at a self-hosted Ichnaea instance; the base URL is configurable. |
| **Google Geolocation API** | Needs an API key, paid past the free tier. |
| **HERE Technologies Positioning API** | Needs an API key. |
| **Combain Positioning API** | Needs an API key. |
| **Unwired Labs LocationAPI** | Needs an API token; region-specific base URL (us1/eu1/...). |
| **WiGLE** | Free-tier BSSID lookups against a community-sourced war-driving database; needs an API name/token pair. |

Any other integration (not just eyefi) can resolve WiFi APs to coordinates
the same way, by calling the `wifi_geolocation.resolve` service with a
list of `{bssid, signal_strength_dbm}` readings — see
`custom_components/wifi_geolocation/services.yaml`.

## Development

```console
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pip install -e ./wifi_geolocation
pytest
```

Both `eyefi_core` and `wifi_geolocation_core` are fully testable standalone,
without a running HA instance. `custom_components/eyefi` and
`custom_components/wifi_geolocation` aren't covered end-to-end (that needs
the `homeassistant` package and a running HA core to exercise
meaningfully), but their config-flow schemas *are* tested — see
`tests/custom_components/`, which runs every schema through the real
`voluptuous_serialize.convert()` HA's frontend uses, without needing
`homeassistant` installed. This exists because of a real bug: a schema
validator that `voluptuous_serialize` can't handle causes a 500 error on
every "Add Integration" attempt, and that failure mode is invisible to
`py_compile` or a plain unit test — it only shows up against a real HA
instance otherwise.

## Credits

Read-only reference material used to document the wire protocol and
`.log` sidecar format — no code copied verbatim, and none of these were
forked:

- [`tachang/EyeFiServer`](https://github.com/tachang/EyeFiServer) — the
  original documented protocol (SOAP envelopes, credential flow); see
  `Documentation/EyeFi Protocol.txt`.
- [`dgrant/eyefiserver2`](https://github.com/dgrant/eyefiserver2) — Python
  fork with geotagging already implemented; primary source for the `.log`
  format and Google Geolocation API usage.
- [`usefulthink/node-eyefi`](https://github.com/usefulthink/node-eyefi) —
  JS protocol implementation, initial reference.
- [`ryantm/heyefi`](https://github.com/ryantm/heyefi) — Haskell, archived;
  config schema (mac address + upload key per card) reference only.

## License

MIT, for `eyefi_core`, `wifi_geolocation_core`, and both HA adapters — see
[LICENSE](LICENSE).
