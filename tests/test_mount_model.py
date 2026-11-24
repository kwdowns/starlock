"""Mount model: fit a tilted alt-az base / misaligned polar axis from solves."""

import math

import numpy as np
import pytest

from evf.engine.mount import compute_mount_guidance
from evf.engine.mount_model import (
    MountModel,
    _lst_deg,
    enu_matrix,
    j2000_to_enu_matrix,
    nominal_axis,
    rotation_between,
)
from evf.solver.sync import orientation_from_radec_roll, vec_to_radec

LOC = (40.0, -105.0)
T = 1_790_000_000.0


def _rx(t):
    c, s = math.cos(t), math.sin(t)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _rz(t):
    c, s = math.cos(t), math.sin(t)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


# Camera at az 0, alt 0: boresight north, image-up = up, image-left = west.
C0 = np.column_stack([[-1, 0, 0], [0, 0, 1], [0, 1, 0]]).astype(float)
# The camera sits a little crooked on the tube.
M_CAM = _rz(math.radians(7)) @ _rx(math.radians(-3))


def _axis(alt_deg, az_deg):
    alt, az = math.radians(alt_deg), math.radians(az_deg)
    return np.array([math.cos(alt) * math.sin(az), math.cos(alt) * math.cos(az), math.sin(alt)])


def _to_solve(r_enu, loc=LOC, t=T):
    """ENU camera orientation -> J2000 (ra, dec, roll)."""
    rj = j2000_to_enu_matrix(loc, t).T @ r_enu
    ra, dec = vec_to_radec(rj[:, 2])
    ra_r, dec_r = math.radians(ra), math.radians(dec)
    east = np.array([-math.sin(ra_r), math.cos(ra_r), 0.0])
    north = np.array([-math.sin(dec_r) * math.cos(ra_r),
                      -math.sin(dec_r) * math.sin(ra_r), math.cos(dec_r)])
    roll = math.degrees(math.atan2(rj[:, 1] @ east, rj[:, 1] @ north)) % 360.0
    # Round trip sanity: the conventions match orientation_from_radec_roll.
    assert np.allclose(orientation_from_radec_roll(ra, dec, roll), rj, atol=1e-9)
    return ra, dec, roll


def _altaz_mount(tilt_axis):
    tilt = rotation_between(np.array([0.0, 0.0, 1.0]), tilt_axis)

    def orient(az_deg, alt_deg):
        r = _rz(-math.radians(az_deg)) @ _rx(math.radians(alt_deg)) @ C0 @ M_CAM
        return tilt @ r
    return orient


POSITIONS = [(az, alt) for az in (10, 80, 150, 220, 290) for alt in (20, 45, 70)]


def test_altaz_tilt_is_recovered():
    a_true = _axis(90 - 1.5, 45)  # leans 1.5° towards NE
    orient = _altaz_mount(a_true)
    m = MountModel()
    for az, alt in POSITIONS:
        m.add_solve(*_to_solve(orient(az, alt)), "altaz", LOC, T)
    st = m.status("altaz", LOC)
    assert st["state"] == "ready"
    assert st["tilt_deg"] == pytest.approx(1.5, abs=0.02)
    assert st["low_side_az_deg"] == pytest.approx(45, abs=1.0)
    assert st["rms_deg"] < 0.01


def test_altaz_guidance_is_in_mount_frame():
    a_true = _axis(90 - 2.0, 200)
    orient = _altaz_mount(a_true)
    m = MountModel()
    for az, alt in POSITIONS:
        m.add_solve(*_to_solve(orient(az, alt)), "altaz", LOC, T)
    corr = m.correction()
    assert corr is not None

    # Boresight of the camera = the pointing (no sync offset needed here).
    cur = _to_solve(orient(30, 25))
    tgt = _to_solve(orient(110, 60))
    g = compute_mount_guidance("altaz", *cur, tgt[0], tgt[1], LOC, T, corr)
    plain = compute_mount_guidance("altaz", *cur, tgt[0], tgt[1], LOC, T)
    # The mount's own azimuth of the boresight depends on the camera's
    # crookedness, so compare the per-axis moves with a camera-free ground
    # truth: the boresight direction in the tilted mount frame.
    q = rotation_between(a_true, np.array([0.0, 0.0, 1.0]))

    def mount_altaz(r):
        v = q @ r[:, 2]
        return (math.degrees(math.asin(v[2])),
                math.degrees(math.atan2(v[0], v[1])))
    c_alt, c_az = mount_altaz(orient(30, 25))
    t_alt, t_az = mount_altaz(orient(110, 60))
    assert g.axis1_deg == pytest.approx(t_az - c_az, abs=0.02)
    assert g.axis2_deg == pytest.approx(t_alt - c_alt, abs=0.02)
    # Without the model the split is off by a noticeable amount.
    assert abs(plain.axis2_deg - (t_alt - c_alt)) > 0.5


def test_collecting_hints_and_spread():
    orient = _altaz_mount(_axis(89.0, 0))
    m = MountModel()
    # Only tube altitude changes: the base never turns.
    for alt in (20, 30, 40, 50, 60, 70, 80, 25, 35):
        m.add_solve(*_to_solve(orient(100, alt)), "altaz", LOC, T)
    st = m.status("altaz", LOC)
    assert st["state"] == "collecting"
    assert st["hint"] == "turn"
    # Only the base turns: the tube altitude stays.
    m.reset()
    for az in range(0, 360, 40):
        m.add_solve(*_to_solve(orient(az, 40)), "altaz", LOC, T)
    st = m.status("altaz", LOC)
    assert st["state"] == "collecting"
    assert st["hint"] == "tilt"


def test_duplicates_are_skipped_and_location_change_resets():
    orient = _altaz_mount(_axis(89.0, 0))
    m = MountModel()
    for _ in range(5):
        m.add_solve(*_to_solve(orient(100, 40)), "altaz", LOC, T)
    assert m.status("altaz", LOC)["samples"] == 1
    m.add_solve(*_to_solve(orient(100, 40)), "altaz", (41.0, -105.0), T)
    assert m.status("altaz", (41.0, -105.0))["samples"] == 1
    assert m.status("altaz", None)["state"] == "off"
    assert m.status("eq", (41.0, -105.0))["samples"] == 0


def test_bump_starts_over():
    orient = _altaz_mount(_axis(90 - 1.0, 90))
    m = MountModel()
    for az, alt in POSITIONS:
        m.add_solve(*_to_solve(orient(az, alt)), "altaz", LOC, T)
    assert m.status("altaz", LOC)["state"] == "ready"
    bumped = _altaz_mount(_axis(90 - 4.0, 270))
    for az, alt in [(40, 30), (130, 50), (250, 35)]:
        m.add_solve(*_to_solve(bumped(az, alt)), "altaz", LOC, T)
    st = m.status("altaz", LOC)
    assert st["state"] == "collecting"
    assert st["samples"] == 3


def test_single_outlier_does_not_reset():
    orient = _altaz_mount(_axis(90 - 1.0, 90))
    m = MountModel()
    for az, alt in POSITIONS:
        m.add_solve(*_to_solve(orient(az, alt)), "altaz", LOC, T)
    bumped = _altaz_mount(_axis(90 - 4.0, 270))
    m.add_solve(*_to_solve(bumped(40, 30)), "altaz", LOC, T)
    m.add_solve(*_to_solve(orient(45, 33)), "altaz", LOC, T)
    st = m.status("altaz", LOC)
    assert st["state"] == "ready"
    assert st["samples"] == len(POSITIONS) + 1


@pytest.mark.parametrize("loc", [LOC, (-33.9, 151.2)])
def test_eq_polar_error_is_recovered(loc):
    lat = loc[0]
    ncp = nominal_axis("eq", lat)
    pole_up = ncp if lat >= 0 else -ncp
    pole_alt = abs(lat)
    pole_az = 0.0 if lat >= 0 else 180.0
    # 0.8° low, 0.5° east of the visible pole.
    a_vis = _axis(pole_alt - 0.8, pole_az + (0.5 if lat >= 0 else -0.5) / math.cos(math.radians(pole_alt)))
    q = rotation_between(pole_up, a_vis)
    m = MountModel()
    # Perfect mount: in the equatorial frame of date the camera keeps a
    # fixed roll to the true pole, so its Dec axis is fixed in the camera.
    roll0 = 33.0
    lst = _lst_deg(loc[1], T)
    eq_to_enu = enu_matrix(lat, lst)
    for ha in (-60, -20, 20, 60, 100):
        for dec in ((10, 40, 70) if lat >= 0 else (-10, -40, -70)):
            ra = (lst - ha) % 360
            r_perfect = eq_to_enu @ orientation_from_radec_roll(ra, dec, roll0)
            m.add_solve(*_to_solve(q @ r_perfect, loc), "eq", loc, T)
    st = m.status("eq", loc)
    assert st["state"] == "ready"
    assert st["polar_alt_error_deg"] == pytest.approx(-0.8, abs=0.05)
    assert st["polar_az_error_deg"] == pytest.approx(0.5, abs=0.05)
