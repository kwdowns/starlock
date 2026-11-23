"""How well the Pi hears its Wi-Fi network, for a "weak signal" warning.

Backyard use often puts the scope at the edge of the home Wi-Fi. A weak
link shows up as a laggy live view and dropped connections; telling the
user why (and what to do) beats leaving them guessing.

Reads ``/proc/net/wireless`` (Linux cfg80211; no subprocess, no extra
packages) at most once a second, smooths over ``WINDOW_S`` and applies
hysteresis so the warning doesn't flicker. Returns None where there's no
Wi-Fi client link to measure: desktop OSes, Ethernet, or the Pi running
its own hotspot (an access point has no single signal to report).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from pathlib import Path

PROC_PATH = Path("/proc/net/wireless")
WINDOW_S = 20.0
SAMPLE_S = 1.0
# dBm thresholds on the smoothed level.
GOOD_DBM = -60
FAIR_DBM = -70
WEAK_DBM = -78
# Warn below this; clear only above CLEAR_DBM.
WARN_DBM = -75
CLEAR_DBM = -72


def read_levels(path: Path = PROC_PATH) -> dict[str, float]:
    """Signal level in dBm per wireless interface, e.g. {"wlan0": -69.0}.

    Interfaces reporting 0 or a positive level (access-point mode, or no
    association) are left out.
    """
    try:
        lines = path.read_text().splitlines()[2:]
    except OSError:
        return {}
    out: dict[str, float] = {}
    for line in lines:
        name, _, rest = line.partition(":")
        fields = rest.split()
        if len(fields) < 3:
            continue
        try:
            level = float(fields[2].rstrip("."))
        except ValueError:
            continue
        if level < 0:
            out[name.strip()] = level
    return out


def quality(dbm: float) -> str:
    if dbm >= GOOD_DBM:
        return "good"
    if dbm >= FAIR_DBM:
        return "fair"
    if dbm >= WEAK_DBM:
        return "weak"
    return "poor"


class WifiSignal:
    """Thread-safe, rate-limited, smoothed Wi-Fi signal for the /ws payload."""

    def __init__(self, path: Path = PROC_PATH, clock=time.monotonic) -> None:
        self._path = path
        self._clock = clock
        self._lock = threading.Lock()
        self._samples: deque[tuple[float, float]] = deque()
        self._last_read = -1e9
        self._iface: str | None = None
        self._warn = False

    def snapshot(self) -> dict | None:
        now = self._clock()
        with self._lock:
            if now - self._last_read >= SAMPLE_S:
                self._last_read = now
                levels = read_levels(self._path)
                if self._iface not in levels:
                    self._iface = next(iter(sorted(levels)), None)
                    self._samples.clear()
                if self._iface is None:
                    self._warn = False
                    return None
                self._samples.append((now, levels[self._iface]))
                while self._samples and now - self._samples[0][0] > WINDOW_S:
                    self._samples.popleft()
                avg = sum(v for _, v in self._samples) / len(self._samples)
                if self._warn:
                    self._warn = avg <= CLEAR_DBM
                else:
                    # Needs a few seconds of history before it can warn.
                    self._warn = avg < WARN_DBM and len(self._samples) >= 5
            if self._iface is None or not self._samples:
                return None
            level = self._samples[-1][1]
            avg = sum(v for _, v in self._samples) / len(self._samples)
            return {
                "interface": self._iface,
                "level_dbm": round(level),
                "avg_dbm": round(avg),
                "quality": quality(avg),
                "warn": self._warn,
            }
