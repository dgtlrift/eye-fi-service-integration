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

The codebase is split in two so the protocol/geotag/storage logic is never
trapped inside Home Assistant's process model:

```
eyefi_core/                     framework-agnostic, installable, zero HA imports
├── protocol.py                 SOAP XML envelopes, credential MD5, integrity digest
├── soap_server.py              aiohttp server: StartSession/GetPhotoStatus/UploadPhoto/MarkLastPhotoInRoll
├── tar_extract.py              untar + integrity verification, JPEG + .log sidecar extraction
├── geotag.py                   .log parsing, Google/WiGLE geolocation, EXIF GPS write (piexif)
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
├── config_flow.py              card mac/upload-key + destination + geotag config UI
├── __init__.py                 starts eyefi_core embedded, bridges its events onto hass.bus
└── camera.py                   optional camera entity showing the latest received photo
```

`eyefi_core` runs **embedded** (imported directly by
`custom_components/eyefi/__init__.py`) for v1 — simplest, lowest latency.
Its public API is plain dicts/dataclasses in and out, with zero
`homeassistant.*` imports, so the same package can later run as a
standalone daemon (`eyefi_core/service.py`, not yet built) exposing
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
3. If a geotagging backend is configured, the `.log` is parsed for AP
   sightings near the shot time, resolved to a lat/long via Google's
   Geolocation API or WiGLE's community BSSID database, and written into
   the JPEG's EXIF `GPSLatitude`/`GPSLongitude` tags — asynchronously,
   after the photo is already safely received, so a slow/failed lookup
   never blocks delivery.
4. The photo is handed to whichever storage backend you configured
   (local/remote NAS, a shared folder for the Apple ecosystem, or one of
   the cloud destinations), wrapped in a spool/retry queue so a
   temporarily unreachable destination doesn't lose the upload.
5. Three events fire along the way — `eyefi_image_received`,
   `eyefi_image_geotagged`, `eyefi_image_stored` — both on eyefi_core's
   internal pub/sub bus and (via the adapter) on `hass.bus`, so automations
   can react at any stage.

## Installation

`eyefi_core` isn't on PyPI yet, so `custom_components/eyefi/manifest.json`
points its `requirements` entry at this repo directly
(`eyefi-core @ git+https://github.com/dgtlrift/eye-fi-service-integration.git@main`).
Once published to PyPI, that `requirements` entry should point there
instead.

1. Copy `custom_components/eyefi/` into your HA config's
   `custom_components/` directory.
2. Restart Home Assistant so it installs `eyefi_core` via the manifest's
   `requirements`.
3. Settings → Devices & Services → **Add Integration** → **Eye-Fi**.
4. Enter the card's MAC address and upload key (found in Eye-Fi Manager's
   `Settings.xml`, or on the card packaging), a local download/spool
   directory, and pick a storage destination.
5. To add more cards later, open the integration's **Configure** button —
   the options flow lets you add further mac/upload-key pairs to the same
   entry.

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

Pick `google` or `wigle` as the geotag backend during setup (or `none` to
skip it):

- **Google Geolocation API** — needs an API key, paid past the free tier.
- **WiGLE** — free-tier BSSID lookups against a community-sourced
  war-driving database; needs a WiGLE API name/token pair.

## Development

```console
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

`eyefi_core` is fully testable standalone, without a running HA instance —
`custom_components/eyefi` is not covered by the test suite here since it
requires the `homeassistant` package and a running HA core to exercise
meaningfully.

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

MIT, for both `eyefi_core` and the `custom_components/eyefi` adapter — see
[LICENSE](LICENSE).
