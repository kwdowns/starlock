"""Push-to guidance along the mount's own two axes.

An alt-az mount moves in azimuth (turning the base) and altitude (tilting
the tube); an equatorial mount moves in right ascension and declination.
With the camera fixed to the tube, the image directions of those axes come
straight from each plate solve (plus the observer's location and the time
for alt-az), so no rotation calibration is needed.

Angles in degrees. Pointing and target come in J2000; the mount axes follow
the true pole and zenith of date, so both are precessed to JNow first.
"""

import math
import time
from dataclasses import dataclass

import erfa

from evf.engine.epoch import j2000_to_jnow, jnow_to_j2000
from evf.engine.mount_model import MountCorrection, axis_j2000, to_mount_frame
from evf.engine.navigation import sky_pa_to_camera_angle, sky_position_angle

MOUNT_MODES = ("altaz", "eq")
DEFAULT_MOUNT_MODE = "altaz"

# Above this altitude a small move on the sky can need a large base turn.
NEAR_ZENITH_ALT_DEG = 75.0
# Same for the RA axis near the celestial pole.
NEAR_POLE_DEC_DEG = 80.0

_UNIX_EPOCH_JD = 2440587.5
_TT_MINUS_UTC_S = 69.184


@dataclass(frozen=True)
class MountAxes:
    """Image directions of the mount's axes, clockwise from image-up.

    axis1: alt-az = turning the base clockwise seen from above (to the
    right); equatorial = moving in RA towards the east.
    axis2: alt-az = raising the tube; equatorial = moving in Dec north.
    """

    mode: str
    axis1_angle_deg: float
    axis2_angle_deg: float


@dataclass(frozen=True)
class MountGuidance:
    """How far to move each mount axis to reach the target.

    axis1_deg is the rotation of the axis itself (base turn or RA axis),
    not the distance on the sky, so near the zenith (or pole) it can be
    much larger than the separation.
    """

    axes: MountAxes
    axis1_deg: float
    axis2_deg: float
    near_pole: bool  # alt-az: near the zenith; equatorial: near the celestial pole
    pointing_alt_deg: float | None  # alt-az only
    target_alt_deg: float | None  # alt-az only


def _wrap180(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def local_sidereal_deg(longitude_deg: float, unix_seconds: float) -> float:
    """Local mean sidereal time in degrees (UT1 taken as UTC)."""
    ut = unix_seconds / 86400.0
    tt = ut + _TT_MINUS_UTC_S / 86400.0
    gmst = erfa.gmst06(_UNIX_EPOCH_JD, ut, _UNIX_EPOCH_JD, tt)
    return (math.degrees(gmst) + longitude_deg) % 360.0


def radec_to_altaz(
    ra_deg: float, dec_deg: float, latitude_deg: float, lst_deg: float,
) -> tuple[float, float]:
    """Equatorial of date → (alt, az); az from north through east, [0, 360)."""
    ha = math.radians(lst_deg - ra_deg)
    dec = math.radians(dec_deg)
    lat = math.radians(latitude_deg)
    sin_alt = math.sin(dec) * math.sin(lat) + math.cos(dec) * math.cos(lat) * math.cos(ha)
    alt = math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))
    az = math.degrees(math.atan2(
        -math.cos(dec) * math.sin(ha),
        math.sin(dec) * math.cos(lat) - math.cos(dec) * math.sin(lat) * math.cos(ha),
    )) % 360.0
    return alt, az


def altaz_to_radec(
    alt_deg: float, az_deg: float, latitude_deg: float, lst_deg: float,
) -> tuple[float, float]:
    """(alt, az) → equatorial of date (ra, dec)."""
    alt = math.radians(alt_deg)
    az = math.radians(az_deg)
    lat = math.radians(latitude_deg)
    sin_dec = math.sin(alt) * math.sin(lat) + math.cos(alt) * math.cos(lat) * math.cos(az)
    dec = math.degrees(math.asin(max(-1.0, min(1.0, sin_dec))))
    ha = math.degrees(math.atan2(
        -math.cos(alt) * math.sin(az),
        math.sin(alt) * math.cos(lat) - math.cos(alt) * math.sin(lat) * math.cos(az),
    ))
    return (lst_deg - ha) % 360.0, dec


def mount_axes(
    mode: str,
    ra_deg: float,
    dec_deg: float,
    roll_deg: float,
    location: tuple[float, float] | None,
    unix_seconds: float | None = None,
    correction: MountCorrection | None = None,
) -> MountAxes | None:
    """Image directions of the mount axes at the given J2000 pointing.

    Returns None for alt-az without a location (the zenith is unknown).
    With a fitted mount model (`correction`, same mode) the axes are taken
    about the fitted axis instead of the zenith or the pole.
    """
    now = time.time() if unix_seconds is None else unix_seconds
    if correction is not None and correction.mode == mode:
        pole_ra, pole_dec = axis_j2000(correction, now)
        towards = sky_pa_to_camera_angle(
            sky_position_angle(ra_deg, dec_deg, pole_ra, pole_dec), roll_deg,
        )
        if mode == "eq":
            return MountAxes("eq", (towards - 90.0) % 360.0, towards)
        return MountAxes("altaz", (towards + 90.0) % 360.0, towards)

    if mode == "eq":
        pole_ra, pole_dec = jnow_to_j2000(0.0, 90.0)
        north = sky_pa_to_camera_angle(
            sky_position_angle(ra_deg, dec_deg, pole_ra, pole_dec), roll_deg,
        )
        # East is counter-clockwise from north in a sky image as seen.
        return MountAxes("eq", (north - 90.0) % 360.0, north)

    if location is None:
        return None
    lat, lon = location
    zen_ra, zen_dec = jnow_to_j2000(local_sidereal_deg(lon, now), lat)
    up = sky_pa_to_camera_angle(
        sky_position_angle(ra_deg, dec_deg, zen_ra, zen_dec), roll_deg,
    )
    # Facing the sky with the zenith up, azimuth grows to the right.
    return MountAxes("altaz", (up + 90.0) % 360.0, up)


def compute_mount_guidance(
    mode: str,
    ra_deg: float,
    dec_deg: float,
    roll_deg: float,
    target_ra_deg: float,
    target_dec_deg: float,
    location: tuple[float, float] | None,
    unix_seconds: float | None = None,
    correction: MountCorrection | None = None,
) -> MountGuidance | None:
    """Per-axis moves from the J2000 pointing to the J2000 target.

    Returns None for alt-az without a location. With a fitted mount model
    (`correction`, same mode) the moves are in the mount's own frame.
    """
    now = time.time() if unix_seconds is None else unix_seconds
    if correction is not None and correction.mode != mode:
        correction = None
    axes = mount_axes(mode, ra_deg, dec_deg, roll_deg, location, now, correction)
    if axes is None:
        return None

    if correction is not None:
        (c1, c2), (t1, t2) = to_mount_frame(
            correction, now, [(ra_deg, dec_deg), (target_ra_deg, target_dec_deg)],
        )
        if mode == "eq":  # (ra, dec) of date about the fitted polar axis
            return MountGuidance(
                axes=axes,
                axis1_deg=_wrap180(t1 - c1),
                axis2_deg=t2 - c2,
                near_pole=bool(max(abs(c2), abs(t2)) > NEAR_POLE_DEC_DEG),
                pointing_alt_deg=None,
                target_alt_deg=None,
            )
        # (alt, az) about the fitted base axis; the reported altitudes stay
        # the true ones.
        lat, lon = correction.location
        lst = local_sidereal_deg(lon, now)
        true_c = radec_to_altaz(*j2000_to_jnow(ra_deg, dec_deg), lat, lst)[0]
        true_t = radec_to_altaz(*j2000_to_jnow(target_ra_deg, target_dec_deg), lat, lst)[0]
        return MountGuidance(
            axes=axes,
            axis1_deg=_wrap180(t2 - c2),
            axis2_deg=t1 - c1,
            near_pole=bool(max(c1, t1) > NEAR_ZENITH_ALT_DEG),
            pointing_alt_deg=true_c,
            target_alt_deg=true_t,
        )

    ra_c, dec_c = j2000_to_jnow(ra_deg, dec_deg)
    ra_t, dec_t = j2000_to_jnow(target_ra_deg, target_dec_deg)

    if mode == "eq":
        return MountGuidance(
            axes=axes,
            axis1_deg=_wrap180(ra_t - ra_c),
            axis2_deg=dec_t - dec_c,
            near_pole=bool(max(abs(dec_c), abs(dec_t)) > NEAR_POLE_DEC_DEG),
            pointing_alt_deg=None,
            target_alt_deg=None,
        )

    lat, lon = location  # type: ignore[misc]  # mount_axes returned None otherwise
    lst = local_sidereal_deg(lon, now)
    alt_c, az_c = radec_to_altaz(ra_c, dec_c, lat, lst)
    alt_t, az_t = radec_to_altaz(ra_t, dec_t, lat, lst)
    return MountGuidance(
        axes=axes,
        axis1_deg=_wrap180(az_t - az_c),
        axis2_deg=alt_t - alt_c,
        near_pole=bool(max(alt_c, alt_t) > NEAR_ZENITH_ALT_DEG),
        pointing_alt_deg=alt_c,
        target_alt_deg=alt_t,
    )
