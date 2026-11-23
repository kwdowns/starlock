"""Tests for the Wi-Fi hotspot fallback shipped in the starlock-headless .deb.

packaging/headless/starlock-wifi-fallback (a POSIX sh script, installed as
/usr/lib/starlock-headless/wifi-fallback) is run against a fake `nmcli`, so
no NetworkManager is needed. The fake also replaces `sleep` (no waiting) and
`id` (pretends to be root).
"""

import configparser
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "packaging/headless"
SCRIPT = PKG / "starlock-wifi-fallback"
UNIT = PKG / "starlock-wifi-fallback.service"

needs_sh = pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")

FAKE_NMCLI = r"""#!/bin/sh
d="$FAKE_NM"
for last in "$@"; do :; done
echo "nmcli $*" >> "$d/calls"
case "$*" in
  *"device status"*)
    n=$(cat "$d/n" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$d/n"
    f="$d/devices"
    if [ -f "$d/devices.late" ] && [ "$n" -gt "${FAKE_NM_LATE_AFTER:-9999}" ]; then
        f="$d/devices.late"
    fi
    cat "$f" ;;
  *"-t -f UUID,TYPE connection show") cat "$d/conns" 2>/dev/null ;;
  *"802-11-wireless.mode,connection.autoconnect connection show uuid "*)
    cat "$d/conn_$last" ;;
  *"-g connection.id connection show "*)
    [ -f "$d/profile_$last" ] || exit 10 ;;
  *"-g 802-11-wireless.mode connection show "*)
    cat "$d/mode_$last" 2>/dev/null ;;
  *"-g ipv4.addresses connection show "*)
    cat "$d/addr_$last" 2>/dev/null ;;
  *"connection up"*)
    if [ -f "$d/up_fails" ]; then exit 4; fi
    echo up > "$d/hotspot_up" ;;
  *"connection add"*) touch "$d/profile_starlock-hotspot" ;;
  *"connection modify"*) ;;
esac
exit 0
"""


@pytest.fixture
def nm(tmp_path):
    """A fake NetworkManager: files under tmp_path/nm, scripts under tmp_path/bin."""
    state = tmp_path / "nm"
    state.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "nmcli").write_bytes(FAKE_NMCLI.encode())
    (bin_dir / "sleep").write_bytes(b"#!/bin/sh\nexit 0\n")
    (bin_dir / "id").write_bytes(b"#!/bin/sh\necho 0\n")
    for f in bin_dir.iterdir():
        f.chmod(0o755)

    class Fake:
        def devices(self, text, late=None):
            (state / "devices").write_bytes(text.encode())
            if late:
                (state / "devices.late").write_bytes(late.encode())

        def wifi_profile(self, uuid, mode="infrastructure", autoconnect="yes"):
            with open(state / "conns", "a", newline="\n") as f:
                f.write(f"{uuid}:802-11-wireless\n")
            (state / f"conn_{uuid}").write_bytes(f"{mode}\n{autoconnect}\n".encode())

        def file(self, name, text=""):
            (state / name).write_bytes(text.encode())

        def calls(self):
            p = state / "calls"
            return p.read_text().splitlines() if p.exists() else []

        def hotspot_started(self):
            return (state / "hotspot_up").exists()

        def run(self, *args, **env):
            e = dict(os.environ)
            e["PATH"] = str(bin_dir) + os.pathsep + e["PATH"]
            e["FAKE_NM"] = str(state)
            e["STARLOCK_WIFI_WAIT"] = "3"
            e["STARLOCK_WIFI_WAIT_NONE"] = "1"
            e["STARLOCK_WIFI_EXTRA"] = "0"
            e.update({k: str(v) for k, v in env.items()})
            return subprocess.run(["sh", str(SCRIPT), *args], env=e,
                                  capture_output=True, text=True, timeout=60)

    return Fake()


# ---- the files themselves -------------------------------------------------

def test_script_has_lf_endings_and_a_shebang():
    assert b"\r" not in SCRIPT.read_bytes()
    assert SCRIPT.read_bytes().startswith(b"#!/bin/sh\n")


@needs_sh
def test_script_parses():
    out = subprocess.run(["sh", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


@needs_sh
@pytest.mark.parametrize("name", ["postinst", "prerm", "postrm"])
def test_maintainer_scripts_parse(name):
    text = (PKG / "debian" / name).read_bytes().replace(b"\r\n", b"\n")
    out = subprocess.run(["sh", "-n"], input=text, capture_output=True)
    assert out.returncode == 0, out.stderr.decode()


def test_unit_file():
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    cp.read_string(UNIT.read_text())
    assert cp["Service"]["Type"] == "oneshot"
    assert cp["Service"]["ExecStart"] == "/usr/lib/starlock-headless/wifi-fallback run"
    assert cp["Install"]["WantedBy"] == "multi-user.target"
    assert cp["Unit"]["After"] == "NetworkManager.service"
    assert cp["Unit"]["Wants"] == "NetworkManager.service"
    # No NetworkManager (containers, other network stacks): skipped, not failed.
    assert cp["Unit"]["ConditionPathExists"] == "/usr/bin/nmcli"
    # Must outlast the longest wait (45 s + 45 s extra) plus three hotspot tries.
    assert int(cp["Service"]["TimeoutStartSec"]) >= 45 + 45 + 3 * 35


def test_build_script_installs_unit_and_script():
    build = (ROOT / "scripts/build_headless_deb.sh").read_text()
    assert re.search(
        r'install -D -m 755 "\$PKG_DIR/starlock-wifi-fallback" "\$APP/wifi-fallback"', build)
    assert "usr/lib/systemd/system/starlock-wifi-fallback.service" in build


def test_maintainer_scripts_enable_and_clean_up():
    post = (PKG / "debian/postinst").read_text()
    assert 'systemctl enable "$FALLBACK_UNIT"' in post
    assert 'wifi-fallback" ensure-profile' in post
    # A hand-installed unit in /etc is left alone, with a note.
    assert "FALLBACK_OVERRIDE" in post and "overrides" in post
    assert 'systemctl disable "$FALLBACK_UNIT"' in (PKG / "debian/prerm").read_text()
    postrm = (PKG / "debian/postrm").read_text()
    assert "nmcli connection delete starlock-hotspot" in postrm


# ---- behaviour against a fake NetworkManager --------------------------------

@needs_sh
@pytest.mark.skipif(shutil.which("nmcli") is not None, reason="real nmcli present")
def test_without_networkmanager_nothing_happens(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "id").write_bytes(b"#!/bin/sh\necho 0\n")
    env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"])
    out = subprocess.run(["sh", str(SCRIPT), "run"], env=env, capture_output=True, text=True)
    assert out.returncode == 0
    assert "nothing to do" in out.stdout
    out = subprocess.run(["sh", str(SCRIPT), "ensure-profile"], env=env,
                         capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout == ""


@needs_sh
def test_connected_wifi_is_left_alone(nm):
    nm.devices("wlan0:wifi:connected:Home\neth0:ethernet:unavailable:\nlo:loopback:unmanaged:\n")
    nm.wifi_profile("u1")
    out = nm.run()
    assert out.returncode == 0, out.stderr
    assert "no hotspot" in out.stdout
    assert not nm.hotspot_started()


@needs_sh
def test_connected_wifi_with_colon_in_name(nm):
    nm.devices("wlan0:wifi:connected:Cafe\\: guest\n")
    assert nm.run().returncode == 0
    assert not nm.hotspot_started()


@needs_sh
def test_wired_connection_is_left_alone(nm):
    nm.devices("wlan0:wifi:disconnected:\neth0:ethernet:connected:Wired connection 1\n")
    nm.wifi_profile("u1")
    out = nm.run()
    assert out.returncode == 0
    assert "wired" in out.stdout
    assert not nm.hotspot_started()


@needs_sh
def test_externally_managed_link_counts_as_connected(nm):
    nm.devices("wlan0:wifi:connected (externally):\n")
    assert nm.run().returncode == 0
    assert not nm.hotspot_started()


@needs_sh
def test_known_wifi_not_found_starts_hotspot_after_the_long_wait(nm):
    nm.devices("wlan0:wifi:disconnected:\neth0:ethernet:unavailable:\n")
    nm.wifi_profile("u1")
    nm.file("profile_starlock-hotspot")
    out = nm.run()
    assert out.returncode == 0, out.stdout + out.stderr
    assert "waiting up to 3s" in out.stdout
    assert nm.hotspot_started()
    up = [c for c in nm.calls() if "connection up" in c]
    assert up == ["nmcli --wait 30 connection up starlock-hotspot ifname wlan0"]


@needs_sh
def test_no_saved_wifi_waits_only_briefly(nm):
    nm.devices("wlan0:wifi:disconnected:\neth0:ethernet:unavailable:\n")
    # Only an access-point profile and a disabled one: neither is a known network.
    nm.wifi_profile("ap", mode="ap", autoconnect="no")
    nm.wifi_profile("off", autoconnect="no")
    nm.file("profile_starlock-hotspot")
    out = nm.run()
    assert out.returncode == 0
    assert "waiting up to 1s" in out.stdout, "; ".join(nm.calls())
    assert nm.hotspot_started()


@needs_sh
def test_slow_connection_gets_extra_time(nm):
    nm.devices("wlan0:wifi:connecting (getting IP configuration):Home\n",
               late="wlan0:wifi:connected:Home\n")
    nm.wifi_profile("u1")
    nm.file("profile_starlock-hotspot")
    # Connected after many polls: more than the 3 s wait, within the extra time.
    out = nm.run(STARLOCK_WIFI_EXTRA=100, FAKE_NM_LATE_AFTER=60)
    assert out.returncode == 0
    assert not nm.hotspot_started(), out.stdout
    assert "still being made" in out.stdout


@needs_sh
def test_slow_connection_without_extra_time_loses_to_the_hotspot(nm):
    nm.devices("wlan0:wifi:connecting (getting IP configuration):Home\n",
               late="wlan0:wifi:connected:Home\n")
    nm.wifi_profile("u1")
    nm.file("profile_starlock-hotspot")
    out = nm.run(STARLOCK_WIFI_EXTRA=0, FAKE_NM_LATE_AFTER=60)
    assert out.returncode == 0
    assert nm.hotspot_started()


@needs_sh
def test_wrong_password_is_not_progress(nm):
    nm.devices("wlan0:wifi:connecting (need authentication):Home\n",
               late="wlan0:wifi:connected:Home\n")
    nm.wifi_profile("u1")
    nm.file("profile_starlock-hotspot")
    out = nm.run(STARLOCK_WIFI_EXTRA=100, FAKE_NM_LATE_AFTER=60)
    assert "still being made" not in out.stdout
    assert nm.hotspot_started()


@needs_sh
def test_no_wifi_device(nm):
    nm.devices("eth0:ethernet:unavailable:\nlo:loopback:unmanaged:\n")
    out = nm.run()
    assert out.returncode == 0
    assert "no Wi-Fi device" in out.stdout
    assert not nm.hotspot_started()


@needs_sh
def test_unmanaged_wifi_device_is_left_alone(nm):
    nm.devices("wlan0:wifi:unmanaged:\n")
    out = nm.run()
    assert out.returncode == 0
    assert not nm.hotspot_started()
    assert "not managed" in out.stdout


@needs_sh
def test_missing_profile_is_created_before_starting(nm):
    nm.devices("wlan0:wifi:disconnected:\n")
    out = nm.run()
    assert out.returncode == 0, out.stdout
    calls = nm.calls()
    add = next(c for c in calls if "connection add" in c)
    assert "con-name starlock-hotspot" in add and "autoconnect no" in add
    assert "ipv4.addresses 192.168.77.1/24" in add and "802-11-wireless.mode ap" in add
    assert "ssid Starlock-" in add
    assert calls.index(add) < next(i for i, c in enumerate(calls) if "connection up" in c)


@needs_sh
def test_failing_hotspot_exits_nonzero_after_three_tries(nm):
    nm.devices("wlan0:wifi:disconnected:\n")
    nm.file("profile_starlock-hotspot")
    nm.file("up_fails")
    out = nm.run()
    assert out.returncode == 1
    assert len([c for c in nm.calls() if "connection up" in c]) == 3
    assert "rfkill" in out.stdout


@needs_sh
def test_ensure_profile_creates_when_missing(nm):
    nm.devices("wlan0:wifi:disconnected:\n")
    out = nm.run("ensure-profile")
    assert out.returncode == 0
    assert any("connection add" in c for c in nm.calls())
    assert not nm.hotspot_started()


@needs_sh
def test_ensure_profile_keeps_an_existing_one(nm):
    nm.devices("wlan0:wifi:disconnected:\n")
    nm.file("profile_starlock-hotspot")
    assert nm.run("ensure-profile").returncode == 0
    assert not any("connection add" in c or "connection modify" in c for c in nm.calls())


@needs_sh
def test_ensure_profile_adopts_the_ready_made_cards_hotspot(nm):
    nm.devices("wlan0:wifi:connected:hotspot\n")
    nm.file("profile_hotspot")
    nm.file("mode_hotspot", "ap\n")
    nm.file("addr_hotspot", "192.168.77.1/24\n")
    out = nm.run("ensure-profile")
    assert out.returncode == 0
    calls = nm.calls()
    mod = next(c for c in calls if "connection modify" in c)
    assert "connection.id starlock-hotspot" in mod and "connection.autoconnect no" in mod
    assert not any("connection add" in c for c in calls)


@needs_sh
def test_ensure_profile_does_not_adopt_someone_elses_hotspot(nm):
    nm.devices("wlan0:wifi:disconnected:\n")
    nm.file("profile_hotspot")
    nm.file("mode_hotspot", "ap\n")
    nm.file("addr_hotspot", "10.42.0.1/24\n")
    assert nm.run("ensure-profile").returncode == 0
    calls = nm.calls()
    assert not any("connection modify" in c for c in calls)
    assert any("connection add" in c for c in calls)


@needs_sh
def test_usage_error():
    out = subprocess.run(["sh", str(SCRIPT), "bogus"], capture_output=True, text=True)
    assert out.returncode == 2
