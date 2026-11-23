#!/usr/bin/env bash
# Copyright (C) 2026 Arun Venkataswamy
#
# This file is part of Starlock.
#
# Starlock is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Starlock is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Starlock. If not, see <https://www.gnu.org/licenses/>.

# Install-and-run smoke test for the starlock-headless .deb in clean Debian
# containers (no systemd, no camera). Checks that apt resolves the
# dependencies, postinst creates the `starlock` user in `video`, the Wi-Fi
# fallback is installed and harmless without NetworkManager, and the
# engine started as that user loads the star database and serves
# /api/version.
#
# Usage: scripts/smoke_test_headless_deb.sh [build/starlock-headless_*_arm64.deb] [release...]
#        (releases default to: bookworm trixie)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DEB="${1:-}"
if [ -z "$DEB" ]; then
    DEB="$(ls "$REPO_ROOT"/build/starlock-headless_*_arm64.deb 2>/dev/null | head -1)"
fi
[ -f "$DEB" ] || { echo "ERROR: no .deb found (run scripts/build_headless_deb.sh)" >&2; exit 1; }
shift || true
RELEASES=("$@")
[ ${#RELEASES[@]} -gt 0 ] || RELEASES=(bookworm trixie)

DEB_DIR="$(cd "$(dirname "$DEB")" && pwd)"
DEB_NAME="$(basename "$DEB")"

read -r -d '' INNER <<'EOF' || true
set -euo pipefail
apt-get update -qq >/dev/null
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl "/deb/$DEB_NAME" >/tmp/apt.log 2>&1 \
    || { tail -30 /tmp/apt.log; exit 1; }
id -nG starlock | grep -qw video || { echo "FAIL: starlock not in video"; exit 1; }
[ -f /usr/lib/systemd/system/starlock-wifi-fallback.service ] || { echo "FAIL: no Wi-Fi fallback unit"; exit 1; }
# No NetworkManager in the container: the fallback must say so and exit 0.
/usr/lib/starlock-headless/wifi-fallback run | grep -q "nothing to do"     || { echo "FAIL: Wi-Fi fallback without NetworkManager"; exit 1; }
su -s /bin/sh starlock -c 'cd /var/lib && HOME=/tmp XDG_CONFIG_HOME=/tmp/c XDG_STATE_HOME=/tmp/s starlock-headless' \
    >/tmp/run.log 2>&1 &
version=""
for _ in $(seq 1 60); do
    version="$(curl -sf http://127.0.0.1:8780/api/version || true)"
    [ -n "$version" ] && break
    sleep 1
done
echo "  /api/version: ${version:-<no response>}"
grep -q "tetra3rs database loaded" /tmp/run.log || { echo "FAIL: star database not loaded"; tail -30 /tmp/run.log; exit 1; }
if grep -q Traceback /tmp/run.log; then echo "FAIL: traceback in log"; tail -40 /tmp/run.log; exit 1; fi
case "$version" in *'"app": "starlock"'*) ;; *) echo "FAIL: /api/version"; tail -30 /tmp/run.log; exit 1 ;; esac
EOF

status=0
for rel in "${RELEASES[@]}"; do
    echo "==> debian:$rel"
    if docker run --rm --platform linux/arm64 -e DEB_NAME="$DEB_NAME" \
        -v "$DEB_DIR:/deb:ro" "debian:$rel" bash -c "$INNER"; then
        echo "  PASS"
    else
        echo "  FAIL"
        status=1
    fi
done
exit $status
