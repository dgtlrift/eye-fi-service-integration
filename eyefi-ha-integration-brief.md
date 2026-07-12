# Project Brief: Eye-Fi Home Assistant Integration

## Goal

Build a standalone Home Assistant custom integration that acts as an Eye-Fi
card upload server, running natively inside HA's asyncio event loop, with
full preservation of the card's WiFi-based geotagging feature (EXIF GPS
tags written locally instead of relying on Eye-Fi's now-defunct cloud
service).

**This project is independent of any other infrastructure project** (e.g.
edge-computing / industrial deployments) — no shared code, config, or
architecture assumptions with those. Treat this as a clean, standalone repo.

## Non-goals / explicit decisions already made

- **Do not fork** `dgrant/eyefiserver2`, `tachang/EyeFiServer`, or
  `ryantm/heyefi` on GitHub. This is a new, clean-room repository with its
  own license (MIT) and commit history.
- `node-eyefi` (Node.js), `dgrant/eyefiserver2` (Python 2), and
  `tachang/EyeFiServer` (Python 2) are **reference material only** — read
  their protocol-handling logic to understand the wire format, but do not
  adapt their runtime/threading model. All of them use blocking
  request-per-thread servers; this integration must be async-native to run
  inside HA's event loop.
- `ryantm/heyefi` (Haskell, archived 2020) offers no portable code — useful
  only as a secondary reference for the config schema (mac address +
  upload key per card).
- Credit these projects in the README as protocol references. Check
  license terms before copying any literal code (e.g. XML templates)
  verbatim; when in doubt, re-derive from documented behavior instead of
  copying.

## Why a custom implementation, not a wrapped dependency

Home Assistant integrations are Python 3 / asyncio. None of the prior art
fits that runtime:
- `node-eyefi`: wrong language entirely.
- `eyefiserver2` / `EyeFiServer`: Python 2, `BaseHTTPServer`/`SocketServer`
  with blocking threads — incompatible with HA's event loop, and Python 2
  stdlib modules used (`xml.sax`, etc.) don't exist in HA's Python 3
  runtime.
- `heyefi`: Haskell daemon requiring root.

## Modular architecture for cross-platform reuse (HOOBS/Homebridge later)

Decision: proceed with Home Assistant as the primary target, but structure
the codebase so the protocol/geotag/storage logic is **not trapped inside
HA's process model** — a future Homebridge/HOOBS plugin (Node.js) should
be able to consume the same running logic rather than requiring a full
reimplementation from a spec.

**Two-tier split:**

1. **`eyefi_core`** — a standalone, installable Python package with **zero
   `homeassistant.*` imports**. Contains everything platform-agnostic: the
   SOAP server, tar/log extraction, geotagging pipeline, and all storage
   backends. This is the actual product; the HA integration is a thin
   shell around it.
2. **`custom_components/eyefi/`** — a thin HA adapter. Its only jobs:
   surface HA's config flow UI (writing config that `eyefi_core`
   consumes), start/stop `eyefi_core`, and translate `eyefi_core`'s
   events into HA constructs (camera entity updates, `hass.bus` events).
   It should contain no protocol, geotag, or storage logic itself.

**Two run modes for `eyefi_core`, same code either way:**
- **Embedded mode (build this first)** — `eyefi_core` runs in-process
  inside HA's event loop, imported directly by
  `custom_components/eyefi/__init__.py`. Simplest, lowest latency, no
  extra moving parts — right choice for v1.
- **Standalone daemon mode (the actual cross-platform reuse path)** — the
  same `eyefi_core` package run as its own process (systemd unit or
  container), exposing a small local HTTP + WebSocket API (`/config`,
  `/status`, `/events` for `eyefi_image_received` /
  `eyefi_image_geotagged` / `eyefi_image_stored`). In this mode, the HA
  integration becomes a thin **network client** of the daemon instead of
  an in-process importer — and a future Homebridge/HOOBS plugin (a small
  Node.js HTTP/WebSocket client that maps daemon events onto a HomeKit
  Accessory) could consume the exact same running service, with zero
  protocol/geotag/storage code duplicated in Node. This is what makes the
  architecture genuinely reusable across ecosystems, not just
  spec-compatible.

**To make the switch between the two modes a config toggle rather than a
rewrite, from day one:**
- Define `eyefi_core`'s internal event dispatch as an abstract pub/sub
  interface (`events.py`), with an in-process implementation now (plain
  asyncio callbacks/queue) and a WebSocket-backed implementation added
  later — both satisfying the same interface.
- Keep `eyefi_core` entirely free of HA types in its public API (plain
  dicts/dataclasses in, plain dicts/dataclasses or JSON out) so it never
  needs to know which adapter is consuming it.
- License `eyefi_core` separately (MIT) as a package that could be
  published to PyPI independently of the HA integration, so a future
  Homebridge plugin's README can point at it as a runtime dependency
  rather than a thing to reimplement.

## Core protocol (from card to server)

- Card connects via WiFi, opens TCP to the server on **port 59278**
  (hardcoded in card firmware — not configurable).
- POSTs SOAP XML to `/api/soap/eyefilm/v1` with a `SoapAction` header, in
  sequence:
  1. `StartSession` — card sends `macaddress`, `cnonce`, `transfermode`;
     server responds with a `credential` challenge nonce.
  2. `GetPhotoStatus` — authenticates via MD5 hash of
     `macaddress + cnonce + uploadKey` (exact concatenation order/encoding
     needs verification against `eyefiserver2` source — this is the most
     common bug point in prior implementations); also carries filename,
     filesize, filesignature for dedup.
  3. `UploadPhoto` — multipart POST containing a **tar archive**: the JPEG
     plus a sidecar `.log` file (see Geotagging below), plus a trailing
     integrity digest. The multipart boundary handling is not fully
     RFC-compliant — `aiohttp`'s built-in multipart reader may need manual
     boundary parsing.
  4. `MarkLastPhotoInRoll` — end-of-batch marker.
- Server must untar the payload, strip the trailing digest bytes, and
  write out the image (and log) files.

## Geotagging preservation (the key feature to keep working)

- The card scans nearby WiFi networks at the moment each photo is taken
  and writes the results into a **`.log` file sharing the image's base
  filename** (e.g. `IMG_1234.JPG` + `IMG_1234.log`), bundled in the same
  tar archive uploaded during `UploadPhoto`.
- Prior servers (`eyefiserver2`, `EyeFiServer`) parse this log into a
  BSSID/signal-strength list and resolve it to a lat/long via an external
  WiFi-positioning API (originally Skyhook via Eye-Fi's cloud; self-hosted
  forks used Google's Geolocation API). **Pull the exact `.log` field
  format from `eyefiserver2`'s source** — don't guess it.
- Since Eye-Fi's own cloud/Skyhook integration is dead, resolve locally:
  - **Google Geolocation API** — simplest, POST
    `wifiAccessPoints: [{macAddress, signalStrength}]`, needs an API key
    (paid past free tier). This is what existing forks already use.
  - **WiGLE API** — free-tier BSSID lookups, community-sourced DB, no
    Google dependency. Reasonable fallback/alternative.
- Write resolved coordinates into the JPEG's EXIF (`GPSLatitude`,
  `GPSLongitude`, `GPSLatitudeRef`, `GPSLongitudeRef`) using **`piexif`**
  (pure Python, async-friendly, no `exiftool` subprocess dependency).
- Do the resolve + EXIF-write as an async step after image write
  completes, so a slow/failed geolocation call never blocks photo
  delivery. Consider firing two distinct HA events: `eyefi_image_received`
  (immediately) and `eyefi_image_geotagged` (once EXIF write finishes), so
  automations can react at either stage.

## Storage & upload destinations

Once an image is imported and geotagged, it should be stored to a local
NAS by default, or — by user choice in config — routed to one of several
alternate destinations. This needs a **pluggable backend** design (one
interface, multiple implementations), selected/configured per card or
globally via the config flow.

**Local / remote NAS**
- Local NAS: simplest — treat as a mounted filesystem path (SMB/NFS
  mounted at the OS level outside HA's concern); integration just writes
  files there.
- Remote NAS without a pre-existing mount: use `smbprotocol` (pure-Python
  SMB2/3 client, async-friendly) or SFTP via `asyncssh` if the NAS exposes
  SSH. Avoid shelling out to `smbclient`/`rsync` if possible, to keep
  everything inside the asyncio runtime.

**Cloud destinations — feasibility varies significantly, confirm before building:**
- **Google Photos** — usable, but scope-limited since Google's March 2025
  API changes: the `photoslibrary.appendonly` scope still allows uploading
  new media items and creating albums, but apps can no longer read back or
  manage the full library — only content the app itself created. Fine for
  a one-way "upload and forget" use case; not usable for anything requiring
  read-back/dedup checks against the existing library.
- **Apple ecosystem (iCloud Photos)** — no official public API for
  uploads exists, so this destination does **not** push directly to
  Apple's cloud. Instead, the integration writes to a plain shared drop
  folder (reusing the `local_nas`/`remote_nas` backend), and a companion
  Apple-native automation — running on hardware the user already owns —
  pulls new files into Photos, from which iCloud Photos syncs them
  normally. Two documented paths, chosen based on what hardware the user
  has (see dedicated section below):
  1. **Mac present**: event-driven **Folder Action** + Photos AppleScript
     import (preferred — real-time, no polling).
  2. **iOS/iPadOS only, no Mac**: scheduled **Shortcuts personal
     automation** polling the drop folder and running "Save to Photo
     Album."
  Do not implement `pyicloud` or any reverse-engineered iCloud client —
  it's unnecessary given the drop-folder approach and carries needless
  ToS/session risk.
- **Microsoft OneDrive** — solid, official: Microsoft Graph API, OAuth2,
  standard file upload / upload-session for larger files.
- **SmugMug** — solid, official: REST API v2, OAuth 1.0a, documented image
  upload endpoint.
- **Backblaze (B2)** — solid, official: B2 native API or S3-compatible
  API, application-key auth, straightforward async HTTP upload.
- **pCloud** — solid, official: REST API, OAuth2, straightforward upload
  endpoint.

**Design implications**
- Add a `destination` config option per card (or global default +
  per-card override): `local_nas` (default), `remote_nas`, `google_photos`,
  `apple_dropfolder` (Mac Folder Action or iOS Shortcuts, documented for
  the user — see dedicated section below), `onedrive`, `smugmug`,
  `backblaze`, `pcloud`.
- Each backend implements a common async interface, e.g.
  `async def store(image_path, metadata) -> None`, defined in
  `eyefi_core/storage/__init__.py` so adding/removing a destination
  doesn't touch the core upload/geotagging pipeline, and doesn't touch HA
  at all.
- OAuth-based destinations (Google Photos, OneDrive, SmugMug, pCloud) need
  their own config-flow steps for auth — likely a second config-flow
  "step" after the card mac/upload-key step, only shown if that
  destination is selected.
- Decide up front whether storage is **fire-and-forget** (best effort,
  logged on failure) or needs a **retry/queue** mechanism for destinations
  that are temporarily unreachable (e.g. NAS offline, cloud API rate
  limit) — recommend a simple local retry queue (SQLite or a flat spool
  directory) so failed uploads aren't lost.

## Apple ecosystem delivery (drop folder + on-device automation)

Since no official API can push into iCloud Photos, this destination is
really **"write to a shared folder"** (the existing `local_nas`/
`remote_nas` backend, just pointed at a folder the user's Apple device(s)
can also reach) **plus end-user documentation** for one of two Apple-side
automations that pull new files into Photos. The integration itself only
needs to know about the drop folder — it has no visibility into which
automation the user picked. Document both paths clearly in the project
README/docs so the user can pick the one matching their hardware.

### Path 1 — Mac present (preferred, event-driven, no polling)

User-facing setup doc should cover:
1. Share/mount the same drop folder on the Mac (SMB from the NAS, or a
   local folder if the drop target *is* the Mac).
2. Open **Folder Actions Setup** (via Finder → right-click the folder →
   "Folder Actions Setup," or `Automator`), attach a new Folder Action
   script to the drop folder.
3. Script body imports new files into Photos, e.g.:
   ```applescript
   on adding folder items to thisFolder after receiving addedItems
     tell application "Photos"
       repeat with anItem in addedItems
         import anItem skip check duplicates yes
       end repeat
     end tell
   end adding folder items to
   ```
4. Note for the user: the Mac must be powered on and logged in (folder
   actions don't run against a sleeping/logged-out Mac) for this to fire;
   otherwise it catches up next time the Mac wakes and Finder notices the
   folder changed.
5. Once imported into Photos, the user's existing iCloud Photos sync
   (System Settings → Apple ID → iCloud → Photos, already enabled on most
   setups) takes over automatically — no further integration work needed.

### Path 2 — iOS/iPadOS only, no Mac (fallback, polling-based)

User-facing setup doc should cover:
1. Add the drop folder as a Files app location: Files → "⋯" → Connect to
   Server (WebDAV) or, if it's the same NAS, via the existing SMB support
   in Files.
2. In Shortcuts app → Automation tab → "+" → **Create Personal
   Automation** → choose **Time of Day**, repeating (e.g. every 15–30
   min — this is polling, not event-driven, so set expectations
   accordingly).
3. Add actions: "Get Contents of Folder" (the Files location) → filter to
   items not already processed (track via a "last run" marker file or by
   date, since Shortcuts has no built-in de-dup) → **"Save to Photo
   Album."**
4. In Shortcuts app settings, disable **"Ask Before Running"** for this
   automation so it executes silently instead of prompting each time.
5. Document the caveats plainly for the user: this only runs while the
   device is reachable/awake often enough to hit the schedule, there's
   inherent lag vs. the Mac path, and de-duplication is the user's
   responsibility to configure (a naive setup will re-save the same
   photos on every run unless filtered).

### Storage backend implication

- No `icloud.py` backend needed. The `apple_dropfolder` destination
  option in config flow is effectively an alias that points at the same
  `eyefi_core/storage/local_nas.py`/`remote_nas.py` write logic, with the
  HA config-flow UI showing the user a link to the setup docs for
  whichever path matches their hardware.

## Integration architecture

- **Cannot use HA's built-in HTTP component** (binds to 8123, not suited to
  raw multipart/SOAP). `eyefi_core`'s SOAP server binds its own
  `aiohttp.web.Application` to port 59278; in embedded mode this is
  started/stopped from `async_setup_entry` alongside HA's own event loop,
  same as before — the only change is that this logic now lives in
  `eyefi_core`, not in `custom_components/eyefi/`.
- **Config flow** (`config_flow.py`): mac address + upload key per card,
  supporting multiple cards (dict keyed by mac, mirroring the shape used
  by prior servers), stored in the config entry, and handed to
  `eyefi_core` as plain config — the adapter doesn't interpret it further.
- **Entity/output side**: either
  - a `camera` entity (`Camera.async_camera_image()`) surfacing the most
    recent photo, and/or
  - `hass.bus.async_fire(...)` events, letting automations route images to
    notify/media_player/etc.
  - Both are just subscribers to `eyefi_core`'s `events.py` pub/sub —
    decide based on preference; event-only is more flexible, a camera
    entity gives an immediate visual tile.

## Proposed file layout

```
eyefi-project/                      # repo root
├── eyefi_core/                     # framework-agnostic, installable (MIT), zero HA imports
│   ├── __init__.py
│   ├── soap_server.py              # SOAP request handlers (StartSession, GetPhotoStatus,
│   │                                #   UploadPhoto, MarkLastPhotoInRoll)
│   ├── protocol.py                 # credential MD5 logic, XML envelope templates
│   ├── tar_extract.py              # tar unpacking, digest stripping, .log sidecar handling
│   ├── geotag.py                   # .log parsing, BSSID resolution (Google/WiGLE), EXIF write
│   ├── events.py                   # abstract pub/sub interface: in-process now,
│   │                                #   WebSocket-backed later, same public shape
│   ├── service.py                  # optional standalone-daemon entrypoint (systemd-runnable),
│   │                                #   exposes /config, /status, /events over HTTP+WebSocket
│   └── storage/
│       ├── __init__.py             # backend interface + dispatch by config
│       ├── local_nas.py            # filesystem write (local or pre-mounted remote NAS)
│       ├── remote_nas.py           # smbprotocol/asyncssh-based NAS client
│       ├── google_photos.py        # appendonly-scope upload
│       ├── apple_dropfolder.py     # alias for local_nas/remote_nas write; see
│       │                            #   docs/apple-ecosystem-setup.md for the
│       │                            #   Mac Folder Action / iOS Shortcuts side
│       ├── onedrive.py             # Microsoft Graph upload
│       ├── smugmug.py              # REST API v2, OAuth 1.0a
│       ├── backblaze.py            # B2 native or S3-compatible API
│       └── pcloud.py               # REST API, OAuth2
└── custom_components/eyefi/        # thin HA adapter — no protocol/geotag/storage logic here
    ├── __init__.py                 # async_setup_entry: starts eyefi_core embedded (v1) or
    │                                #   connects to a standalone eyefi_core daemon (later)
    ├── manifest.json
    ├── config_flow.py              # HA config UI; writes config eyefi_core consumes
    ├── const.py
    ├── camera.py                   # optional camera entity, subscribes to eyefi_core events
    └── translations/en.json
```

## Reference material (read-only, not build bases)

- `usefulthink/node-eyefi` — JS protocol implementation, initial reference.
- `tachang/EyeFiServer` — original documented protocol (SOAP envelopes,
  credential flow); see `Documentation/EyeFi Protocol.txt`.
- `dgrant/eyefiserver2` — Python fork with geotagging already implemented;
  primary source for `.log` format and Google Geolocation API usage.
- `ryantm/heyefi` — Haskell, archived; config schema reference only.

## Immediate next steps for Claude Code

1. Scaffold the two-tier repo layout above: `eyefi_core/` (installable,
   zero HA imports) and `custom_components/eyefi/` (thin adapter).
2. Build `eyefi_core` first, as a plain Python package testable on its own
   without HA running:
   a. `protocol.py` (SOAP XML templates + MD5 credential logic) and
      `soap_server.py` (aiohttp handlers for the 4 SOAP actions).
   b. `tar_extract.py` for the multipart/tar payload, preserving the
      `.log` sidecar file instead of discarding it.
   c. `geotag.py`: parse the `.log` file, resolve via a pluggable
      geolocation backend (Google first), write EXIF via `piexif`.
   d. `events.py`: the abstract pub/sub interface (in-process
      implementation now).
   e. `storage/` backends: `local_nas` first (default, no external auth),
      then `remote_nas`, `onedrive`, `smugmug`, `backblaze`, `pcloud` (all
      official APIs). `google_photos` is upload-only (no read-back).
      `apple_dropfolder` is a thin alias over `local_nas`/`remote_nas`.
3. Build `custom_components/eyefi/` as a thin adapter: `config_flow.py`
   collects mac/upload-key/destination config and hands it to
   `eyefi_core`; `__init__.py` starts `eyefi_core` embedded; `camera.py`
   and/or `hass.bus` event firing subscribe to `eyefi_core`'s events.
4. Defer `eyefi_core/service.py` (standalone daemon mode) until embedded
   mode is working end-to-end — same code, just add the HTTP+WebSocket
   wrapper once the core logic is proven, at which point a future
   Homebridge/HOOBS plugin becomes a thin client of it.
5. Write `docs/apple-ecosystem-setup.md` covering both the Mac Folder
   Action path and the iOS Shortcuts path (content drafted in the section
   above — turn into full step-by-step user docs with screenshots/exact
   menu paths).
6. Write a README documenting setup, crediting reference projects, and
   noting the license (MIT for both `eyefi_core` and the HA adapter).
