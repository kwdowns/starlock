# Starlock (EVF) — Plate-Solving Push-To System

## Project Overview

A plate-solving engine that reads live camera frames to determine telescope pointing,
enabling push-to navigation for manual telescopes. It ships only as the headless
Raspberry Pi package (`starlock-headless`); users control it from the React web UI
in a browser and from the native phone apps. The engine stays platform-agnostic and
runs on Windows, macOS and Linux PCs for development.

Python (engine + tetra3rs Rust plate-solver, serving the React UI over HTTP) talks to a native camera subprocess over TCP.
Camera servers are platform-specific: Swift (macOS), C/V4L2 (Linux), C/DirectShow (Windows).

External integrations run in-process on three TCP servers: a **Stellarium** binary-protocol
server on `localhost:10001`, an **LX200 Classic** ASCII server on `0.0.0.0:4030` for
SkySafari / Stellarium Mobile / INDI / ASCOM clients, and an **aiohttp HTTP + WebSocket**
server on `0.0.0.0:8780` for the phone-scannable mobile web interface. The web
server is advertised over Bonjour / mDNS as `_starlock._tcp` (`evf/discovery.py`,
TXT record in `specs/start/SPEC_DISCOVERY.md`) so phone apps find it without an IP.

The UI is a single screen with no tabs (design rules in `web/DESIGN.md`, red
channel only for night vision; live component reference at `?gallery`):
- **Camera** — live frame with plate-solve overlay and push-to arrow, sticky
  under the app bar on phones and in the left column on tablets. A pencil in
  its top-left corner toggles the camera settings under it (exposure/gain
  sliders and solve stats) once tracking; through the wizard they are always
  shown and there is no pencil.
- **Step area** — the setup wizard (camera, sync, calibrate); once tracking,
  the target readout (with its magnitude when this device sent it), the
  always-open sky dome (spins once when a target is picked), then Recenter
  on target and Restart setup.
- **Targets** — below the camera: Tonight (161 curated deep-sky objects,
  vendored from the Stargazing-Buddy site, with client-side visibility math),
  Search (NGC + bright stars) and Manual RA/Dec. Every row has a "Go to"
  button; tapping a row opens a detail sheet.
- **Settings sheet** (gear in the app bar) — settings, connectivity QR and
  the Logbook (observation log, range picker, CSV).
- **Equipment sheet** (telescope button left of the gear,
  `SPEC_EQUIPMENT_SITES.md`) — what's in use (site, telescope, eyepiece,
  finder; magnification and field), saved sites, each its own location and
  horizon (the Location panel and the Horizon editor, 16 directions × 10°
  bands hidden by trees or buildings; Tonight skips what's behind them), and
  the gear lists. Observer location feeds visibility math and falls back to
  Stellarium's reported location when a Stellarium client is connected. With
  an older engine the Location panel and Horizon editor stay in Settings.

## Build & Run

```bash
uv sync                          # install Python deps from lockfile
(cd web && npm install)          # install Node deps

# Production-style — engine serves the built React UI (there is no window)
(cd web && npm run build)
uv run python -m evf.main
# Open http://localhost:8780/ in your browser (or the configured webserver.port)

# Dev mode (HMR) — Vite serves UI on :5173 with hot reload
uv run python -m evf.main --dev                  # terminal 1: engine
(cd web && npm run dev)                          # terminal 2: Vite dev server
# Open http://localhost:5173 in your browser
```

`--no-window` is still accepted but does nothing. The camera watchdog, status
LED and CPU-cap helpers always start; off the Pi they do nothing.

### Platform-specific camera build

```bash
scripts/build_camera_mac.sh         # macOS — Swift camera server
make -C camera/linux                # Linux — C/V4L2 camera server
```

```cmd
camera\windows\build.bat            :: Windows — C/DirectShow camera server (run from VS Developer Command Prompt)
```

### Raspberry Pi package (the only release build)

```bash
scripts/build_headless_deb.sh       # Raspberry Pi — starlock-headless .deb (arm64, bookworm container)
scripts/smoke_test_headless_deb.sh  # install + run the .deb in clean bookworm / trixie containers
```

The Raspberry Pi package is the only supported host for customers, named
`starlock-headless`. It bundles a standalone Python under
`/usr/lib/starlock-headless` (runtime deps only, `--no-dev`), runs as the
`starlock-headless` systemd service (user `starlock`, state in
`/var/lib/starlock-headless`), and the launcher sets `STARLOCK_ROOT` so
`evf/paths.py` uses the release layout. The engine runs a camera watchdog
that keeps retrying the camera in the background, and shows its status on
the Pi's ACT/PWR LEDs (`evf/engine/status_led.py`), plus a brief green flash when a client
connects or sends a target (the servers' `on_client_connected` callbacks
and `GotoTarget` changes). The LEDs are only writable because the
unit's `ExecStartPre=+`/`ExecStopPost=+` run `evf.engine.led_helper
take`/`restore` as root; `led.enabled` in config.json turns it off.
The package also ships a Wi-Fi hotspot fallback: the one-shot
`starlock-wifi-fallback.service` runs `/usr/lib/starlock-headless/wifi-fallback`
(source `packaging/headless/starlock-wifi-fallback`) once per boot. If no known
Wi-Fi network or wired link connects (45 s, 10 s when no Wi-Fi is saved, +45 s
while a connection is in progress), it starts the NetworkManager connection
`starlock-hotspot` (`Starlock-XXXX`, 192.168.77.1, autoconnect off, created by
postinst if missing); it never touches a working connection and does not
re-check later. A hand-installed same-named unit in `/etc/systemd/system`
overrides it (postinst prints a note). Details in `specs/start/SPEC_FIRST_RUN.md` 1.1.
The same way, `evf.engine.cpufreq_helper take`/`restore` saves the CPU's
cpufreq `scaling_max_freq` and lets group starlock write it; the engine
(`evf/engine/cpufreq.py`) then caps the clock at `power.max_freq_mhz`
(default 1200, governor untouched) while `power.cpu_cap` is on, switchable
from the Settings panel's Power saving switch.
A jumper from GPIO21 (pin 40) to GND (pin 39) turns on debug mode on the Pi
without environment variables: another root `ExecStartPre=+` step,
`evf.engine.debug_pin`, reads the pin and creates `/run/starlock-headless/debug`
(in the unit's `RuntimeDirectory=`), which `main.py` treats like `STARLOCK_DEBUG=1`.

### Running tests

```bash
uv run pytest tests/
```

## Project Layout

```
pyproject.toml                  # project config (hatchling build, uv sources)
python/evf/                     # main Python package
  main.py                       # entry point — engine (no window; UI is served over HTTP)
  paths.py                      # centralized path resolution (repo vs release via STARLOCK_ROOT)
  network.py                    # shared LAN-IP probe used by webserver + engine
  wifi_signal.py                # the Pi's Wi-Fi signal (/proc/net/wireless), smoothed, for the weak-signal warning (/ws `wifi`)
  discovery.py                  # Bonjour / mDNS advert of the web server (_starlock._tcp, zeroconf)
  engine/                       # core engine, state machine, threading
    engine.py                   # main engine (owns all subsystems)
    state.py                    # state machine
    frame_buffer.py             # latest-frame buffer (no queues)
    pointing.py                 # telescope pointing state
    navigation.py               # goto-target navigation logic
    mount.py                    # push-to guidance along alt-az / equatorial mount axes (Settings → Mount)
    mount_model.py              # learns the alt-az base tilt / polar-axis error from steady solves; corrects the guidance (experimental)
    clock.py                    # engine-wide wall clock, corrected by a client's /api/clock when the Pi's is wrong
    goto_target.py              # thread-safe goto target container
    sample_injector.py          # dev-mode sample-image injector
    audio.py                    # audio feedback (lock/lost sounds)
    epoch.py                    # J2000 <-> JNow precession (pyerfa)
    solar_system.py             # Moon, planets, Pluto (astronomy-engine) + bright asteroids (two-body from data/minor_planets.json), served at /api/solar-system
    observation_log.py          # observation log: dwell tracker, SQLite store (observations.sqlite3 next to config.json) + one frame per entry (observation_frames/, oldest trimmed past a quota), CSV, client-corrected clock
  camera/                       # TCP camera client
    client.py                   # camera TCP client
    protocol.py                 # camera protocol (de)serialization
    subprocess_mgr.py           # camera subprocess lifecycle manager
  solver/                       # tetra3rs (Rust) plate-solving
    solver.py                   # solver wrapper
    thread.py                   # solver worker thread
    sync.py                     # multi-star sync / calibration
  stellarium/                   # Stellarium telescope protocol server
    server.py                   # TCP server for Stellarium connection
    protocol.py                 # Stellarium binary protocol
  lx200/                        # LX200 Classic TCP protocol server
    server.py                   # TCP server (select-based, multi-client)
    protocol.py                 # LX200 ASCII parsing + dispatch
  cloud/                        # optional Starlock Cloud link (opt-in; idle until paired)
    link.py                     # cloud.json (base URL, device id, credential; 0600, never sent to clients)
    client.py                   # stdlib HTTP client for the device API (Authorization: Device …)
    pointing.py                 # Live Activity pointing updates from the /ws payload (2 s / 30 s heartbeat / backoff)
    uploader.py                 # observation-log backup, batches of 100, idempotent entry ids
    service.py                  # owns link + workers; pairing (/api/cloud/pair) and unlinking
  webserver/                    # aiohttp HTTP + WebSocket server
    server.py                   # serves React build, MJPEG, /ws, /api/*
  config/                       # configuration
    manager.py                  # JSON config read/write
    observing.py                # saved sites + telescopes/eyepieces/finders (config `observing`): validation, migration, optics; keeps the site in use and location/horizon in step
    logging_setup.py            # logging configuration
web/                            # React + Vite + TS + Tailwind + shadcn/ui front-end
  package.json
  vite.config.ts
  src/
    App.tsx
    main.tsx
    components/                 # LiveView, StepArea, Targets, Settings, DebugPanel, ...
      app/                      # TopBar, SettingsSheet
      step/                     # StepArea (wizard cards, TrackingPanel)
      catalog/                  # Targets section — Tonight/Search/Manual panels, TargetList, TargetDetail sheet, filters, time, LocationPanel
      ui/                       # component library (see web/DESIGN.md)
      settings/                 # Settings, Connectivity, ObservationLog (range picker + CSV download), CloudLink
      live-view/                # LiveView, NavOverlay, AxesOverlay, StarOverlay, ...
        SkyDome/                # always-visible 3D dome (R3F) — pointing/target markers, telescope cylinder
    hooks/                      # useEngineState (WebSocket subscription), useFullscreen (Fullscreen API)
    lib/                        # api client, types, astronomy (altAz/rise/set), catalogTypes, advancedSearch, pwa (isStandalone)
    data/
      objects.json              # vendored buddy catalog (161 curated entries)
      openngc.json              # OpenNGC trimmed to ~12.5k NGC objects (CC-BY-SA 4.0)
      hyg-bright.json           # HYG v3 trimmed to ~8.8k bright stars (CC-BY-SA 4.0)
      object_sizes.json         # apparent size (arcmin) of the curated objects, for the size-aware on-target radius (scripts/build_object_sizes.py)
  public/                       # logo, inapp-title, favicons, PWA manifest.webmanifest + icons (red on #0a0000;
                                #   regenerate with scripts/make_pwa_icons.py). No service worker: plain HTTP on the LAN
  dist/                         # build output (gitignored)
camera/
  mac/                          # Swift camera server (macOS)
  linux/                        # C/V4L2 camera server (Linux)
  windows/                      # C/DirectShow camera server (Windows)
data/
  tetra3rs_gaia.bin             # tetra3rs Gaia star catalog (~50 MB)
  VERSION.json                  # app + protocol + db version metadata
  minor_planets.json            # JPL orbital elements for Ceres, Vesta, Pallas, Juno, Iris, Hebe (scripts/update_minor_planets.py; refresh before a release)
  sounds/                       # audio feedback WAVs (lock, lost, goto_ack)
  web_dist/                     # React build output (release-only — copied here by build scripts)
docs/                           # GitHub Pages documentation
  index.md                      # GitHub Pages landing page
  hardware.md                   # camera, lens, DIY, shopping list
  design.md                     # KISS philosophy, design decisions
  _config.yml                   # Jekyll config for GitHub Pages
  assets/                       # documentation images
hardware/                       # 3D-printable mechanical designs (OpenSCAD)
  3d_models/                    # OpenSCAD source and pre-built STLs (README lists every part)
    housing_v3.scad             # recommended camera housing, hood, cap and low (laptop) mount
    housing_v4.scad             # optional Pi 3A+ mount and box for headless use (YAPP_Box)
    housing_v2.scad, housing.scad  # deprecated v2 (threaded) and v1 (bolted) housings
    housing_u20cam.scad         # v3 housing resized for the 32 mm Innomaker U20CAM-9281M board
    tube_shoe.scad              # stick-on (VHB) finder shoe curved to the tube, takes the mounts' rail
    pi45_tray.scad              # stick-on tray for a Pi 4 / Pi 5 on the tube, and its snap-on cover
    laser_pointer_holder.scad   # 23 mm laser pointer cradle on a finder-shoe saddle
    camera_base.scad            # spare for the camera module's white base
    vendor/                     # threads.scad (CC0), YAPP_Box (MIT)
    stls/                       # pre-built STL files ready for printing
marketing/                      # app branding assets (logo, in-app title)
packaging/headless/             # starlock-headless .deb: launcher, systemd units (service + Wi-Fi hotspot fallback), debian/ maintainer scripts,
                                #   and user-data (first-boot config for the ready-made SD card, attached to releases)
build/                          # build output (gitignored)
scripts/                        # build and dev scripts
  build_headless_deb.sh         # Raspberry Pi starlock-headless .deb build
  smoke_test_headless_deb.sh    # container install/run test for the .deb (incl. the Wi-Fi fallback without NetworkManager)
  build_camera_mac.sh           # compile Swift camera server
  run_dev.sh                    # dev launch (macOS)
  run_dev_linux.sh              # dev launch (Linux)
  run_dev_windows.bat           # dev launch (Windows)
  run_mock_camera.sh            # launch mock camera for testing
  sync_catalog.py               # vendor objects.json from ~/Devel/Github/stargazing-buddy-site
  update_minor_planets.py       # refresh data/minor_planets.json from JPL's Small-Body Database
  build_object_sizes.py         # web/src/data/object_sizes.json from OpenNGC + a table of asterisms / big clusters
  make_pwa_icons.py             # regenerate web/public PWA/apple-touch icons from marketing/logo.png (red on #0a0000)
  make_pi_label.py              # 50 x 20 mm SVG + PNG label for a ready-made Pi (QR + hotspot details)
  fonts/                        # Atkinson Hyperlegible (OFL), used only by make_pi_label.py
  render_3d_models.py           # render docs/assets/3d_model_*.png from the STLs (uv run, PyVista)
  test_stellarium_live.py       # manual Stellarium integration test
tests/                          # test suite (pytest)
  samples/                      # plate-solve test images (a–d.png + targets/)
specs/start/                    # design specifications
```

## Key Dependencies

- **tetra3rs** — Rust (pyo3) plate-solver, installed from a prebuilt wheel (`tetra3rs==0.7.1`); no vendoring or Rust toolchain needed
- **React + Vite + TypeScript + Tailwind + shadcn/ui** — front-end stack (under `web/`)
- **three** + **@react-three/fiber** + **@react-three/drei** — WebGL rendering for the always-visible Sky View 3D dome (`web/src/components/live-view/SkyDome/`). Labels use drei `<Html>` to stay offline; `<Text>` is intentionally avoided so troika-three-text's CDN font-resolver is never loaded
- **numpy**, **Pillow** — image/array handling (solver wrapper) and the sync rotation maths
- **playsound3** — audio feedback for solve lock/lost events
- **zeroconf** (+ ifaddr) — pure-Python mDNS responder for the `_starlock._tcp` advert; runs alongside avahi-daemon on the Pi
- **aiohttp** — HTTP + WebSocket server (serves the React build, /ws state, /frame.jpg + /frame.mjpg, /api/*)
- **qrcode.react** (npm) — QR-code rendering for the LAN URL in the Settings panel
- **pyerfa** — IAU 2006 precession (J2000 ↔ JNow) for the LX200 protocol server
- **astronomy-engine** (MIT) — Moon, planet and Pluto positions and magnitudes for the solar-system targets
- **pyyaml** (dev group) — used by `scripts/sync_catalog.py` to parse the
  buddy-site markdown frontmatter when refreshing `web/src/data/objects.json`,
  by `tests/test_headless_user_data.py` to check `packaging/headless/user-data`,
  and by `scripts/make_pi_label.py` to read its passwords and address

Dev dependencies: **pytest** (tests), and **segno**,
**fonttools**, **uharfbuzz** and **freetype-py** for `scripts/make_pi_label.py`
(QR code, outlined and kerned text, and the PNG). The Pi package is built
with `--no-dev`, so none of these reach it.
Docs dependency group (`uv sync --group docs`): **mkdocs-material** for the
GitHub Pages site under `docs/`.

The runtime app does **not** depend on `~/Devel/Github/stargazing-buddy-site`.
That repo is only consulted by `scripts/sync_catalog.py` when the maintainer
runs the script to refresh the vendored JSON.

## Important: Loading the tetra3rs Catalog

The plate solver is **tetra3rs** (a Rust/pyo3 port of ESA's tetra3). The star catalog is a
prebuilt `SolverDatabase` at `data/tetra3rs_gaia.bin` (~50 MB, Gaia DR3, mag 8), loaded once
at startup:

```python
import tetra3rs
from evf.paths import tetra3rs_database_path

# load_from_file takes a plain string path — no Path-vs-string gotcha
db = tetra3rs.SolverDatabase.load_from_file(str(tetra3rs_database_path()))
```

In application code, use `evf.paths.tetra3rs_database_path()` (handles dev vs release path
resolution). The `.bin` is regenerated by `scripts/build_tetra3rs_catalog.py` from the
`gaia-catalog` package.

## Architecture Rules

- UI must NOT own core logic; core engine runs without UI
- Solver thread never blocks UI thread
- No frame queues — always use most recent frame only
- All shared state protected by `threading.Lock`
- Camera subprocess is a separate OS process, communicating over TCP
- The camera_server binary should `exit(1)` on device disconnect / fatal
  capture error; the engine's `CameraSubprocessMgr` watches the TCP socket
  and runs a 5-attempt backoff recovery loop (1, 2, 4, 8, 15 s)
- Path resolution goes through `evf/paths.py` (handles the dev repo on any OS and the Pi release under `STARLOCK_ROOT`)
- The Innomaker U20CAM-9281M (0c45:636d, Sonix SN9C286) has a camera-server quirk in all three
  servers (`u20_*` in the C servers, `U20CamQuirk.swift` on macOS): real gain via the firmware's
  RAM gain variable and a frame length that follows exposure, through the Sonix extension unit
  (unit 3, selector 1). Keep its write allowlist tight: never write the bridge's SPI flash
  controller (0x8E00–0x8EFF) or use the flash selector (3). Protocol notes in
  `specs/start/SPEC_PROTOCOL_CAMERA.md`
- All fonts in the React UI come from the OS — the app ships no web fonts and
  applies no `font-family` overrides; Tailwind v4 preflight uses its built-in
  `font-sans` / `font-mono` stacks (system-ui / ui-monospace)

## Licensing and copyright headers

Starlock is a fork of PushNav (meridianfield/pushnav, GPL-3.0-or-later). The
rules for copyright lines when editing or creating files are in
`.claude/rules/copyright-headers.md`.

## Specs

Detailed design docs live in `specs/start/`:
- `SPEC_ARCHITECTURE.md` — threading model, state machine, data structures
- `SPEC_PRODUCT.md` — product requirements
- `SPEC_PROTOCOL_CAMERA.md` — camera TCP protocol
- `SPEC_PROTOCOL_STELLARIUM.md` — Stellarium telescope binary protocol (J2000, port 10001)
- `SPEC_DISCOVERY.md` — Bonjour / mDNS service type and TXT record the native apps rely on
- `SPEC_FIRST_RUN.md` — out-of-box setup: Pi image, hotspot/QR provisioning, owner tokens, factory reset, cloud ownership (design)
- `SPEC_OBSERVING_LOG.md` — certifiable logbook: sessions, sightings, observations, equipment, sync, exports (design)
- `SPEC_UPDATES.md` — Pi updates: signed apt repo, daily check, owner-installed only (never automatic), rollback (design)
- `SPEC_EQUIPMENT_SITES.md` — saved sites (location + horizon) and equipment, `/api/observing/*`, `/ws` `observing` + optics, eyepiece-based on-target radius, Logbook page
- `SPEC_HORIZON_MOUNT_MODEL.md` — horizon mask (Settings → Horizon, filters Tonight), clock sync, mount model (experimental)
- `SPEC_EQUIPMENT_SITES.md` — saved observing sites (location + horizon), telescopes, eyepieces, finders; optics, eyepiece/finder circles, Logbook page
- `SPEC_PROTOCOL_LX200.md` — LX200 Classic ASCII protocol for SkySafari / Stellarium Mobile / INDI / ASCOM (JNow, port 4030)
- `SPEC_BUILD_RELEASE.md` — build and release process
- `ACCEPTANCE_TESTS.md` — acceptance criteria
