---
title: Install Starlock
---

# Install Starlock

Starlock runs on macOS, Windows, and Linux. Pick your platform below, and you'll be up and running in a few minutes.

## Download

Grab the latest release from GitHub:

[:material-download: Download Starlock](https://github.com/kwdowns/starlock/releases/latest){ .md-button .md-button--primary }

| Platform | What to download |
|---|---|
| **Windows** | `Starlock-windows-x64-setup.exe` |
| **macOS** (Apple Silicon, M1/M2/M3/M4) | `Starlock-macOS-arm64.dmg` |
| **Linux** | `Starlock-linux-x86_64.AppImage` |
| **Raspberry Pi 3A+ / 4 / 5** (headless, beta) | `starlock-headless_<version>_arm64.deb`, plus `user-data` for the ready-made SD card ([guide](rpi-headless.md)) |

---

## Windows

### Install

1. Run the downloaded `Starlock-windows-x64-setup.exe`
2. Click **Yes** when Windows asks for permission to install
3. Follow the installer (the defaults are fine)
4. Starlock appears in your **Start Menu**

### First launch: firewall prompt

The first time Starlock starts, Windows Firewall will ask if you want to allow Starlock to communicate on your network. **Tick "Private networks"** and click **Allow access**. This lets other devices on your Wi-Fi (your phone for the mobile companion view, and telescope apps like SkySafari) connect to Starlock.

!!! note "If Starlock won't start at all"
    If you see an error about a missing `.dll` file, you may need to install the [Microsoft Visual C++ Runtime](https://aka.ms/vs/17/release/vc_redist.x64.exe) (a one-time, free download from Microsoft). Most Windows 10/11 machines already have it.

---

## macOS

### Install

1. Open the downloaded `.dmg` file
2. Drag **Starlock** into your **Applications** folder

### First launch: security prompts

Because Starlock is a free, open-source app and isn't sold through the Mac App Store, macOS will show a couple of prompts the first time you open it. This is normal.

**"Starlock is damaged and can't be opened. You should move it to the Bin."**

The app is fine — this is macOS Gatekeeper refusing to launch an unsigned app that your browser flagged as "downloaded from the internet". The dialog has only **Cancel** and **Move to Bin**, with no "Open Anyway" option.

To fix it, open **Terminal** and run:

```bash
xattr -cr /Applications/Starlock.app
```

That removes the quarantine flag your browser set. Double-click Starlock again — it'll launch normally. You only need to do this once.

If you instead see **"can't be opened because Apple cannot check it for malicious software"** (older quarantine dialog with an "Open Anyway" path), that one you can solve in **System Settings → Privacy & Security** — scroll down and click **Open Anyway**. Either path lands at the same end state.

**Camera access.** macOS will ask if Starlock can use your camera. Click **Allow**. Starlock needs the camera to see the stars.

**Network access.** macOS will ask if Starlock can accept incoming network connections. Click **Allow**. This lets other devices on your Wi-Fi (your phone for the mobile companion view, and telescope apps like SkySafari) connect to Starlock.

---

## Linux

### Before you start: system packages

Starlock ships its own window toolkit (Qt/Chromium) inside the AppImage,
so there's nothing GTK- or WebKit-related to install. You do need two
small system pieces: **FUSE** (so the AppImage format can mount itself
on first launch) and **GStreamer** (so the lock / lost / GOTO audio
alerts can play). Most desktop Linux installs already have both, but on
a fresh or minimal system install them first:

**Ubuntu / Debian / Mint / Pop!_OS:**

```bash
sudo apt install libfuse2 gstreamer1.0-tools
```

**Fedora:**

```bash
sudo dnf install fuse gstreamer1
```

**Arch / Manjaro:**

```bash
sudo pacman -S fuse2 gst-plugins-base
```

If FUSE is missing, the AppImage refuses to start with a message about
mounting. If GStreamer is missing, you'll see "could not open audio
device" warnings but the rest of the app still works.

!!! note "What about PyGObject / GTK / WebKit2GTK?"
    Older versions of Starlock used pywebview's GTK backend and required
    `python3-gi`, `gir1.2-webkit2-4.1`, etc. The Linux build switched to
    Qt — none of those packages are needed anymore.

### Install

1. Download the `.AppImage` file
2. Make it executable and run it:
   ```bash
   chmod +x Starlock-linux-*.AppImage
   ./Starlock-linux-*.AppImage
   ```

### Camera permission

If Starlock can't find your camera, you may need to add yourself to the `video` group (this is a one-time step):

```bash
sudo usermod -aG video "$USER"
```

Log out and back in for the change to take effect.

---

## Raspberry Pi (headless)

On a Raspberry Pi 3A+, 4 or 5, install the `starlock-headless` package
(`starlock-headless_<version>_arm64.deb`) instead of the Linux AppImage.
There are two ways:

- **Install with apt** on a Pi you set up yourself, on your own Wi-Fi.
- **Ready-made Starlock SD card:** flash Raspberry Pi OS Lite, copy the
  release's `.deb` and `user-data` onto the card, and boot. The Pi becomes
  a dedicated box with its own Wi-Fi hotspot. You can
  [print a label](rpi-headless.md#label-for-a-ready-made-pi) for the box
  with the hotspot details and a QR code that opens Starlock.

It has no window: it runs in the background as a service, and you use
it from a phone browser over Wi-Fi. The Pi's LEDs show whether Starlock
needs attention (red) or is working (green).

See **[Running Starlock headless on a Raspberry Pi](rpi-headless.md)**
for install, updates and troubleshooting.

---

## Before you launch

You can launch Starlock with or without a camera plugged in. If you start it without one, the live-view area shows a **"Camera not connected"** placeholder with a **Retry** button — plug the camera in, click Retry, and Starlock picks up where it would have started. The rest of the app (Settings, Connectivity, the "What to See" catalog) is fully usable in the meantime, so you can plan a session indoors before stepping out to the scope.

When Starlock starts, you'll see a brief loading screen, then the main window with a live camera feed on the left (or the camera-not-connected placeholder) and a step-by-step panel on the right. The panel walks you through alignment. No prior experience needed.

## Phone companion

Starlock has a built-in mobile view so you can check your push direction from your phone while you're at the eyepiece. No app to install, just scan a QR code.

1. Open the **Settings** section in Starlock's side panel
2. Point your phone's camera at the **QR code** shown there
3. Tap the link that pops up; a live view opens in your phone's browser

Your phone and laptop need to be on the same Wi-Fi network. That's it.

!!! tip "If your phone can't connect"
    You probably clicked "Deny" or "Cancel" on the firewall/network prompt when Starlock first launched. See the macOS or Windows sections above for how to fix it.

---

## What's next

Now that Starlock is running, connect it to Stellarium so you can pick targets from a sky chart and have Starlock guide you to them. See [Stellarium Setup](stellarium-setup.md).
