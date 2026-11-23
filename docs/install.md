---
title: Install Starlock
---

# Install Starlock

Starlock runs on a **Raspberry Pi 3A+, 4 or 5** as the `starlock-headless`
package. It runs in the background as a service, and you use it from a
phone, tablet or laptop browser over Wi-Fi, or from the Starlock phone
apps. The Pi's LEDs show whether Starlock needs attention (red) or is
working (green).

[:material-download: Download Starlock](https://github.com/kwdowns/starlock/releases/latest){ .md-button .md-button--primary }

From the release, download `starlock-headless_<version>_arm64.deb`, plus
`user-data` if you want the ready-made SD card. There are two ways to set
up the Pi:

- **Install with apt** on a Pi you set up yourself, on your own Wi-Fi.
- **Ready-made Starlock SD card:** flash Raspberry Pi OS Lite, copy the
  release's `.deb` and `user-data` onto the card, and boot. The Pi becomes
  a dedicated box with its own Wi-Fi hotspot. You can
  [print a label](rpi-headless.md#label-for-a-ready-made-pi) for the box
  with the hotspot details and a QR code that opens Starlock.

See **[Running Starlock headless on a Raspberry Pi](rpi-headless.md)**
for install, updates and troubleshooting.

!!! note "Desktop apps"
    Starlock no longer ships desktop apps for Windows, macOS or Linux. The
    Raspberry Pi package is the only supported way to run it.

## What's next

Once Starlock is running, connect it to Stellarium so you can pick targets
from a sky chart and have Starlock guide you to them. See
[Stellarium Setup](stellarium-setup.md), or
[SkySafari & Other Apps](skysafari-setup.md) for phone planetariums.
