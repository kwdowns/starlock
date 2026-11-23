"""Pointing updates for Live Activities: ``POST /v1/device/pointing``.

The body is built from the same state dict the web UI gets over /ws
(``WebServer._build_payload``), so the cloud sees exactly what the UI shows.
The service does the APNs throttling; the Pi follows the send rules in
Starlock Cloud's docs/pi-integration.md so it doesn't post more than the
service can use:

- major changes (state, target, on-target, dwelling) within 2 s;
- minor changes (offsets or pointing moved by a meaningful amount) at most
  every 15 s, and only while a phone is watching (the service says so in
  each response: ``watching``);
- a 60 s heartbeat while tracking or lost;
- latest only (no queue), and a 30 s .. 5 min backoff after a failure.
"""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from typing import Callable

from evf.cloud.client import CloudClient, CloudError, Unauthorized
from evf.engine.epoch import j2000_to_jnow
from evf.engine.mount import local_sidereal_deg, radec_to_altaz

logger = logging.getLogger(__name__)

# Same as the web UI's LOCKED_THRESHOLD_DEG (NavOverlay.tsx).
ON_TARGET_DEG = 0.15
# A solve older than this means "lost".
STALE_SOLVE_S = 5.0
MIN_INTERVAL_S = 2.0
MINOR_INTERVAL_S = 15.0
HEARTBEAT_S = 60.0
# A minor change: an offset or the separation moved by this fraction of the
# last-sent separation, clamped to [MIN, MAX] degrees (the service's rule).
OFFSET_CHANGE_FRACTION = 0.25
MIN_OFFSET_CHANGE_DEG = 0.2
MAX_OFFSET_CHANGE_DEG = 2.0
# Without a target: the pointing moved this far.
POINTING_CHANGE_DEG = 1.0
BACKOFF_S = (30.0, 60.0, 120.0, 240.0, 300.0)

_SETUP_STATES = {"SETUP", "SYNC", "SYNC_CONFIRM", "CALIBRATE", "WARMING_UP"}


def _r(x: float | None, digits: int) -> float | None:
    return None if x is None else round(float(x), digits)


def build_pointing_body(payload: dict, *, dwelling: bool, now: float) -> dict:
    """Cloud pointing body (without ``seq`` / ``sentAtUnix``) from a /ws payload."""
    p = payload.get("pointing") or {}
    age = p.get("solve_age_s")
    solved = bool(p.get("valid")) and (age is None or age <= STALE_SOLVE_S)
    engine_state = payload.get("state")
    if engine_state == "TRACKING":
        state = "tracking" if solved else "lost"
    elif engine_state in _SETUP_STATES:
        state = "setup"
    else:
        state = "idle"

    pointing = None
    if solved:
        ra, dec = p["ra_deg"], p["dec_deg"]
        pointing = {"raJ2000Deg": _r(ra, 4), "decJ2000Deg": _r(dec, 4),
                    "altDeg": None, "azDeg": None}
        loc = payload.get("location") or {}
        lat, lon = loc.get("latitude"), loc.get("longitude")
        if lat is not None and lon is not None:
            ra_now, dec_now = j2000_to_jnow(ra, dec)
            alt, az = radec_to_altaz(ra_now, dec_now, lat, local_sidereal_deg(lon, now))
            pointing["altDeg"], pointing["azDeg"] = _r(alt, 2), _r(az, 2)

    nav = payload.get("nav") or {}
    target = offsets = None
    on_target = False
    if nav.get("active"):
        target = {"name": nav.get("target_name"),
                  "raJ2000Deg": _r(nav.get("target_ra_deg"), 4),
                  "decJ2000Deg": _r(nav.get("target_dec_deg"), 4)}
        sep = nav.get("separation_deg")
        if solved and sep is not None:
            on_target = (nav["on_target"] if "on_target" in nav
                         else sep <= (nav.get("on_target_deg") or ON_TARGET_DEG))
            mount = nav.get("mount")
            mode = (payload.get("mount") or {}).get("mode")
            if mount:
                offsets = {"separationDeg": _r(sep, 2),
                           "axis1Deg": _r(mount["axis1_deg"], 2),
                           "axis2Deg": _r(mount["axis2_deg"], 2),
                           "frame": "equatorial" if mode == "eq" else "altaz"}
            elif nav.get("camera_angle_deg") is not None:
                a = math.radians(nav["camera_angle_deg"])
                offsets = {"separationDeg": _r(sep, 2),
                           "axis1Deg": _r(sep * math.sin(a), 2),
                           "axis2Deg": _r(sep * math.cos(a), 2),
                           "frame": "camera"}

    return {
        "state": state,
        "pointing": pointing,
        "target": target,
        "offsets": offsets,
        "onTarget": on_target,
        "dwelling": bool(dwelling and solved),
    }


def ended_body() -> dict:
    return {"state": "ended", "pointing": None, "target": None, "offsets": None,
            "onTarget": False, "dwelling": False}


def _minor_change(last: dict, body: dict) -> bool:
    """Moved enough to be worth a Live Activity update (same test as the service)."""
    lo, no = last.get("offsets"), body.get("offsets")
    if (lo is None) != (no is None):
        return True
    if lo is not None and no is not None:
        if lo.get("frame") != no.get("frame"):
            return True
        threshold = min(MAX_OFFSET_CHANGE_DEG,
                        max(MIN_OFFSET_CHANGE_DEG, (lo.get("separationDeg") or 0) * OFFSET_CHANGE_FRACTION))
        return any(abs((no.get(k) or 0) - (lo.get(k) or 0)) >= threshold
                   for k in ("axis1Deg", "axis2Deg", "separationDeg"))
    if body.get("target"):
        return False  # with a target, the offsets carry the motion
    lp, np_ = last.get("pointing"), body.get("pointing")
    if (lp is None) != (np_ is None):
        return True
    if lp is None or np_ is None:
        return False
    return _sep_deg(lp["raJ2000Deg"], lp["decJ2000Deg"], np_["raJ2000Deg"], np_["decJ2000Deg"]) >= POINTING_CHANGE_DEG


def _sep_deg(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    c = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(r1 - r2)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


class SendPolicy:
    """When to send, per the contract. Pure; times are monotonic seconds."""

    def __init__(self) -> None:
        self._last_body: dict | None = None
        self._last_sent = -math.inf
        self._not_before = -math.inf
        self._failures = 0
        # The service's last word on whether a phone is watching this device.
        self.watching = True

    @staticmethod
    def _key(body: dict) -> tuple:
        t = body.get("target") or {}
        return (body["state"], t.get("name"), t.get("raJ2000Deg"), t.get("decJ2000Deg"),
                body["onTarget"], body["dwelling"])

    def due(self, body: dict, now: float) -> bool:
        if now < self._not_before:
            return False
        last = self._last_body
        if last is None:
            return True
        since = now - self._last_sent
        if self._key(body) != self._key(last):
            return since >= MIN_INTERVAL_S
        if self.watching and since >= MINOR_INTERVAL_S and _minor_change(last, body):
            return True
        return body["state"] in ("tracking", "lost") and since >= HEARTBEAT_S

    def sent(self, body: dict, now: float, watching: bool | None = None) -> None:
        self._last_body = body
        self._last_sent = now
        self._failures = 0
        self._not_before = -math.inf
        if watching is not None:
            self.watching = watching

    def failed(self, now: float, retry_after: float | None = None) -> float:
        delay = BACKOFF_S[min(self._failures, len(BACKOFF_S) - 1)]
        if retry_after:
            delay = max(delay, retry_after)
        self._failures += 1
        self._not_before = now + delay
        return delay

    def reset(self) -> None:
        self.__init__()


class PointingReporter:
    """Thread that samples the UI state twice a second and sends when due."""

    def __init__(
        self,
        client_fn: Callable[[], CloudClient | None],
        snapshot: Callable[[], dict | None],
        dwelling: Callable[[], bool],
        on_unauthorized: Callable[[], None],
        *,
        poll_s: float = 0.5,
        wall: Callable[[], float] = time.time,
        mono: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client_fn = client_fn
        self._snapshot = snapshot
        self._dwelling = dwelling
        self._on_unauthorized = on_unauthorized
        self._poll_s = poll_s
        self._wall = wall
        self._mono = mono
        self._policy = SendPolicy()
        self._session = str(uuid.uuid4())
        self._seq = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None
        self.last_sent_at: float | None = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="cloud-pointing", daemon=True)
        self._thread.start()

    def stop(self, send_ended: bool = True, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
        if send_ended:
            client = self._client_fn()
            if client is not None and self._policy._last_body is not None:
                try:
                    client._timeout = min(client._timeout, timeout)
                    self._send(client, ended_body())
                except CloudError:
                    pass

    def reset(self) -> None:
        """Forget the send history (new link)."""
        with self._lock:
            self._policy.reset()

    def _run(self) -> None:
        while not self._stop.wait(self._poll_s):
            try:
                self.step()
            except Exception as exc:  # never let the reporter die
                logger.warning("Cloud pointing step failed: %s", exc)

    def step(self) -> bool:
        """One poll; returns True if an update was sent."""
        client = self._client_fn()
        if client is None:
            return False
        payload = self._snapshot()
        if payload is None:
            return False
        body = build_pointing_body(payload, dwelling=self._dwelling(), now=self._wall())
        now = self._mono()
        with self._lock:
            if not self._policy.due(body, now):
                return False
        try:
            response = self._send(client, body)
        except Unauthorized:
            self._on_unauthorized()
            return False
        except CloudError as exc:
            with self._lock:
                delay = self._policy.failed(now, exc.retry_after)
            if self.last_error != str(exc):
                logger.info("Cloud pointing update failed (%s); next try in %.0f s", exc, delay)
            self.last_error = str(exc)
            return False
        watching = response.get("watching") if isinstance(response, dict) else None
        with self._lock:
            self._policy.sent(body, now, watching if isinstance(watching, bool) else None)
        self.last_error = None
        self.last_sent_at = self._wall()
        return True

    def _send(self, client: CloudClient, body: dict) -> dict | None:
        with self._lock:
            self._seq += 1
            seq = self._seq
        return client.post_pointing({"seq": seq, "sentAtUnix": round(self._wall(), 1), **body},
                                    self._session)
