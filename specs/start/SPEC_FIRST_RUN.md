# First-time setup (out-of-box experience)

Status: **design proposal**, nothing here is built yet. Written 2026-11-22;
owner decisions from the same day are in "Decisions" below and override
anything older in this document.

## Decisions (2026-11-22)

| Topic | Decision |
|---|---|
| Boards | **Pi 4 first.** The Zero 2 W is deferred until one is in hand (3.6 stays as the to-test list). |
| Regions | **United States**, plus **Canada** if cheap. Wi-Fi country is `US` by default and set from the phone's region during setup (`US` / `CA`); both allow the same 2.4 GHz channels 1-11, so the hotspot config doesn't change. Canada's extra work is outside the code: French on the label, box and printed guide for Québec, and radio-compliance labelling (check with a compliance lab for both countries). |
| QR on the label | One `https://starlock.app/s#...` link that is an **iOS Universal Link and an Android App Link** (`apple-app-site-association` + `assetlinks.json` on starlock.app). With the app installed it opens the app on either platform; without it, the browser shows a setup-instructions page on starlock.app that the owner controls. A plain Wi-Fi QR is the fallback if App Links can't be made to work. |
| Factory reset | In the app (owner) **and** a physical **button** (hold 10 s while running, LEDs confirm), plus the `starlock-reset` boot-partition file as a last resort. No power-cycle pattern. See 7.4. |
| Minimum iOS | **iOS 18.** Unlocks AccessorySetupKit for finding a unit's hotspot without the QR. |
| Location | Viewers on the unit's network see the exact location (they're within ~50 m anyway). No rounding. |
| Second-hand units | **A factory reset gives the unit a new identity.** The buyer claims it as a new device and gets their own data; the previous owner's cloud data stays in their account, untouched and unreadable to the buyer. No transfer or support process. See 7.3. |
| Self-built units | Get a one-time notice when claimed ("not built by Starlock"). A purchased unit never shows it, even after a reset or reflash, because its "built by Starlock" key lives in the Pi 4's one-time-programmable memory. See 7.3. |
| Bench boot | One powered bench boot per unit is fine. |
| Unit key | Split into two (7.3): a permanent **hardware key** that only proves "built by Starlock", and a **device identity** that is replaced on every reset. |

This covers what happens between "a customer unboxes a Starlock" and "the
Starlock is on their phone, on the right network, and owned by them". It
spans three repos:

| Repo | What it does in this flow |
|------|---------------------------|
| `pushnav` (this repo, GPL-3.0) | Pi image, first boot, network modes, local API, local ownership, factory reset |
| `starlock-ios` (private) | Finds the unit, joins its hotspot, hands it Wi-Fi details, claims it |
| `starlock-cloud` (private) | Account ownership of a unit, release and transfer |

The apps and the cloud may use this document as a spec. They must not copy
code from this repo (see the iOS `README.md`); they only talk to the Pi over
the network.

---

## 1. Current state

### 1.1 Pi packaging and first boot

- `packaging/headless/user-data` is a cloud-init file for a **stock**
  Raspberry Pi OS Lite (64-bit, Trixie) card. The maker copies it and the
  `.deb` onto the boot partition by hand. On first boot it:
  - sets hostname `starlock` (the same on every unit);
  - creates user `pi` / password `starlock` with password-less sudo, and turns
    on SSH with password login;
  - sets the Wi-Fi country to `IN` (hard-coded, marked "CHANGE");
  - writes `/etc/starlock-ssid` = `Starlock-XXXX` (last 4 hex of the board
    serial);
  - creates a **permanent** NetworkManager hotspot (`ipv4.method shared`,
    192.168.77.1/24, 2.4 GHz `band bg`, WPA2-PSK `starlock123` for every
    unit, PMF off);
  - installs the `.deb` from the boot partition with `apt-get install`.
  - There is no station (home Wi-Fi) mode and no fallback logic. It is
    tested by `tests/test_headless_user_data.py`.
- The owner's own Pi has a hand-installed `starlock-wifi-fallback.service`
  (hotspot only when home Wi-Fi isn't in range). It is **not** in the repo or
  the package.
- `packaging/headless/starlock-headless.service` runs the engine as the
  unprivileged `starlock` user with `NoNewPrivileges`, `ProtectSystem=strict`.
  Root work is done only by `ExecStartPre=+` helpers (LEDs, cpufreq, debug
  pin). The engine therefore **cannot** change networking today.
- `debian/postinst` creates the `starlock` user and enables the service.
  State lives in `/var/lib/starlock-headless` (`config.json`, `cloud.json`,
  `observations.sqlite3`, logs).
- `scripts/build_headless_deb.sh` builds the arm64 `.deb` in a Bookworm
  container (runs on Bookworm and Trixie). There is **no image build**.
- `scripts/make_pi_label.py` makes a 50 x 20 mm label. Its QR code is the web
  URL (`http://192.168.77.1:8780`), not a Wi-Fi join code; the text shows the
  hotspot name, password and SSH login, read from `user-data`.
- Docs (`docs/rpi-headless.md`) list the Pi 3A+, 4 and 5; ~150 MB RAM use; a
  3A+ does ~2 solves/s. The Zero 2 W is only mentioned for its LED.

### 1.2 Discovery

- `python/evf/discovery.py`, spec `SPEC_DISCOVERY.md`: Bonjour
  `_starlock._tcp`, TXT `id` = `device.id` from `config.json` (random
  `uuid4().hex`, made on first start by `config/manager.py`, so it changes
  after a config wipe). Address set re-checked every 30 s and the advert
  rebuilt when it changes.
- iOS (`App/Sources/Discovery.swift`) browses with `NWBrowser`; the device
  picker (`DevicePickerView.swift`) has a hard-coded fallback button for
  `192.168.77.1` and tells the user to join the hotspot themselves. No
  hotspot joining, no Bluetooth, no Wi-Fi provisioning. Minimum iOS 17.
  Entitlements are only push + Sign in with Apple.

### 1.3 Local web API (`python/evf/webserver/server.py`)

Every route is unauthenticated to anyone who can reach port 8780: goto,
wizard, camera controls, `POST /api/settings` (incl. location),
`GET/DELETE /api/observations`, `GET /api/observations.csv`,
`POST /api/cloud/pair`, `DELETE /api/cloud`, dev routes. The `/ws` state
includes the observer's latitude/longitude. Only a log warning is emitted
for a non-local WebSocket `Origin`.

Concrete finding: aiohttp's `request.json()` parses any body without
checking `Content-Type`, so a web page anywhere on the internet that the
user opens while on the same LAN can send a "simple" cross-site
`POST text/plain` (no CORS preflight) to `http://starlock.local:8780/api/...`
— e.g. `/api/cloud/pair` with the attacker's own pairing code, or
`/api/goto/set`. (`DELETE` needs a preflight and is blocked by the browser.)
DNS rebinding would also let a remote page **read** `/api/observations`.

### 1.4 Cloud link

Pi side (`python/evf/cloud/`):
- `pair()` claims a code and **overwrites** `cloud.json` even if already
  linked. It does not tell the old account. It then calls
  `store.reset_cloud_sync()`, so the **whole local observation history**
  (made under any previous owner) is uploaded into the new account.
- `unlink()` calls `DELETE /v1/device` (removes the device from the owner's
  account; keeps their cloud data) then deletes `cloud.json`. Reachable by
  anyone on the LAN through `DELETE /api/cloud`.
- On a 401 the Pi forgets the link (owner removed it in the app).

Cloud side (`starlock-cloud/src/Starlock.Cloud.Api/Features/Devices/DeviceEndpoints.cs`,
`Auth/AccessRules.cs`, `Auth/DeviceAuthentication.cs`):
- `POST /v1/pairing-codes` (user): single-use 8-char code, 10 min TTL.
- `POST /v1/pairing/claim` (anonymous, rate-limited per IP): creates a
  **brand-new** `DeviceRecord` with a new random `deviceId` in the code
  owner's partition. `localId` is stored as sent by the Pi; it is not
  unique, not checked, not verified.
- Credential `sld1.{userId}.{deviceId}.{secret}`; only the hash is stored.
  Deleting the device record revokes it.
- `DELETE /v1/devices/{id}?deleteData=` (owner) and `DELETE /v1/device`
  (the Pi itself, always keeps data) both just delete the record.
- All data is partitioned by `userId` taken from the caller, never the
  request. Observations stay in the old owner's partition after a device is
  removed.

What that means for ownership today:

| Question | Today |
|---|---|
| Can someone else read the previous owner's **cloud** logs? | **No.** They live in the old owner's partition; a new claim creates a new device in the new owner's partition. This property already holds. |
| Must the owner release the unit before it's claimed by another account? | **No.** The cloud has no notion of a physical unit. Anyone on the LAN can re-pair the Pi to their account; the old record is orphaned (shows "last seen" going stale). |
| Can a new claimant get the previous owner's **local** history? | **Yes** — `GET /api/observations` with no auth, and `reset_cloud_sync()` uploads it all to the new account on re-pair. |
| Can anyone on the LAN remove the unit from the owner's account? | **Yes**, `DELETE /api/cloud`. Owner isn't notified. |
| Is there a transfer or support flow? | No. |

---

## 2. Goals and non-goals

Goals:
1. One image file that boots on both the **Pi 4** and the **Pi Zero 2 W**,
   flashed identically onto every unit; per-unit details made on first boot.
2. Phone app finds a fresh unit with no typing, in hotspot mode and on home
   Wi-Fi.
3. User picks "use my Wi-Fi" or "stay standalone"; wrong details roll back
   safely to the hotspot.
4. A unit claimed in Starlock Cloud can only move to another account after
   the owner releases it (or support does). Nobody but the owner sees the
   owner's logs, local or cloud.
5. The web UI stays usable without an app for observing.

Non-goals: Android (design must not rule it out), locking the device itself
against its owner (impossible and undesirable with GPL software — the owner
can always reflash; ownership enforcement lives in the cloud), HTTPS on the
LAN in the first phase.

---

## 3. The image

### 3.1 Recommendation: remaster the pinned official Raspberry Pi OS Lite arm64 image

Script `scripts/build_pi_image.sh`:
1. Download a specific `raspios_lite_arm64` (Trixie) `.img.xz`, verify its
   SHA-256 (pinned in the script).
2. Grow the image by ~300 MB, loop-mount it, chroot in with
   `qemu-user-static` (or run natively on an arm64 host / the
   `ubuntu-24.04-arm` GitHub runner).
3. `apt-get install` the just-built `starlock-headless_*.deb` and the extra
   pieces (`starlock-network`, `starlock-firstboot`, see 3.3/4). Purge
   what a single-purpose unit doesn't need. Keep cloud-init installed but
   ship no `user-data` that does anything (so DIY users can still drop one
   in; see 3.5).
4. Empty `/etc/machine-id`, delete SSH host keys, leave no login user with a
   password, SSH off.
5. Write a build manifest (`dpkg -l`, base image hash, .deb version, git
   commit) next to the image; output `starlock-<version>-arm64.img.xz` plus a
   Raspberry Pi Imager `os_list` JSON so it can be flashed from Imager's
   custom repository.

Why: it keeps Raspberry Pi's own kernel, firmware, boot-time resize and
host-key regeneration exactly as shipped, it's a ~150-line script, and the
inputs are pinned so a rebuild gives the same package set (not a
bit-identical image; that is not worth chasing).

**One image fits both boards.** The 64-bit Raspberry Pi OS image already
supports Pi 3, 4, 5 and Zero 2 W; `config.txt` picks the right kernel and
device tree. rpi-image-gen's minimum target is also the Zero 2 W.

### 3.2 Alternatives considered

| Option | Verdict |
|---|---|
| **pi-gen** with a custom stage after `stage2` (Lite) | Mature, Docker build, defaults to Trixie. Rebuilds the whole OS from debootstrap (~1 h), more to maintain. Fallback if remastering ever runs out of road (e.g. we want a read-only root). |
| **rpi-image-gen** (Raspberry Pi, 2025, BSD-3) | Declarative profiles, made for exactly this. Still "under active development", examples are Bookworm, best run on a Pi host. Re-evaluate in 2027. |
| **Keep the `user-data` + `.deb` on stock image** (today) | Fine for DIY, wrong for a product: first boot needs `apt` (slow on a Zero), relies on manual file copying, bakes a shared password and an SSH sudo account. |
| sdm (gitbls/sdm) | Capable customiser, but another tool to learn; remastering covers our needs. |

### 3.3 First boot (`starlock-firstboot.service`, root, runs once)

Runs before NetworkManager brings up Wi-Fi, guarded by
`ConditionPathExists=!/etc/starlock/unit.json`:

| Item | How | Where | Survives factory reset? |
|---|---|---|---|
| Unit serial | `/sys/firmware/devicetree/base/serial-number` | `unit.json` | yes |
| Short id | last 4 hex of serial, upper case (`3F2A`) | `unit.json` | yes |
| Hostname | `starlock-3f2a` (unique on a LAN — two units at a star party no longer fight over `starlock.local`) | `/etc/hostname` | yes |
| Hotspot SSID | `Starlock-3F2A` | NM profile `starlock-hotspot` | yes |
| Hotspot password | random, 12 chars from an unambiguous alphabet, shown as `7KQ2-M9XP-4TWD` | `unit.json` + NM profile | yes |
| Setup code | random, 8 chars, separate from the Wi-Fi password (local ownership, 7.2) | `unit.json` (hash only) + label | yes |
| Hardware key | Pi 4 OTP customer private key, burned once at the bench (7.3); Ed25519 derived from it | SoC OTP (never on the card) | yes, and survives reflashing |
| Wi-Fi country | from the factory batch config on the boot partition (`starlock-factory.txt`), else `US`; changed later from the app | `raspi-config nonint do_wifi_country` | yes |
| `device.id` (Bonjour `id`) | made by the engine as today | `config.json` | **no** — new id after reset |
| SSH host keys, machine-id | Raspberry Pi OS's own first-boot steps | `/etc` | yes |

`/etc/starlock/unit.json` is root-only. The engine reads the non-secret
parts (SSID, short id, setup-code hash) through the network helper (4.2).

### 3.4 Factory flow (per unit)

1. Flash N cards with the same image (Imager or `dd`).
2. **Bench boot** each assembled unit once with its camera: first boot makes
   the identity, then runs a self-test (camera found, catalog loads, one
   solve on a built-in sample) and shows the result on the LED.
3. First boot writes `starlock-unit.json` (serial, SSID, hotspot password,
   setup code, unit public key) to the **boot partition**.
4. On the bench PC, `make_pi_label.py --unit <bootfs>/starlock-unit.json`
   prints the label (7.1 for the QR contents) and, optionally, registers the
   unit with the cloud (serial hash + public key, 7.3). A `--seal` step then
   deletes the boot-partition file so the secrets are only on the label and
   in root-only `/etc`.
5. An **unsealed** card (DIY users who flash our image themselves) keeps
   `starlock-unit.json` on the boot partition, so they can read their
   password from a PC. The hotspot falls back to that.

The bench boot is required for labelled units: a card that is never booted
before shipping has no password yet to print.

### 3.5 DIY path

Keep `packaging/headless/user-data` for people installing on their own Pi,
but change it to call the same `starlock-firstboot` logic (random password,
unique hostname) instead of the fixed `starlock123` / `pi:starlock`.
`apt install` on an existing Pi keeps today's behaviour (no network changes
unless the user turns hotspot mode on).

### 3.6 Pi Zero 2 W

| Topic | What we know | Unknown / to test |
|---|---|---|
| CPU/RAM | RP3A0: 4x Cortex-A53 @ 1 GHz, 512 MB. The Pi 3A+ (same cores at 1.4 GHz, 512 MB) runs Starlock at ~150 MB and ~2 solves/s. | Expect ~1.3–1.5 solves/s on the Zero; measure with `scripts/bench_solvers.py`. Check whether the 50 MB `tetra3rs_gaia.bin` is read into RAM or mapped, and peak RSS during a solve. Thermal throttling inside a closed box. |
| Power cap | `power.max_freq_mhz` default 1200 is above the Zero's 1000 max, so the cap does nothing there. | Pick a Zero default (e.g. 800) after measuring. |
| USB | One micro-USB OTG data port: the camera needs an OTG adapter; no Ethernet. | Power budget of camera + Zero on one supply. |
| Wi-Fi | CYW43436, **2.4 GHz only**, single antenna shared with Bluetooth. AP mode works with NetworkManager. | Home networks that are 5 GHz-only are invisible; the app must say so. Client limit (Broadcom AP mode is anecdotally ~8 clients). |
| AP + station at once | brcmfmac allows a virtual AP next to a station only on the **same channel**, and there are reports of firmware crashes doing it on Trixie (raspberrypi/linux#7092, Pi 5) and of slow responses on a Zero 2 W. | **Design does not depend on it** — one mode at a time (4.1). |
| Boot time | cloud-init + NetworkManager are slow on Zero-class boards. | Measure; disable cloud-init's network stage on the product image if it costs >10 s. |
| Swap | — | Whether Trixie's default swap/zram setup is enough during `apt` upgrades on 512 MB. |

---

## 4. Network modes on the Pi

### 4.1 One radio, one mode at a time

The Pi is **either** a station on a saved network **or** the hotspot, never
both. That avoids the channel-locking and firmware problems above and works
the same on Pi 4 and Zero 2 W.

Modes (`network.mode` in a root-owned `/etc/starlock/network.json`):

- `auto` (default once a home network is saved): at boot try saved networks
  for up to 40 s; if none connects, start the hotspot. This is the owner's
  `starlock-wifi-fallback.service` behaviour, productised.
- `hotspot` ("standalone"): hotspot only, never tries saved networks. Factory
  default (no networks saved yet), and what the user picks to stay standalone.

A wrong password, a network out of range or a changed router all end the
same way: hotspot after 40 s. No reset is ever needed to get back in.
While on the hotspot the Pi does not leave it on its own (a phone may be
connected); the user can press "Try my Wi-Fi now" in Settings.

The hotspot profile keeps today's settings (192.168.77.1/24, `shared`, 2.4
GHz, WPA2-PSK CCMP) with the per-unit password. DNS on the hotspot answers
only local names; there is no internet and **no captive portal** (Apple DTS
says its captive-network machinery isn't meant for accessories, and the
captive sheet is a throw-away mini-browser). iOS will show "No Internet
Connection" and keep using cellular for other apps, which is what we want.

### 4.2 `starlock-network` (root helper)

A small root systemd service, separate from the engine, so the boot
fallback works even if the engine crashes and the engine keeps its sandbox.
It owns NetworkManager via `nmcli`/D-Bus and exposes a narrow JSON API on a
Unix socket writable by group `starlock`:

| Call | Effect |
|---|---|
| `status` | mode, current SSID/IP, hotspot SSID, last attempt result, saved networks (names only), country |
| `scan` | cached scan from just before the hotspot came up, plus `rescan` (drops the hotspot for ~5 s; the app warns) |
| `try_network {ssid, psk, hidden}` | starts a **pending** attempt (4.3) |
| `confirm {attempt_id}` | makes a pending network permanent |
| `set_mode {auto|hotspot}`, `forget {ssid}`, `hotspot_now`, `set_country` | |
| `factory_reset` | 7.4 |

It never returns a password, except the hotspot password to the setup flow
when asked with a valid owner token (for "show Wi-Fi QR" on the owner's
phone).

### 4.3 Joining home Wi-Fi with automatic rollback

Like a display-settings change that reverts unless you confirm:

1. Owner app: `POST /api/network/wifi {ssid, password}` → `202
   {attempt_id, join_timeout_s: 40, confirm_timeout_s: 180}`.
2. Pi waits ~3 s (so the reply gets out), drops the hotspot, tries the
   network. Success = NetworkManager activated the connection **and** got a
   DHCP lease.
3. If that fails within 40 s: hotspot back up, profile deleted, result
   recorded from NetworkManager's reason: `wrong_password`
   (no-secrets / supplicant failure), `not_found`, `no_address`, `timeout`.
4. If it succeeds: Bonjour re-advertises on the new address right away
   (discovery should re-check on a network-change signal from the helper,
   not wait for its 30 s poll). The Pi now waits up to 180 s for **any owner
   client to reach it on the new network** (the app calls
   `POST /api/network/confirm`; the web UI calls it automatically when it
   loads over the new address with an owner token).
5. Confirmed → saved, `mode=auto`. Not confirmed → back to the hotspot with
   result `unreachable` ("joined, but your phone couldn't find it — guest
   network or client isolation?").

The confirm step catches the nasty case where the Pi joins fine but the
phone can't see it (guest SSID, AP isolation, mDNS filtered, phone on a
different VLAN), which would otherwise strand the unit until reboot.

---

## 5. Discovery and provisioning (app side)

### 5.1 Recommendation: hotspot + QR label + `NEHotspotConfiguration`

**First power-on, with the app:**

1. Unit boots into the hotspot `Starlock-3F2A` (Zero ~60 s). LED pattern
   "waiting for setup".
2. App onboarding: "Scan the code on your Starlock". The QR (7.1) gives the
   app the exact SSID, password and setup code. Typing them is the fallback.
3. App calls `NEHotspotConfigurationManager.apply` with
   `NEHotspotConfiguration(ssid:passphrase:isWEP:false)`. iOS shows one
   system prompt ("Starlock wants to join Wi-Fi network…"). Needs the
   **Hotspot Configuration** capability. Use `joinOnce = false` (`true` has
   had background-removal bugs and makes iOS cling to the internet network)
   and remove the configuration ourselves when it's no longer wanted.
4. App explains and triggers the Local Network prompt *before* step 3 (so
   the prompt doesn't land mid-join), then browses `_starlock._tcp`. Bonjour
   works on the hotspot because the Pi *is* the access point; fall back to
   `192.168.77.1`. Match on TXT `id` and `GET /api/version`.
5. `POST /api/setup/claim {setup_code, client_name}` → owner token (7.2),
   stored in the Keychain under the unit's id.
6. Two buttons:
   - **"Use my home Wi-Fi"** → Pi's scan list (sorted by signal; this also
     tells the user whether the Pi can hear the router *where the scope
     stands*), with a note on Zero 2 W units that 5 GHz-only networks won't
     show. User types the password (iOS has no API to hand over a saved
     Wi-Fi password). App also sends country (phone region), time zone and
     clock. Then 4.3; meanwhile the app removes its hotspot configuration
     so the phone falls back to home Wi-Fi, and browses for the same `id`
     for up to 90 s, then confirms.
     If not found: "Starlock couldn't join *Home*. Reconnecting to its own
     Wi-Fi…" → re-apply the hotspot configuration, read
     `GET /api/network/status` for the reason, offer to retry.
   - **"Keep it standalone"** → `set_mode hotspot`. The app **keeps** the
     hotspot configuration so the phone auto-joins `Starlock-3F2A` in the
     field, and its device picker gets a "Join Starlock Wi-Fi" button that
     re-applies it.
7. Optional last step: sign in to Starlock Cloud and link (section 7.3).

**Without the app** (web only): the label text has the hotspot name and
password and the address `http://starlock-3f2a.local:8780` (and
`192.168.77.1:8780`). The web UI shows the same "Setup" card on an unowned
unit: setup code → Wi-Fi or standalone. After a switch the browser tab is
dead; the card tells the user to rejoin home Wi-Fi and open
`starlock-3f2a.local:8780`, where the page auto-confirms.

**Later changes** (owner only, Settings → Network): list/forget saved
networks, add a network (same pending/confirm flow), "Standalone only"
switch, "Switch to Starlock Wi-Fi now" (until next reboot), Wi-Fi country.
Moving house or a new router password needs nothing: the unit falls back to
its hotspot and the user adds the new network from there.

**Android later:** `WifiNetworkSpecifier` joins the hotspot (app-scoped,
which is fine for setup), `NsdManager` for discovery. Nothing above is
iOS-only.

### 5.2 Alternatives considered

| Option | Why not (now) |
|---|---|
| **BLE provisioning** (GATT service on BlueZ, e.g. the Improv Wi-Fi protocol; CoreBluetooth on iOS) | Its real strength is that the phone stays on home Wi-Fi and gets a synchronous "wrong password" while the Pi tries — no hotspot hop. But: Bluetooth must stay on (the owner disables it for power and it shares the antenna with 2.4 GHz Wi-Fi, worst on the Zero); we'd need a BlueZ GATT server in Python (D-Bus, pairing quirks), app-level encryption for the password (Improv has none beyond the BLE link), a Bluetooth permission prompt, and it does nothing for standalone mode, where the hotspot is needed anyway. Two transports to test instead of one. Revisit if support data shows the hotspot hop confusing people. |
| **AccessorySetupKit** (iOS 18+) with a Wi-Fi `ssidPrefix` "Starlock-" | Nice system picker with no QR and no Wi-Fi/Bluetooth prompts. But it needs iOS 18 (app is iOS 17), forum reports say `joinAccessoryHotspot` fails with prefix-only descriptors (needs the full SSID, which the app only has from the QR anyway), and a per-unit password still has to come from somewhere. Good **phase-3 polish** once the minimum iOS is 18: QR gives SSID, ASK gives the nice join. |
| **Concurrent AP + station** (keep hotspot up while testing home Wi-Fi) | Same-channel only, firmware-crash reports on Trixie, slow on the Zero 2 W. Not worth it given the rollback design. |
| **Captive portal** that pops the web UI on join | Apple warns against it for accessories; the captive sheet closes on its own and breaks the WebSocket; it makes iOS treat the network as "captive" and fight it. |
| **WPS / Wi-Fi Easy Connect (DPP)** | No iOS API; router support patchy. |
| **Open hotspot during setup only** | Anyone in range could claim an unowned unit first. Label password is cheap. |

---

## 6. Label and QR

The QR becomes an app link that also works without the app:

```
https://starlock.app/s#v=1&n=3F2A&p=7KQ2M9XP4TWD&c=H4KD7Q2M
```

- `n` short id (SSID `Starlock-<n>`, host `starlock-<n>.local`), `p` hotspot
  password, `c` setup code.
- Everything is in the URL **fragment**, which browsers never send to the
  server, so the secrets don't reach starlock.app's logs.
- With the app installed it opens as an iOS Universal Link or an Android
  App Link (`/.well-known/apple-app-site-association` and
  `/.well-known/assetlinks.json` on starlock.app; both hand the whole URL,
  fragment included, to the app). Without the app, the camera opens a
  static instructions page on starlock.app that links to the stores and
  shows the Wi-Fi details from the fragment for joining by hand.
- Label text keeps: Wi-Fi name, Wi-Fi password, web address. Drop the SSH
  login (SSH is off by default, 7.5). The setup code is printed too, labelled
  "Setup code", so the web-only path works.

The alternative QR, `WIFI:T:WPA;S:Starlock-3F2A;P:…;;`, lets the iPhone camera
join the hotspot with no app, but then the app can't get the setup code from
it. One QR per label, so the app link wins (decided).

---

## 7. Ownership, privacy and security

### 7.1 Threats we care about

1. A stranger on the same hotspot/LAN (star party, campground) changes
   settings, reads the owner's log/location, or re-links the unit to their
   account.
2. A web page the owner visits (CSRF / DNS rebinding) talks to the unit.
3. A second-hand buyer or a thief with a still-claimed unit reads the
   previous owner's data or takes over its cloud identity.
4. Device ids or location leaking to people nearby or to the internet.

Out of scope: someone with the SD card in their hand (they own the unit);
a determined attacker who knows the hotspot password sniffing plain HTTP
(see 7.6).

### 7.2 Local ownership: owner token, two tiers

| Anyone who can reach the unit (viewer) | Owner (holds a token) |
|---|---|
| Live view, `/ws`, frames, goto, wizard/sync/calibrate, exposure/gain, clock, LX200, Stellarium | Network settings, Starlock Cloud link/unlink, observation log read/delete/CSV, location, mount/power/LED/audio settings, factory reset, enable SSH, dev routes |

- Viewer actions stay open so a friend's phone or SkySafari works with no
  setup — that's the product. LX200 and Stellarium have no auth and only
  reach viewer actions.
- **Claiming:** `POST /api/setup/claim {setup_code}` works only while the
  unit has **no owner** (fresh or factory-reset). Returns a random 256-bit
  token; the Pi stores its hash with a name ("Kyle's iPhone", "Safari on
  Mac"). Wrong codes are rate-limited (5/min, then back-off).
- **More devices:** an owner adds another browser/phone by showing a
  one-time QR/code from Settings ("Add a device"), valid 10 minutes.
  The label's setup code does **not** work on an owned unit: borrowing the
  unit plus its label must not unlock the owner's log without wiping it.
- **Web UI:** owner sections show "Unlock with setup code" once per browser;
  the token goes in `localStorage`. Everything else looks the same.
- Owners can list and revoke tokens. Lost every token? Factory reset (7.4).
- Header: `Authorization: Bearer <token>`.

Cheap fixes that ship with this (and are worth doing even before tokens):
- Require `Content-Type: application/json` on every POST/DELETE (forces a
  CORS preflight, which the server doesn't answer → cross-site writes
  blocked).
- Reject requests whose `Host` isn't an IP literal, `*.local`, `localhost`
  or the unit's hostname (stops DNS rebinding).
- Reject a present `Origin` that doesn't match `Host`.
- `/api/dev/*` only in debug mode.

### 7.3 Cloud ownership: device identity and the hardware key

Owner rules: cloud data belongs to the account that recorded it and is never
readable by anyone else; a second-hand buyer factory-resets the unit and
starts fresh with their own data; a purchased unit is told apart from a
self-built one without nagging its owner.

**Two keys, two jobs.**

1. **Device identity** (who the cloud talks to). The engine's random
   `device.id` plus the cloud credential in `cloud.json`, as today. A
   factory reset deletes both, so the next claim creates a **new** device
   in the cloud. The previous owner's device record and its observation
   logs stay in their account ("Not seen since ..."), where they can keep
   or delete them. Nothing links the old record to the new one.
2. **Hardware key** (only proves "built by Starlock"). The Pi 4's SoC has
   one-time-programmable (OTP) memory with room for a 256-bit customer
   private key (`rpi-otp-private-key`; Pi 4, Pi 400, CM4 and Pi 5 with a
   current bootloader). At the bench, the factory script burns 32 random
   bytes there, derives an Ed25519 key pair from them, and registers only
   the **public key** in the cloud's list of genuine units. The list has
   no user link. OTP can't be erased or rewritten, so the key survives
   factory resets and reflashing, and a purchased unit stays "genuine"
   for good.

**Claim v2.** `POST /v1/pairing/claim` gains an optional `attestation`:
the hardware public key and a signature over `code|deviceId|timestamp`.
The cloud checks the signature and that the key is on the genuine list,
then stores only `genuine: true` on the new device record, not the key.
No attestation (self-built, or a board without the OTP key) means
`genuine: false`, and the app shows a one-time notice before finishing:
"This Starlock wasn't built by Starlock. It works the same; we can't help
with its hardware." The same account re-pairing the same `localId`
replaces its old record instead of adding a second one.

**What this deliberately gives up.** Because a reset makes a new identity,
a thief can reset a stolen unit and use it, cloud included. The owner's
data is still safe. If that matters later, add "Mark as lost" in the app:
the cloud would then remember which hardware key belonged to the owner's
device and refuse claims from it. That is the only feature that would need
the link, so it isn't stored today.

**Weak spots, accepted.** Anyone with root on a unit (it's GPL software,
so its owner can get root) can read the OTP key through the firmware
mailbox and copy "genuine" onto another Pi; all they gain is skipping the
notice. Burning OTP is permanent, so the bench script must be tested on a
sacrificial Pi 4 first, never on the developer's unit. Zero 2 W support
for this key is unknown; decide when one is in hand.

**Release.** Removing a device in the app (`DELETE /v1/devices/{id}`), the
Pi's own unlink (owner-token-gated, 7.2) and account deletion all end the
link. The remove dialog offers "keep my logs" (default) or "delete them".

Pi-side changes to go with it:
- `/api/cloud/pair` and `DELETE /api/cloud` are owner-only.
- `pair()` refuses with 409 while already linked ("Unlink first").
- After pairing, upload only sessions recorded **after** pairing. Older
  local history is offered explicitly ("Back up 42 earlier sessions from
  this Starlock?"), owner-only. Remove the unconditional
  `reset_cloud_sync()`.
- Sign the claim with the hardware key when the OTP key is present.

### 7.4 Factory reset

Triggers:
1. **In the app or web UI** (owner token; confirm twice). The normal way;
   it also removes the device from the owner's cloud account.
2. **Reset button**, for when the app can't get in (lost phone, lost owner
   token, broken network settings): a momentary button from a free GPIO to
   GND behind a pinhole in the enclosure. Held for 10 s while the unit is
   running, the LEDs blink fast for the last 3 s, then the reset runs. A
   short press could later mean "back to hotspot mode now", which fixes
   most "I can't reach it" cases without wiping anything. Read by the root
   network helper, the way `evf.engine.debug_pin` reads GPIO21 today.
   Needs a pinhole in the Pi 4 enclosure design.
3. **Boot-partition file** `starlock-reset` (card in a PC), for DIY units
   with no button. Documented, not on the label.

No power-cycle pattern: repeated power cuts risk the SD card. The unit
always falls back to its own hotspot when it can't join a saved network
(4.3), so the app can usually still reach it for an in-app reset.

Button and file resets forget `cloud.json` without calling the cloud; the
old device record stays in the old account.

Clears: `config.json` (so a new `device.id`, location, calibration,
settings), `observations.sqlite3` (deleted, after `secure_delete` +
`VACUUM`; SD flash can't be guaranteed wiped), `cloud.json` (owner-initiated
reset also releases in the cloud; physical reset does not), owner tokens,
all saved Wi-Fi networks, SSH enabled state and `authorized_keys`, Starlock
logs and the journal, debug captures. Returns to `mode=hotspot`.

Keeps: `/etc/starlock/unit.json` (hotspot SSID/password, setup code — they
match the label), the OTP hardware key (can't be erased), installed
software, Wi-Fi country.

### 7.5 Hotspot and SSH

- **Per-unit WPA2 password** on the label, not open and not a shared
  `starlock123` (which is as good as open once published in the docs). It
  keeps strangers off the unit's network in the field; the owner token
  still protects settings from friends the owner gave the password to.
- WPA3-SAE in AP mode on brcmfmac is unproven; stay on WPA2-PSK/CCMP, PMF
  off (as today) until tested with iPhones.
- **SSH off, no password account.** Owner can enable it from Settings
  (paste a public key). Power users with the card can still use Raspberry
  Pi OS's `ssh` + `userconf.txt` boot files. Today's `pi`/`starlock` with
  password-less sudo must not ship on a sold unit.

### 7.6 Privacy notes

- Bonjour TXT `id` is a random per-install id, new after a reset. Never put
  the serial, the hardware key or cloud `deviceId` in the TXT record or hostname.
  The hostname's 4-hex suffix reveals 16 bits of serial; acceptable.
- The cloud credential embeds the `userId`; it never leaves the Pi
  (`CloudLink.public()` already hides it).
- `/ws` sends latitude/longitude to every viewer; it drives the UI's
  visibility maths. Decided: keep it exact (viewers are on the unit's own
  network, so within tens of metres anyway).
- Plain HTTP on the LAN: someone with the hotspot password can sniff an
  owner token. Later phase: per-unit self-signed TLS on a second port, with
  the certificate fingerprint in the QR so the app can pin it (browsers keep
  HTTP).
- GPL: shipping units with Raspberry Pi OS means shipping (or a written
  offer for) the corresponding source of GPL parts of the image, not just
  Starlock's. Add the offer to the box insert and docs.

---

## 8. Open questions for the owner

Answered 2026-11-22 (see "Decisions" at the top). Still open:

1. **Reset button hardware:** which GPIO, and where the pinhole goes in the
   Pi 4 enclosure (a `hardware/3d_models` change).
2. **A sacrificial Pi 4 for OTP testing:** the hardware-key bench script
   must be proven on a board whose OTP can be burned for good.
3. **starlock.app hosting** for the `/s` instructions page and the two
   `.well-known` files (Static Web Apps, or served by the cloud).
4. **Android app id and signing key** for `assetlinks.json`, needed before
   the QR format is final even though Android work is deferred.

---

## 9. Phased work list

Sizes: S ≈ ½–1 day, M ≈ 2–4 days, L ≈ 1–2 weeks.

### Phase 1 — Close the local holes (no new UX)

| Repo | Work | Size |
|---|---|---|
| pushnav | Content-Type, Host and Origin checks on all writes; dev routes debug-only | S |
| pushnav | `pair()` refuses while linked; stop unconditional `reset_cloud_sync()`; explicit "back up earlier sessions" | S |
| pushnav | Owner token store + `/api/setup/claim`, `/api/owner/tokens`; gate owner routes; web UI unlock flow | M |
| starlock-ios | Send owner token on owner calls; Keychain storage per unit; unlock-with-setup-code screen | M |

### Phase 2 — Image and network modes

| Repo | Work | Size |
|---|---|---|
| pushnav | `starlock-firstboot` (identity, hostname, password, setup code, bootfs export) | M |
| pushnav | `starlock-network` root helper: modes, boot fallback, scan cache, pending/confirm attempts, NM failure reasons; replaces the hand-installed fallback service | L |
| pushnav | Engine/web API: `/api/network/*`; discovery re-checks on network change; web UI Setup card and Settings → Network | M |
| pushnav | `scripts/build_pi_image.sh` remaster + manifest + Imager JSON; CI on an arm64 runner | M |
| pushnav | `make_pi_label.py --unit … --seal`, new QR format; update `user-data` DIY path; docs | S |
| pushnav | Factory reset (owner, reset button, boot-partition file) in the helper; enclosure pinhole | M |
| starlock-ios | Onboarding: QR scan / Universal Link, Hotspot Configuration entitlement, `NEHotspotConfiguration` join/remove, Local Network pre-prompt | M |
| starlock-ios | Wi-Fi-or-standalone screens, scan list, switch + rediscover by `id` + confirm, failure → rejoin hotspot and show reason | M |
| starlock-ios | Settings → Network (saved networks, standalone switch, country) | S |

### Phase 3 — Cloud ownership

| Repo | Work | Size |
|---|---|---|
| starlock-cloud | Genuine-units list; claim v2 (optional hardware attestation → `genuine` flag, same-user replace); release on device delete, self-unpair and account delete | M |
| starlock-cloud | Admin endpoint: register a genuine unit's public key (bench), with audit log | S |
| starlock-cloud | Docs: `pi-integration.md`/`app-integration.md` updates, error codes | S |
| pushnav | Bench script: burn the OTP key (Pi 4), derive Ed25519, register the public key; sign claims with it | M |
| starlock-ios | "Not seen since ... / Remove" on the device list; remove dialog (keep/delete logs); self-built notice on claim | S |
| starlock.app site | `/s` instructions page, `apple-app-site-association`, `assetlinks.json` | S |

### Phase 4 — Polish (optional)

| Repo | Work | Size |
|---|---|---|
| starlock-ios | AccessorySetupKit picker (iOS 18 is now the minimum) | M |
| pushnav + starlock-ios | Per-unit TLS port with fingerprint pinning from the QR | M |
| pushnav | Zero 2 W: bench (solve rate, RSS, boot, thermal), defaults, hardware-key answer | M |
| pushnav | BLE provisioning, only if field data asks for it | L |

---

## References

- Raspberry Pi, *Introducing rpi-image-gen* (2025): https://raspberrypi.com/news/introducing-rpi-image-gen-build-highly-customised-raspberry-pi-software-images
- rpi-image-gen: https://github.com/raspberrypi/rpi-image-gen
- Raspberry Pi, *Cloud-init on Raspberry Pi OS*: https://raspberrypi.com/news/cloud-init-on-raspberry-pi-os
- Trixie STA+AP firmware crash: https://github.com/raspberrypi/linux/issues/7092
- Zero 2 W hotspot with NetworkManager: https://community.element14.com/products/raspberry-pi/f/forum/55064/how-to-enable-hotspot-in-raspberry-pi-zero-2w-with-network-manager-nmcli
- `NEHotspotConfiguration.joinOnce`: https://developer.apple.com/documentation/networkextension/nehotspotconfiguration/joinonce
- joinOnce problems: https://developer.apple.com/forums/thread/700612
- iOS leaving a no-internet accessory network: https://developer.apple.com/forums/thread/848895
- Captive portal and accessories (Apple DTS): https://developer.apple.com/forums/thread/723534
- AccessorySetupKit + `ssidPrefix` join failure: https://developer.apple.com/forums/thread/774760
- Improv Wi-Fi (BLE provisioning): https://esphome.io/components/improv_ble/ , https://docs.rs/crate/improv-wifi/0.1.2
