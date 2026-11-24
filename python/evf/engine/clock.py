"""Engine-wide wall clock, correctable by a connected client.

A Pi has no real-time clock: without internet (hotspot mode, a dark site) it
boots with the last time it saw, often hours or days off. Sidereal time, and
with it alt/az, the mount guidance and the mount model, would follow. The web
UI and the phone apps report their own clock on every connect
(POST /api/clock); when it differs from the host's by more than
CLOCK_TOLERANCE_S the difference is applied to everything that asks this
clock for the time.
"""

import threading
import time
from typing import Callable

# A client clock differing from the host's by more than this wins. Phones
# keep network time to well under a second; the request itself takes
# milliseconds on a LAN.
CLOCK_TOLERANCE_S = 2.0


class Clock:
    """Wall-clock seconds, optionally corrected by a client-reported time."""

    def __init__(self, time_fn: Callable[[], float] = time.time) -> None:
        self._time = time_fn
        self._lock = threading.Lock()
        self._offset = 0.0
        self._corrected = False

    def report_client_time(self, client_unix_s: float) -> bool:
        """Take a connecting client's clock. Returns True if it is now used.

        Within CLOCK_TOLERANCE_S of the host clock the host is trusted and any
        earlier correction is dropped; otherwise the client wins.
        """
        diff = float(client_unix_s) - self._time()
        with self._lock:
            if abs(diff) > CLOCK_TOLERANCE_S:
                self._offset = diff
                self._corrected = True
            else:
                self._offset = 0.0
                self._corrected = False
            return self._corrected

    def now(self) -> float:
        with self._lock:
            return self._time() + self._offset

    def __call__(self) -> float:
        return self.now()

    @property
    def source(self) -> str:
        with self._lock:
            return "client" if self._corrected else "system"

    @property
    def offset_s(self) -> float:
        """Client time minus host time (positive: the host was behind)."""
        with self._lock:
            return self._offset

    def snapshot(self) -> dict:
        """The /ws `clock` block."""
        with self._lock:
            return {
                "source": "client" if self._corrected else "system",
                "offset_s": round(self._offset, 1),
            }
