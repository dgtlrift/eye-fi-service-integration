# Apple ecosystem delivery (iCloud Photos)

There is no official public API for uploading directly into iCloud Photos,
so the `apple_dropfolder` destination in this integration does not talk to
Apple at all. Instead it writes photos to a plain shared folder — the same
`local_nas`/`remote_nas` storage backend, just pointed at a folder one of
your Apple devices can also reach — and one of the two on-device
automations below picks new files up from there and imports them into
Photos. From that point on, your existing iCloud Photos sync (already
enabled on most setups) takes over automatically.

The integration has no visibility into which automation you use; pick
whichever path matches the hardware you have.

| You have | Use | Latency |
|---|---|---|
| A Mac that's usually on | [Path 1: Mac Folder Action](#path-1--mac-present-preferred) | Real-time |
| iPhone/iPad only | [Path 2: iOS Shortcuts](#path-2--iosipados-only-no-mac) | Polling (15–30 min lag) |

## Path 1 — Mac present (preferred)

Event-driven, no polling: Folder Actions fire the moment Finder notices a
new file.

1. **Share/mount the drop folder on the Mac.**
   - If the drop folder lives on your NAS: mount the same SMB share on the
     Mac (Finder → Go → Connect to Server → `smb://<nas-address>/<share>`).
   - If the Mac itself *is* the drop target, just use a local folder — no
     mounting needed.
2. **Attach a Folder Action to the drop folder.**
   - Finder → right-click the drop folder → **Folder Actions Setup...**
     (if you don't see this option, enable it via Automator: File → New →
     Folder Action, choose the drop folder when prompted, then continue
     to step 3 to write the action).
   - Alternatively: open **Automator** → File → New → **Folder Action** →
     set "Folder Action receives files and folders added to" to the drop
     folder.
3. **Add an "Run AppleScript" action with this script body:**

   ```applescript
   on adding folder items to thisFolder after receiving addedItems
     tell application "Photos"
       repeat with anItem in addedItems
         import anItem skip check duplicates yes
       end repeat
     end tell
   end adding folder items to
   ```

4. Save the Folder Action.
5. **Caveat:** the Mac must be powered on and logged in for the Folder
   Action to fire — it does not run against a sleeping or logged-out Mac.
   If the Mac was asleep when photos arrived, it catches up the next time
   it wakes and Finder notices the folder changed; nothing is lost, it's
   just delayed.
6. Once photos land in Photos.app, iCloud Photos sync
   (**System Settings → Apple ID → iCloud → Photos**, already enabled on
   most setups) picks them up automatically — no further configuration
   needed here.

## Path 2 — iOS/iPadOS only, no Mac

Polling-based fallback: a Shortcuts automation checks the drop folder on a
schedule rather than reacting instantly.

1. **Add the drop folder as a Files app location.**
   - Files app → **⋯** (top right) → **Connect to Server** → enter the
     WebDAV or SMB address of your NAS/drop folder, or use the existing
     SMB support in Files if it's the same NAS share.
2. **Create a Personal Automation in Shortcuts.**
   - Shortcuts app → **Automation** tab → **+** → **Create Personal
     Automation** → **Time of Day**.
   - Set it to repeat — every 15–30 minutes is reasonable. This is
     polling, not event-driven, so there will always be some lag between
     upload and import.
3. **Add these actions to the automation:**
   - **Get Contents of Folder** (pointed at the Files location from step
     1).
   - Filter to items not already processed — Shortcuts has no built-in
     de-duplication, so you need either a "last run" marker file you
     compare dates against, or a "Filter Files" step on date added, to
     avoid re-importing the same photos every run.
   - **Save to Photo Album.**
4. **Disable "Ask Before Running"** in the automation's settings so it
   runs silently instead of prompting every time it fires.
5. **Caveats to keep in mind:**
   - This only runs while the device is reachable/awake often enough to
     hit its schedule — an iPhone left off WiFi or asleep through several
     scheduled runs will simply catch up whenever it next runs the
     automation.
   - There is inherent lag vs. the Mac path — treat this as "eventually
     synced," not real-time.
   - De-duplication is entirely your responsibility to configure; a naive
     setup without the date/marker-file filter will re-save the same
     photos into the album on every run.

## Why no `icloud.py` backend

Reverse-engineered iCloud clients (e.g. `pyicloud`) are deliberately not
used here — they carry real ToS/session risk and buy nothing over the
drop-folder approach, since Apple's own automations already do the "get it
into Photos" step reliably once files land in a folder your device can
see. `apple_dropfolder` in the integration's config flow is just an alias
that writes to `local_nas`/`remote_nas`; everything above happens entirely
on your own hardware, outside the integration.
