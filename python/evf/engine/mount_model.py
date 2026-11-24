"""Mount model: how far the mount's first axis is off its nominal direction.

On a two-axis mount, axis 1 (an alt-az base axis, or an equatorial polar
axis) is fixed to the ground and axis 2 (altitude or declination axis) is
fixed to the tube, so also to the camera. Each plate solve gives the camera's
full orientation R_i in local east-north-up (ENU) coordinates. For every solve
the axis-2 direction R_i b is at right angles to axis 1:

    a . (R_i b) = 0

with `a` (ground-fixed, ENU) and `b` (camera-fixed) unknown. Both come from
alternating smallest-eigenvector solves, starting from `a` = the zenith
(alt-az) or the celestial pole (equatorial). Axis non-perpendicularity is not
modelled. The spec is specs/start/SPEC_HORIZON_MOUNT_MODEL.md section 3.

A wrong clock or latitude looks just like tilt; for guidance that does not
matter, because the same clock and location are used throughout.
"""

import logging
import math
import threading
from dataclasses import dataclass

import numpy as np

from evf.engine.epoch import precession_matrix
from evf.solver.sync import orientation_from_radec_roll, radec_to_vec, vec_to_radec

logger = logging.getLogger(__name__)

NEEDED_SAMPLES = 8
MAX_SAMPLES = 40
# A new sample must differ this much from every kept one.
MIN_SAMPLE_SEP_DEG = 3.0
# Middle eigenvalue thresholds of the spread matrices (see SPEC 3.3).
TURN_SPREAD_MIN = 0.05
TILT_SPREAD_MIN = 0.02
# Non-square axes (common on Dobsonians) show up as residual, so the fit
# may not be perfect.
MAX_RMS_DEG = 0.5
MAX_AXIS_OFFSET_DEG = 15.0
# Against a ready model, this many samples in a row off by more than
# max(BUMP_RESIDUAL_DEG, BUMP_RMS_FACTOR x the fit's rms) mean the mount was
# moved.
BUMP_RESIDUAL_DEG = 1.0
BUMP_RMS_FACTOR = 4.0
BUMP_COUNT = 3
# The location may wander this much before the samples are dropped.
LOCATION_TOLERANCE_DEG = 0.01

_UNIX_EPOCH_JD = 2440587.5
_TT_MINUS_UTC_S = 69.184


def _lst_deg(longitude_deg: float, unix_seconds: float) -> float:
    import erfa
    ut = unix_seconds / 86400.0
    tt = ut + _TT_MINUS_UTC_S / 86400.0
    gmst = erfa.gmst06(_UNIX_EPOCH_JD, ut, _UNIX_EPOCH_JD, tt)
    return (math.degrees(gmst) + longitude_deg) % 360.0


def enu_matrix(latitude_deg: float, lst_deg: float) -> np.ndarray:
    """Rotation from equatorial-of-date Cartesian to local (east, north, up)."""
    lat = math.radians(latitude_deg)
    lst = math.radians(lst_deg)
    east = [-math.sin(lst), math.cos(lst), 0.0]
    north = [-math.sin(lat) * math.cos(lst), -math.sin(lat) * math.sin(lst), math.cos(lat)]
    up = [math.cos(lat) * math.cos(lst), math.cos(lat) * math.sin(lst), math.sin(lat)]
    return np.array([east, north, up])


def j2000_to_enu_matrix(
    location: tuple[float, float], unix_seconds: float,
) -> np.ndarray:
    """Rotation from J2000 Cartesian to local ENU at the given time."""
    lat, lon = location
    return enu_matrix(lat, _lst_deg(lon, unix_seconds)) @ precession_matrix()


def nominal_axis(mode: str, latitude_deg: float) -> np.ndarray:
    """Where axis 1 should point, in ENU: the zenith, or the north celestial
    pole (below the horizon in the south; an axis is a line either way)."""
    if mode == "eq":
        lat = math.radians(latitude_deg)
        return np.array([0.0, math.cos(lat), math.sin(lat)])
    return np.array([0.0, 0.0, 1.0])


def _smallest_eigvec(m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    w, v = np.linalg.eigh(m)  # ascending
    return v[:, 0], w


def fit_axes(
    rotations: list[np.ndarray], a0: np.ndarray, max_iter: int = 100,
) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Fit axis 1 (`a`, ENU) and axis 2 (`b`, camera frame).

    Returns (a, b, turn_spread, tilt_spread): the spreads are the middle
    eigenvalues of the normalised scatter matrices of R_i b and R_i^T a.
    `a` is oriented to the same side as `a0`.
    """
    n = len(rotations)
    a = a0 / np.linalg.norm(a0)
    b = np.array([1.0, 0.0, 0.0])
    tilt_w = turn_w = np.zeros(3)
    for _ in range(max_iter):
        us = [r.T @ a for r in rotations]
        b, tilt_w = _smallest_eigvec(sum(np.outer(u, u) for u in us) / n)
        vs = [r @ b for r in rotations]
        a_new, turn_w = _smallest_eigvec(sum(np.outer(v, v) for v in vs) / n)
        if a_new @ a0 < 0:
            a_new = -a_new
        moved = math.acos(max(-1.0, min(1.0, float(a_new @ a))))
        a = a_new
        if moved < 1e-7:
            break
    return a, b, float(turn_w[1]), float(tilt_w[1])


def residuals_deg(rotations: list[np.ndarray], a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.degrees(np.arcsin(np.clip([float(a @ (r @ b)) for r in rotations], -1, 1)))


def rotation_between(a: np.ndarray, n: np.ndarray) -> np.ndarray:
    """Smallest rotation taking unit vector a to unit vector n."""
    v = np.cross(a, n)
    s = float(np.linalg.norm(v))
    c = float(a @ n)
    if s < 1e-12:
        return np.eye(3)
    k = v / s
    kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + s * kx + (1 - c) * (kx @ kx)


def camera_rotation_enu(
    ra_deg: float, dec_deg: float, roll_deg: float, to_enu: np.ndarray,
) -> np.ndarray:
    """Camera body frame -> ENU for a J2000 solve."""
    return to_enu @ orientation_from_radec_roll(ra_deg, dec_deg, roll_deg)


@dataclass(frozen=True)
class MountCorrection:
    """A ready model, for the guidance: axis 1 in ENU (oriented towards the
    zenith or the north celestial pole) at the given location."""

    mode: str
    axis_enu: tuple[float, float, float]
    location: tuple[float, float]


@dataclass
class _Sample:
    rotation: np.ndarray
    boresight: np.ndarray  # ENU, for the minimum-separation test


class MountModel:
    """Collects solve orientations and fits the mount's axes. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._samples: list[_Sample] = []
        self._mode: str | None = None
        self._location: tuple[float, float] | None = None
        self._fit: dict | None = None  # last fit result
        # Samples off a ready model, waiting to confirm the mount moved.
        self._pending: list[_Sample] = []

    # -- input -------------------------------------------------------------

    def reset(self) -> None:
        with self._lock:
            self._clear()

    def _clear(self) -> None:
        self._samples.clear()
        self._fit = None
        self._pending.clear()

    def add_solve(
        self,
        ra_deg: float,
        dec_deg: float,
        roll_deg: float,
        mode: str,
        location: tuple[float, float] | None,
        unix_seconds: float,
    ) -> None:
        """Offer a fresh, steady solve (the scope at rest)."""
        with self._lock:
            if location is None:
                if self._samples or self._location is not None:
                    self._clear()
                self._location = None
                self._mode = mode
                return
            if mode != self._mode or not self._same_location(location):
                self._clear()
            self._mode = mode
            self._location = location

            rot = camera_rotation_enu(
                ra_deg, dec_deg, roll_deg, j2000_to_enu_matrix(location, unix_seconds),
            )
            sample = _Sample(rot, rot[:, 2].copy())

            if self._fit is not None and self._fit["ready"]:
                a, b = self._fit["a"], self._fit["b"]
                resid = abs(float(np.degrees(np.arcsin(np.clip(a @ (rot @ b), -1, 1)))))
                limit = max(BUMP_RESIDUAL_DEG, BUMP_RMS_FACTOR * self._fit["rms"])
                if resid > limit:
                    # Held back until it is clear whether the mount moved.
                    self._pending.append(sample)
                    if len(self._pending) >= BUMP_COUNT:
                        logger.info("Mount model: mount moved (residual %.2f°), starting over",
                                    resid)
                        pending = list(self._pending)
                        self._clear()
                        self._samples.extend(self._distinct(pending))
                        self._refit()
                    return
                self._pending.clear()

            cos_min = math.cos(math.radians(MIN_SAMPLE_SEP_DEG))
            if any(float(s.boresight @ sample.boresight) > cos_min
                   and self._roll_close(s.rotation, rot) for s in self._samples):
                return
            self._samples.append(sample)
            if len(self._samples) > MAX_SAMPLES:
                self._samples.pop(0)
            self._refit()
            # Collecting with enough spread but a poor fit: something moved
            # early on; let the oldest samples age out faster.
            fit = self._fit
            if (fit is not None and not fit["ready"] and fit["spread_ok"]
                    and len(self._samples) > NEEDED_SAMPLES):
                self._samples.pop(0)
                self._refit()

    @classmethod
    def _distinct(cls, samples: list["_Sample"]) -> list["_Sample"]:
        cos_min = math.cos(math.radians(MIN_SAMPLE_SEP_DEG))
        out: list[_Sample] = []
        for s in samples:
            if not any(float(o.boresight @ s.boresight) > cos_min
                       and cls._roll_close(o.rotation, s.rotation) for o in out):
                out.append(s)
        return out

    @staticmethod
    def _roll_close(r1: np.ndarray, r2: np.ndarray) -> bool:
        """True when the two orientations differ by less than the minimum
        separation also in roll (image-up directions close)."""
        cos_min = math.cos(math.radians(MIN_SAMPLE_SEP_DEG))
        return float(r1[:, 1] @ r2[:, 1]) > cos_min

    def _same_location(self, location: tuple[float, float]) -> bool:
        if self._location is None:
            return False
        return (abs(location[0] - self._location[0]) <= LOCATION_TOLERANCE_DEG
                and abs(location[1] - self._location[1]) <= LOCATION_TOLERANCE_DEG)

    def _refit(self) -> None:
        n = len(self._samples)
        if n < 3 or self._location is None or self._mode is None:
            self._fit = None
            return
        rots = [s.rotation for s in self._samples]
        a0 = nominal_axis(self._mode, self._location[0])
        a, b, turn, tilt = fit_axes(rots, a0)
        res = residuals_deg(rots, a, b)
        rms = float(np.sqrt(np.mean(res ** 2)))
        offset = math.degrees(math.acos(max(-1.0, min(1.0, float(a @ a0)))))
        spread_ok = turn >= TURN_SPREAD_MIN and tilt >= TILT_SPREAD_MIN
        ready = (n >= NEEDED_SAMPLES and spread_ok and rms <= MAX_RMS_DEG
                 and offset <= MAX_AXIS_OFFSET_DEG)
        was_ready = self._fit is not None and self._fit["ready"]
        self._fit = {
            "a": a, "b": b, "turn": turn, "tilt": tilt, "rms": rms,
            "offset": offset, "spread_ok": spread_ok, "ready": ready,
        }
        if ready and not was_ready:
            logger.info("Mount model ready: axis %.2f° off nominal, rms %.3f°, %d samples",
                        offset, rms, n)

    # -- output ------------------------------------------------------------

    def correction(self) -> MountCorrection | None:
        with self._lock:
            if self._fit is None or not self._fit["ready"] or self._location is None:
                return None
            a = self._fit["a"]
            return MountCorrection(self._mode or "altaz", (float(a[0]), float(a[1]), float(a[2])),
                                   self._location)

    def status(self, mode: str, location: tuple[float, float] | None) -> dict:
        """The /ws `mount.model` block (SPEC 3.5)."""
        blk = {
            "state": "off", "samples": 0, "needed": NEEDED_SAMPLES, "hint": None,
            "tilt_deg": None, "low_side_az_deg": None,
            "polar_alt_error_deg": None, "polar_az_error_deg": None,
            "rms_deg": None, "applied": False,
        }
        if location is None:
            return blk
        with self._lock:
            stale = (mode != self._mode or not self._same_location(location))
            n = 0 if stale else len(self._samples)
            fit = None if stale else self._fit
        blk["samples"] = n
        if fit is None or not fit["ready"]:
            blk["state"] = "collecting"
            if fit is not None and n >= 3:
                if fit["turn"] < TURN_SPREAD_MIN:
                    blk["hint"] = "turn"
                elif fit["tilt"] < TILT_SPREAD_MIN:
                    blk["hint"] = "tilt"
            return blk
        a = fit["a"]
        blk["state"] = "ready"
        blk["applied"] = True
        blk["rms_deg"] = round(fit["rms"], 3)
        if mode == "eq":
            lat = location[0]
            pole = a if lat >= 0 else -a  # the end above the horizon
            alt = math.degrees(math.asin(max(-1.0, min(1.0, float(pole[2])))))
            blk["polar_alt_error_deg"] = round(alt - abs(lat), 2)
            blk["polar_az_error_deg"] = round(
                math.degrees(math.asin(max(-1.0, min(1.0, float(pole[0]))))), 2)
        else:
            blk["tilt_deg"] = round(fit["offset"], 2)
            blk["low_side_az_deg"] = round(math.degrees(math.atan2(a[0], a[1])) % 360.0, 1)
        return blk


# -- guidance in the mount's own frame --------------------------------------

def axis_j2000(correction: MountCorrection, unix_seconds: float) -> tuple[float, float]:
    """RA/Dec (J2000) of the fitted axis 1 now."""
    to_enu = j2000_to_enu_matrix(correction.location, unix_seconds)
    return vec_to_radec(to_enu.T @ np.array(correction.axis_enu))


def to_mount_frame(
    correction: MountCorrection, unix_seconds: float,
    points_j2000: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """J2000 points -> the mount's own coordinates.

    Alt-az: (alt, az) about the fitted base axis. Equatorial: (ra, dec) of
    date about the fitted polar axis. Both via the smallest rotation that
    takes the fitted axis to the nominal one.
    """
    lat, lon = correction.location
    lst = _lst_deg(lon, unix_seconds)
    enu = enu_matrix(lat, lst)
    to_enu = enu @ precession_matrix()
    a = np.array(correction.axis_enu)
    q = rotation_between(a / np.linalg.norm(a), nominal_axis(correction.mode, lat))
    out = []
    for ra, dec in points_j2000:
        v = q @ (to_enu @ radec_to_vec(ra, dec))
        if correction.mode == "eq":
            out.append(vec_to_radec(enu.T @ v))
        else:
            alt = math.degrees(math.asin(max(-1.0, min(1.0, float(v[2])))))
            az = math.degrees(math.atan2(v[0], v[1])) % 360.0
            out.append((alt, az))
    return out
