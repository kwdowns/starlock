# SPEC_BUILD_RELEASE.md — Starlock

Version: 2.2
Status: Reflects Current Implementation
Date: 2026-11-23
Target: Raspberry Pi (`starlock-headless` .deb, the only release build);
macOS, Linux and Windows PCs for development

---

## 1. Repository Layout

```
starlock/
  specs/start/
    SPEC_PRODUCT.md
    SPEC_ARCHITECTURE.md
    SPEC_PROTOCOL_CAMERA.md
    SPEC_PROTOCOL_STELLARIUM.md
    SPEC_BUILD_RELEASE.md
    ACCEPTANCE_TESTS.md
    EQ_PLAN.md
    impl0.md

  python/
    evf/
      main.py
      paths.py
      network.py        # LAN-IP probe shared by webserver + engine
      engine/
      cloud/
      discovery.py
      camera/
      solver/
      stellarium/
      lx200/            # LX200 Classic TCP protocol server
      webserver/        # aiohttp mobile web interface
      config/
  pyproject.toml

  camera/
    mac/              # Swift camera server (SwiftPM)
    linux/            # C/V4L2 camera server
    windows/          # C/DirectShow camera server

  data/
    tetra3rs_gaia.bin
    VERSION.json
    sounds/

  marketing/          # logo, in-app title images

  packaging/headless/ # .deb launcher, systemd unit, debian/ scripts, user-data

  scripts/
    build_headless_deb.sh
    smoke_test_headless_deb.sh
    build_camera_mac.sh
    run_dev.sh
    run_dev_linux.sh
    run_dev_windows.bat
    run_mock_camera.sh
    test_stellarium_live.py

  tests/
```

---

## 2. Dependency Strategy

### 2.1 tetra3rs (plate solver)

The solver is `tetra3rs` — a Rust/pyo3 port of ESA's tetra3 — installed from a prebuilt
wheel (no vendoring, no Rust toolchain). It ships `win_amd64` + `manylinux_2_28`
(x86_64/aarch64) wheels for cp312/cp313, so `uv sync` downloads the wheel; `cargo`/`rustc`
never run.

```toml
dependencies = ["tetra3rs==0.7.1", ...]
```

### 2.2 Python dependency locking

Uses `pyproject.toml` (hatchling build backend) with `uv` for dependency locking (`uv.lock`).

Dependencies: Pillow, numpy, tetra3rs, playsound3, aiohttp, pyerfa (>=2.0.0, for LX200 J2000↔JNow precession), among others. The React front-end (under `web/`) is built separately with Vite (Node deps from `web/package.json`) and copied into the release as `data/web_dist`.
Dev dependencies: pytest (and the tools for `scripts/make_pi_label.py`); the Pi package is built with `--no-dev`.

---

## 3. Camera Servers

The camera server for each OS is kept for development on a PC; the Pi
package compiles the Linux one itself (section 4).

### 3.1 macOS (Swift)

Uses Swift Package Manager (SwiftPM):

```bash
scripts/build_camera_mac.sh
# Runs: swift build -c release
# Produces: camera/mac/.build/release/camera_server
```

Backend uses:
- AVFoundation (capture)
- IOKit (UVC controls via USB control requests)

### 3.2 Linux (C / V4L2)

```bash
make -C camera/linux
# Produces: camera/linux/camera_server
```

### 3.3 Windows (C / DirectShow)

```bash
camera\windows\build.bat
# Compiles C/DirectShow camera server (run from a VS Developer Command Prompt)
```

---

## 4. Raspberry Pi Package (.deb)

The only release build is `starlock-headless_<version>_arm64.deb`:

```bash
scripts/build_headless_deb.sh        # builds in a Debian bookworm arm64 container
scripts/smoke_test_headless_deb.sh   # installs and runs it in clean bookworm / trixie containers
```

The build compiles `camera_server` from `camera/linux`, builds the React UI
into `data/web_dist`, bundles a standalone Python (python-build-standalone)
with the runtime dependencies only (`--no-dev`), and copies the data files.
Everything lands in `/usr/lib/starlock-headless`; the launcher sets
`STARLOCK_ROOT` to that directory and the `starlock-headless` systemd service
runs it. Install, updates and the ready-made SD card (`user-data`) are
described in `docs/rpi-headless.md`.

---

## 5. Continuous Integration

`.github/workflows/build.yml` builds the `.deb` on an arm64 runner, runs the
smoke test, and uploads the `.deb` and `packaging/headless/user-data` as
artifacts. On a `v*` tag (or a manual run with `create_release`), the release
job attaches both to a GitHub release with checksums.

---

## 6. (Removed)

Desktop builds for macOS, Linux and Windows were removed in November 2026.

---

## 7. Config + Logs Paths

Config and logs are stored in platform-specific locations:

| Platform | Config root |
|----------|------------|
| macOS    | `~/Library/Application Support/ElectronicViewfinder/` |
| Linux    | `$XDG_CONFIG_HOME/electronic-viewfinder/` |
| Windows  | `%APPDATA%/ElectronicViewfinder/` |

On the Pi the service sets `XDG_CONFIG_HOME=/var/lib/starlock-headless/config`.

Files:
- `config.json`
- `logs/evf.log` (rotating)

The app creates directories if missing.

---

## 8. Path Resolution (`evf/paths.py`)

Centralized path resolution handles two modes:

- **Repo** (development, any OS): the repo root, found by walking up from
  `paths.py` to `pyproject.toml`.
- **Release** (the Pi package): `STARLOCK_ROOT`, set by the launcher to
  `/usr/lib/starlock-headless`, laid out as `camera_server`, `data/`,
  `marketing/`.

Functions:
- `tetra3rs_database_path()` — tetra3rs star catalog (`tetra3rs_gaia.bin`)
- `camera_binary()` — platform-specific camera server binary
- `sounds_dir()` — audio files
- `web_dist_dir()` — built React UI (`web/dist` in the repo, `data/web_dist` in a release; with HMR, Vite serves the UI on :5173 instead)
- `title_image()` — in-app branding

---

## 9. Signing

The `.deb` is not signed yet. A signed apt repository is planned in
`SPEC_UPDATES.md`.

---

## 10. Dev Mode (Fast Iteration)

Platform-specific dev scripts:

```bash
scripts/run_dev.sh              # macOS
scripts/run_dev_linux.sh        # Linux
scripts/run_dev_windows.bat     # Windows
```

These run the Python engine in the normal interpreter, spawning the camera
server and using local data files. The engine opens no window: open
`http://localhost:8780/` in a browser.

`scripts/run_mock_camera.sh` launches a mock camera server for testing without hardware.

Launch with `--dev` flag for debug features.

---

## 11. Versioning

### Product versions (all components)

Starlock ships as several components in separate repos: this engine (the
`starlock-headless` Pi package), Starlock Cloud, and the iOS app (Android
later). They share one version scheme:

- **SemVer `MAJOR.MINOR.PATCH`, numbers only.** No `-beta` / `-rc`
  suffixes: iOS's `CFBundleShortVersionString` only takes digits and dots,
  and the Pi and app should show exactly the same string. Staying below
  1.0 says "not finished"; TestFlight is the iOS beta channel. 1.0.0 is the
  first release you sell.
- **`MAJOR.MINOR` is the product release, shared by every component.**
  "Starlock 0.4" means engine 0.4.x, cloud 0.4.x and app 0.4.x. Starting a
  new minor (a feature release) bumps every component to `X.Y.0`, even one
  that didn't change, so users can match them at a glance.
- **`PATCH` is per component.** A cloud hotfix is cloud 0.4.3 while the
  app stays 0.4.1; no empty App Store releases.
- **Compatibility is decided by the API versions, not by matching
  numbers:** the Bonjour TXT `api` and `/api/version` here, the cloud's
  `/v1` path, `protocol_version` for the camera protocol. A breaking API
  change bumps those (and, before 1.0, the minor).
- **Releases are git tags `vX.Y.Z`** in each repo, on the commit whose
  version file says `X.Y.Z`.
- **Build numbers** (iOS `CFBundleVersion`) are a separate, ever-increasing
  counter (the CI run number). Apple always has both: TestFlight shows
  "version (build)", the App Store only the version.
- **Every TestFlight upload bumps the app's `PATCH`**, so testers see
  "0.5.1 (20)", "0.5.2 (21)" rather than the same version with a new build
  number. Several uploads of one version are allowed but hard to tell apart.

Where each component keeps its version (the one place to edit):

| Component | File | Shown as |
|---|---|---|
| Engine / Pi package | `data/VERSION.json` `app_version` (and `pyproject.toml`, kept equal by a test) | `/api/version`, Bonjour TXT `version`, `.deb` `X.Y.Z-1` |
| Starlock Cloud | `Directory.Build.props` `<Version>` | `/healthz`, image tag |
| iOS app | `project.yml` `MARKETING_VERSION` | App Store / TestFlight version |

### `data/VERSION.json`

```json
{
  "app_version": "<x.y.z>",
  "protocol_version": 1,
  "solver_db_version": "tetra3rs_gaia_<hash>_mag8"
}
```

`protocol_version` and `solver_db_version` are stable across minor releases;
`app_version` follows the product scheme above and must equal
`pyproject.toml`'s `version` (checked by `tests/test_version.py`).
Logged at startup (INFO).
