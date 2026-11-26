# Copyright (C) 2026 Arun Venkataswamy
# Copyright (C) 2026 Kyle Downs
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

"""Configuration manager — JSON persistence with defaults and versioning."""

import ipaddress
import json
import logging
import os
import platform
import re
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_VERSION = 1

# The web server's default port until it moved to 8780 (8765 clashes with
# other apps). A config that still holds it is moved to the new default.
_OLD_DEFAULT_WEB_PORT = 8765

DEFAULT_CONFIG = {
    "version": CONFIG_VERSION,
    "solver": {"min_matches": 8, "max_prob": 0.2},
    "camera": {"exposure": None, "gain": None, "extra_camera_ids": []},
    # finder_rotation_v2: finder_rotation uses the corrected (unmirrored)
    # image-angle convention; older configs are converted once on load.
    "calibration": {"finder_rotation": 0.0, "sync_d_body": None, "finder_rotation_v2": True},
    # "altaz" or "eq" — which axes the push-to guidance is given in.
    "mount": {"mode": "altaz"},
    "logging": {"verbose": False},
    "audio": {"enabled": True},
    # Headless Pi status LED (see evf/engine/status_led.py).
    "led": {"enabled": True},
    # Headless Pi CPU clock cap (see evf/engine/cpufreq.py). Solves take
    # tens of ms per exposure, so the CPU can run slower.
    "power": {"cpu_cap": True, "max_freq_mhz": 1200},
    # Dwell log of what the scope pointed at (see evf/engine/observation_log.py).
    "observation_log": {"enabled": True, "dwell_s": 30, "radius_deg": 1.0},
    "lx200": {"epoch": "jnow"},
    # Address of the computer running Stellarium, for its Remote Control
    # plugin (HTTP, port 8090). Empty = use the computer that is connected
    # to the telescope server (see evf/stellarium/server.py).
    "stellarium": {"remote_control_host": ""},
    "webserver": {"port": 8780},
    # Bonjour / mDNS advertising of the web server (see evf/discovery.py).
    "discovery": {"enabled": True},
    # Stable random id for this install, generated on first use. Lets apps
    # tell two Starlocks apart and recognise one that changed IP.
    "device": {"id": None},
    # Optional Starlock Cloud (see evf/cloud/). The phone app can pass another
    # (https) address along with a pairing code, e.g. the dev service.
    "cloud": {"base_url": "https://api.starlock.app"},
    "location": {"latitude": None, "longitude": None},
    # Horizon mask: 16 direction sectors (N, NNE, ...), each a 9-bit mask of
    # 10° altitude bands (bit 0 = 0-10°) hidden by trees or buildings. The
    # default hides everything below 20°. See specs/start/SPEC_HORIZON_MOUNT_MODEL.md.
    "horizon": {"obscured": [3] * 16},
    # Saved observing sites and equipment, and which are in use (see
    # evf/config/observing.py and specs/start/SPEC_EQUIPMENT_SITES.md).
    "observing": {
        "sites": [], "telescopes": [], "eyepieces": [], "finders": [],
        "current": {"site_id": None, "telescope_id": None,
                    "eyepiece_id": None, "finder_id": None},
    },
}

HORIZON_SECTORS = 16
HORIZON_BANDS = 9
DEFAULT_HORIZON = [3] * HORIZON_SECTORS


def validate_horizon(value: object) -> list[int]:
    """Check a horizon mask (16 ints, each 0-511); raises ValueError."""
    if not isinstance(value, list) or len(value) != HORIZON_SECTORS:
        raise ValueError(f"horizon must be a list of {HORIZON_SECTORS} integers")
    out = []
    for v in value:
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < (1 << HORIZON_BANDS):
            raise ValueError(f"each horizon sector must be an integer 0-{(1 << HORIZON_BANDS) - 1}")
        out.append(v)
    return out


def _default_config_dir() -> Path:
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(appdata) / "ElectronicViewfinder"
    if platform.system() == "Linux":
        xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        return Path(xdg) / "electronic-viewfinder"
    return Path.home() / "Library" / "Application Support" / "ElectronicViewfinder"


_DEFAULT_DIR = _default_config_dir()

_HOST_LABEL = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")
_MAX_HOST_LEN = 253


def normalize_host(value: object) -> str:
    """Check a host name or IPv4 / IPv6 literal and return it cleaned up.

    Surrounding spaces, ``[ ]`` around an IPv6 literal and a trailing dot are
    dropped. An empty value (or None) returns "". Raises ValueError for
    anything else: URLs, ``host:port``, spaces, over-long names.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("address must be text")
    host = value.strip()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if not host:
        return ""
    if len(host) > _MAX_HOST_LEN:
        raise ValueError("address is too long")
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    name = host.rstrip(".")
    if name and all(_HOST_LABEL.match(label) for label in name.split(".")):
        return name
    raise ValueError(
        "enter a computer name or IP address, such as 192.168.1.20 "
        "(no http:// and no port)"
    )


class ConfigManager:
    """Load, save, and access application configuration.

    Config path: ~/Library/Application Support/ElectronicViewfinder/config.json
    """

    def __init__(self, config_dir: Path | None = None) -> None:
        self._dir = config_dir or _DEFAULT_DIR
        self._path = self._dir / "config.json"
        self._data: dict = {}
        self._dirty = False
        # Guards _data and the file: web requests run on their own threads.
        self._lock = threading.RLock()
        # > 0 inside batch(): changes are saved once, when it ends.
        self._batch_depth = 0
        self._load()

    # -- persistence ----------------------------------------------------------

    def _migrate_old_default_port(self) -> None:
        web = self._data.get("webserver")
        if isinstance(web, dict) and web.get("port") == _OLD_DEFAULT_WEB_PORT:
            web["port"] = DEFAULT_CONFIG["webserver"]["port"]
            self._dirty = True
            logger.info("Web server port moved from the old default %d to %d",
                        _OLD_DEFAULT_WEB_PORT, web["port"])

    def _migrate_finder_rotation(self) -> None:
        """Convert a finder_rotation saved before the mirror fix.

        The old calibration measured image angles counter-clockwise, so the
        saved value is the negative of the real one. Must run before
        defaults are merged in, which would add the v2 marker.
        """
        cal = self._data.get("calibration")
        if not isinstance(cal, dict) or cal.get("finder_rotation_v2"):
            return
        old = cal.get("finder_rotation")
        if isinstance(old, (int, float)):
            cal["finder_rotation"] = (-float(old)) % 360.0
            logger.info("finder_rotation converted from %.1f to %.1f (mirror fix)",
                        old, cal["finder_rotation"])
        cal["finder_rotation_v2"] = True
        self._dirty = True

    def _migrate_observing(self) -> None:
        """Check the saved sites and equipment, or make them the first time.

        Runs before defaults are merged in, so a missing ``observing`` key
        still means a config from before sites existed.
        """
        from evf.config import observing

        if "observing" not in self._data:
            loc = self._data.get("location")
            lat = loc.get("latitude") if isinstance(loc, dict) else None
            lon = loc.get("longitude") if isinstance(loc, dict) else None
            hz = self._data.get("horizon")
            mask = hz.get("obscured") if isinstance(hz, dict) else None
            self._data["observing"] = observing.migrate(lat, lon, mask)
            self._dirty = True
            return
        clean, changed = observing.sanitize(self._data["observing"])
        self._data["observing"] = clean
        if changed:
            self._dirty = True

    def _load(self) -> None:
        if self._path.exists():
            try:
                with open(self._path) as f:
                    self._data = json.load(f)
                if self._data.get("version") != CONFIG_VERSION:
                    logger.warning(
                        "Config version mismatch (got %s, expected %s) — using defaults",
                        self._data.get("version"),
                        CONFIG_VERSION,
                    )
                    self._data = _deep_copy(DEFAULT_CONFIG)
                    self._dirty = True
                else:
                    self._migrate_finder_rotation()
                    self._migrate_observing()
                    # Merge in any missing keys from defaults
                    self._data = _merge_defaults(DEFAULT_CONFIG, self._data)
                    self._migrate_old_default_port()
                logger.info("Loaded config from %s", self._path)
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("Failed to read config (%s) — using defaults", exc)
                self._data = _deep_copy(DEFAULT_CONFIG)
                self._dirty = True
        else:
            logger.info("No config file found — creating defaults at %s", self._path)
            self._data = _deep_copy(DEFAULT_CONFIG)
            self._dirty = True
        if self._dirty:
            self.save()

    def save(self) -> None:
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w") as f:
                json.dump(self._data, f, indent=2)
                f.write("\n")
            self._dirty = False
        logger.debug("Config saved to %s", self._path)

    @contextmanager
    def batch(self):
        """Hold the config lock and save once at the end, so several
        changes (a site's location and horizon) land in one write."""
        with self._lock:
            self._batch_depth += 1
            try:
                yield self
            finally:
                self._batch_depth -= 1
                if self._batch_depth == 0 and self._dirty:
                    self.save()

    def _changed(self) -> None:
        self._dirty = True
        if self._batch_depth == 0:
            self.save()

    # -- getters / setters ----------------------------------------------------

    def get(self, section: str, key: str):
        with self._lock:
            return self._data.get(section, {}).get(key)

    def set(self, section: str, key: str, value) -> None:
        with self._lock:
            if section not in self._data:
                self._data[section] = {}
            if self._data[section].get(key) != value:
                self._data[section][key] = value
                self._changed()

    # -- convenience properties -----------------------------------------------

    @property
    def min_matches(self) -> int:
        return self.get("solver", "min_matches")

    @min_matches.setter
    def min_matches(self, value: int) -> None:
        self.set("solver", "min_matches", value)

    @property
    def max_prob(self) -> float:
        return self.get("solver", "max_prob")

    @max_prob.setter
    def max_prob(self, value: float) -> None:
        self.set("solver", "max_prob", value)

    @property
    def exposure(self) -> int:
        return self.get("camera", "exposure")

    @exposure.setter
    def exposure(self, value: int) -> None:
        self.set("camera", "exposure", value)

    @property
    def gain(self) -> int:
        return self.get("camera", "gain")

    @gain.setter
    def gain(self, value: int) -> None:
        self.set("camera", "gain", value)

    @property
    def extra_camera_ids(self) -> list[str]:
        """Additional USB camera allowlist entries as 'vid:pid' hex strings.

        Appended to the camera servers' built-in allowlist via the
        STARLOCK_CAMERA_IDS env var, so a new camera model can be registered
        without recompiling the native camera server.
        """
        return self.get("camera", "extra_camera_ids") or []

    @extra_camera_ids.setter
    def extra_camera_ids(self, value: list[str]) -> None:
        self.set("camera", "extra_camera_ids", value)

    @property
    def finder_rotation(self) -> float:
        return self.get("calibration", "finder_rotation")

    @finder_rotation.setter
    def finder_rotation(self, value: float) -> None:
        self.set("calibration", "finder_rotation", value)

    @property
    def mount_mode(self) -> str:
        """"altaz" or "eq"; anything else reads as the alt-az default."""
        mode = self.get("mount", "mode")
        return mode if mode in ("altaz", "eq") else "altaz"

    @mount_mode.setter
    def mount_mode(self, value: str) -> None:
        if value not in ("altaz", "eq"):
            raise ValueError(f"mount mode must be 'altaz' or 'eq', got {value!r}")
        self.set("mount", "mode", value)

    @property
    def sync_d_body(self) -> list[float] | None:
        return self.get("calibration", "sync_d_body")

    @sync_d_body.setter
    def sync_d_body(self, value: list[float] | None) -> None:
        self.set("calibration", "sync_d_body", value)

    @property
    def has_calibration(self) -> bool:
        """True if both sync_d_body and finder_rotation have been saved."""
        return self.sync_d_body is not None

    @property
    def audio_enabled(self) -> bool:
        return self.get("audio", "enabled")

    @audio_enabled.setter
    def audio_enabled(self, value: bool) -> None:
        self.set("audio", "enabled", value)

    @property
    def led_enabled(self) -> bool:
        return self.get("led", "enabled") is not False

    @property
    def cpu_cap(self) -> bool:
        return self.get("power", "cpu_cap") is not False

    @cpu_cap.setter
    def cpu_cap(self, value: bool) -> None:
        self.set("power", "cpu_cap", bool(value))

    @property
    def max_freq_mhz(self) -> int:
        value = self.get("power", "max_freq_mhz")
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return DEFAULT_CONFIG["power"]["max_freq_mhz"]
        return value

    @property
    def verbose(self) -> bool:
        return self.get("logging", "verbose")

    @verbose.setter
    def verbose(self, value: bool) -> None:
        self.set("logging", "verbose", value)

    @property
    def lx200_epoch(self) -> str:
        """Coordinate epoch reported on the LX200 server: 'jnow' or 'j2000'."""
        return self.get("lx200", "epoch")

    @lx200_epoch.setter
    def lx200_epoch(self, value: str) -> None:
        self.set("lx200", "epoch", value)

    @property
    def stellarium_rc_host(self) -> str:
        """Address of the computer running Stellarium ("" = use the connected
        client's address). Hand-edited garbage in config.json reads as ""."""
        try:
            return normalize_host(self.get("stellarium", "remote_control_host"))
        except ValueError:
            return ""

    @stellarium_rc_host.setter
    def stellarium_rc_host(self, value: str | None) -> None:
        self.set("stellarium", "remote_control_host", normalize_host(value))

    @property
    def web_port(self) -> int:
        return self.get("webserver", "port")

    @web_port.setter
    def web_port(self, value: int) -> None:
        if not (1024 <= value <= 65535):
            raise ValueError(f"Web port must be between 1024 and 65535, got {value}")
        self.set("webserver", "port", value)

    @property
    def web_allowed_hosts(self) -> list[str]:
        """Extra host names the web server answers to, besides IPs and LAN
        names: e.g. a home DNS name behind a reverse proxy. Hand-edited in
        config.json (``webserver.allowed_hosts``); ``*.example.com`` matches
        any subdomain."""
        value = self.get("webserver", "allowed_hosts")
        if not isinstance(value, list):
            return []
        return [str(h).strip().lower().rstrip(".") for h in value if str(h).strip()]

    @property
    def location(self) -> tuple[float, float] | None:
        """Return (latitude_deg, longitude_deg) or None if unset."""
        lat = self.get("location", "latitude")
        lon = self.get("location", "longitude")
        if lat is None or lon is None:
            return None
        return (float(lat), float(lon))

    @location.setter
    def location(self, value: tuple[float, float] | None) -> None:
        if value is None:
            with self.batch():
                self.set("location", "latitude", None)
                self.set("location", "longitude", None)
            return
        lat, lon = value
        if not (-90.0 <= lat <= 90.0):
            raise ValueError(f"latitude must be in [-90, 90], got {lat}")
        if not (-180.0 <= lon <= 180.0):
            raise ValueError(f"longitude must be in [-180, 180], got {lon}")
        with self.batch():
            self.set("location", "latitude", float(lat))
            self.set("location", "longitude", float(lon))

    @property
    def horizon(self) -> list[int]:
        """The horizon mask; the default for a missing or broken value."""
        try:
            return validate_horizon(self.get("horizon", "obscured"))
        except ValueError:
            return list(DEFAULT_HORIZON)

    @horizon.setter
    def horizon(self, value: list[int] | None) -> None:
        self.set("horizon", "obscured",
                 list(DEFAULT_HORIZON) if value is None else validate_horizon(value))

    @property
    def observing(self) -> dict:
        """Saved sites and equipment and the ones in use (a copy). Change
        them through evf.config.observing.ObservingLibrary."""
        with self._lock:
            return _deep_copy(self._data["observing"])

    @observing.setter
    def observing(self, value: dict) -> None:
        with self._lock:
            if self._data.get("observing") != value:
                self._data["observing"] = _deep_copy(value)
                self._changed()

    @property
    def observation_log_enabled(self) -> bool:
        return self.get("observation_log", "enabled") is not False

    @observation_log_enabled.setter
    def observation_log_enabled(self, value: bool) -> None:
        self.set("observation_log", "enabled", bool(value))

    @property
    def observation_dwell_s(self) -> float:
        return self._positive("observation_log", "dwell_s")

    @property
    def observation_radius_deg(self) -> float:
        return self._positive("observation_log", "radius_deg")

    @property
    def observation_frame_limits(self) -> tuple[int, int] | None:
        """(quota, minimum free disk) in bytes for the frame kept with each
        log entry, or None when frames are off. ``observation_log.frames``,
        ``frame_quota_mb`` (default 2048) and ``min_free_mb`` (default 1024)."""
        if self.get("observation_log", "frames") is False:
            return None

        def mb(key: str, default: int) -> int:
            value = self.get("observation_log", key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                value = default
            return int(value * 1024 * 1024)

        return mb("frame_quota_mb", 2048), mb("min_free_mb", 1024)

    @property
    def cloud_base_url(self) -> str | None:
        value = self.get("cloud", "base_url")
        return value if isinstance(value, str) and value.strip() else None

    @property
    def discovery_enabled(self) -> bool:
        return self.get("discovery", "enabled") is not False

    @property
    def device_id(self) -> str:
        """This install's id, created and saved the first time it's read."""
        value = self.get("device", "id")
        if isinstance(value, str) and value:
            return value
        value = uuid.uuid4().hex
        self.set("device", "id", value)
        return value

    def _positive(self, section: str, key: str) -> float:
        value = self.get(section, key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            return float(DEFAULT_CONFIG[section][key])
        return float(value)

    @property
    def dir(self) -> Path:
        """Directory holding config.json (and the observation log database)."""
        return self._dir

    @property
    def path(self) -> Path:
        return self._path

    @property
    def data(self) -> dict:
        with self._lock:
            return _deep_copy(self._data)


def _deep_copy(d: dict) -> dict:
    return json.loads(json.dumps(d))


def _merge_defaults(defaults: dict, current: dict) -> dict:
    """Recursively merge missing keys from defaults into current."""
    merged = dict(current)
    for key, default_val in defaults.items():
        if key not in merged:
            merged[key] = _deep_copy(default_val) if isinstance(default_val, dict) else default_val
        elif isinstance(default_val, dict) and isinstance(merged[key], dict):
            merged[key] = _merge_defaults(default_val, merged[key])
    return merged
