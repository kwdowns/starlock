# Updating the Pi

Status: **design proposal**, written 2026-11-22.

## Decision

**Nothing installs on its own.** A Starlock is usually switched on to start
observing, so it must never slow down, restart or change under the user
then. The Pi only **checks** and **tells**; the owner chooses when to
install, from the app or the web UI.

## 1. What gets updated

| Part | Source | Notes |
|---|---|---|
| **Starlock** (`starlock-headless` .deb) | Our signed apt repository, `apt.starlock.app`, channels `stable` and `beta` | Published by CI from release tags (`vX.Y.Z`), signed with a key kept as a CI secret; the image ships the public key (`signed-by=`), so the Pi accepts only our packages for it. The repo links the source (GPL). |
| **OS security updates** | Debian security and Raspberry Pi archives | Security origins only (kernel, firmware, bootloader EEPROM, libraries); no feature upgrades. |
| **Major OS versions** (Debian 13 → 14) | A new image | Not upgraded in place; the cloud backup or an export carries the data across. |

## 2. Checking

- Once a day, at a random time, **only when the Pi has internet** (home
  Wi-Fi) and **never while tracking**: `apt-get update` for our repo and the
  security sources, then work out what's pending. Runs in a root helper
  (`starlock-update`, same pattern as `led_helper` / `cpufreq_helper`) at
  low CPU and I/O priority. It sends no device id.
- Nothing is downloaded in advance; the check is a few hundred kB.
- The engine adds to the `/ws` payload:
  `updates: {checked_at, starlock: {installed, available, notes_url} | null,
  security: {count, needs_restart} | null}`.

## 3. Offering

- The web UI and the apps show a quiet banner in Settings (and a dot on the
  gear), never a pop-up over the live view:
  "Starlock 0.5.0 is available" / "12 security updates".
- Security updates get louder only with age: after 30 days a line on the
  connect screen, "Security updates are waiting — install when you're done
  observing".
- App and Pi compatibility: each compares the other's version
  (`/api/version`, the app's own). If they're too far apart for the
  features in use, the app says which one to update.

## 4. Installing (owner only)

- **Install** (owner token, SPEC_FIRST_RUN §7.2) runs the helper:
  Starlock and/or security updates, with progress in the UI. Refused while
  tracking or during a session with activity in the last 10 minutes ("Finish
  observing first"), unless the owner confirms.
- The Starlock service restarts at the end (the package's postinst); the
  app reconnects by itself.
- **Rollback:** the previous `.deb` stays in apt's cache. If the new
  version isn't serving `/api/version` within 2 minutes, the helper
  reinstalls the previous one and reports it.
- **Restart:** when an update needs one (kernel, firmware), the UI shows
  "Restart to finish updates" with a button. The Pi never restarts itself.
- Uses `unattended-upgrades` as a library only (security origins,
  `MinimalSteps`, so a power cut mid-install is survivable); its timer and
  automatic installs stay off.

## 5. Offline units

On the hotspot the Pi has no internet, so it can't check or update. Later
option: the phone, which has internet, fetches the Starlock `.deb` from the
repo, checks the signature and hands it to the Pi over the LAN. OS updates
still wait for home Wi-Fi.

## 6. Later, maybe

Full-image A/B updates (Pi 4 `tryboot`, Mender, RAUC) give atomic OS +
app updates with rollback, at the cost of a new partition layout. Revisit
if units sell at scale.

## 7. Work list

| Repo | Work | Size |
|---|---|---|
| pushnav | apt repo publishing in CI (reprepro or aptly → Azure static site), signing key, `apt.starlock.app` DNS | M |
| pushnav | Image: repo source + keyring; unattended-upgrades installed, timers off | S |
| pushnav | `starlock-update` root helper: check, install, rollback, restart; `/api/updates` + `/ws` field | M |
| pushnav | Web UI: Settings banner, install flow with progress, restart prompt | S |
| starlock-ios | Same banner and flow; compatibility messages | S |
