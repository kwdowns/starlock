"""Tests for mount-axis push-to guidance and the image-direction convention."""

import json
import math

import pytest

from evf.config.manager import ConfigManager
from evf.engine.epoch import j2000_to_jnow, jnow_to_j2000
from evf.engine.mount import (
    altaz_to_radec,
    compute_mount_guidance,
    local_sidereal_deg,
    mount_axes,
    radec_to_altaz,
)
from evf.engine.navigation import compute_navigation, gnomonic_project

FOV = 8.86
W, H = 1280, 720
NOW = 1_795_000_000.0  # fixed instant so the sky does not move under the tests
LOC = (40.0, -105.0)


def _image_angle(ra0, dec0, roll, ra, dec):
    """Clockwise-from-up image direction of (ra, dec) as actually projected."""
    px, py = gnomonic_project(ra0, dec0, roll, ra, dec, FOV, W, H)
    return math.degrees(math.atan2(px - W / 2, H / 2 - py)) % 360.0


def _angle_diff(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _altaz_point_j2000(alt, az):
    lst = local_sidereal_deg(LOC[1], NOW)
    return jnow_to_j2000(*altaz_to_radec(alt, az, LOC[0], lst))


# -- the mirror fix ----------------------------------------------------------


@pytest.mark.parametrize("roll", [0.0, 37.0, 90.0, 202.0, 300.0])
def test_navigation_direction_matches_projection(roll):
    """camera_angle / delta_right must point where the target is drawn."""
    ra0, dec0 = 80.0, 30.0
    for ra_t, dec_t in [(81.5, 30.0), (78.5, 30.5), (80.2, 28.8), (79.0, 31.2)]:
        nav = compute_navigation(ra0, dec0, roll, ra_t, dec_t, FOV, W, H)
        drawn = _image_angle(ra0, dec0, roll, ra_t, dec_t)
        assert _angle_diff(nav.camera_angle_deg, drawn) < 1.0
        px, _ = gnomonic_project(ra0, dec0, roll, ra_t, dec_t, FOV, W, H)
        if abs(px - W / 2) > 20:
            assert (nav.delta_right_deg > 0) == (px > W / 2)


def test_east_is_left_at_roll_zero():
    nav = compute_navigation(80.0, 0.0, 0.0, 81.0, 0.0, FOV, W, H)
    assert nav.delta_right_deg < 0
    assert "L" in nav.direction_text


# -- coordinate helpers --------------------------------------------------------


def test_altaz_roundtrip():
    lst = local_sidereal_deg(LOC[1], NOW)
    for ra, dec in [(10.0, 20.0), (200.0, -10.0), (95.0, 70.0)]:
        alt, az = radec_to_altaz(ra, dec, LOC[0], lst)
        ra2, dec2 = altaz_to_radec(alt, az, LOC[0], lst)
        assert _angle_diff(ra, ra2) < 1e-6 and dec == pytest.approx(dec2, abs=1e-6)


def test_zenith_is_at_altitude_90():
    lst = local_sidereal_deg(LOC[1], NOW)
    alt, _ = radec_to_altaz(lst, LOC[0], LOC[0], lst)
    assert alt == pytest.approx(90.0, abs=1e-6)


# -- axes agree with where things actually move in the image -------------------


@pytest.mark.parametrize("alt", [20.0, 60.0, 85.0, 89.0])
@pytest.mark.parametrize("roll", [0.0, 123.0, 250.0])
def test_altaz_axes_match_projection(alt, roll):
    az = 140.0
    ra0, dec0 = _altaz_point_j2000(alt, az)
    axes = mount_axes("altaz", ra0, dec0, roll, LOC, NOW)
    step = 0.2
    up = _image_angle(ra0, dec0, roll, *_altaz_point_j2000(alt + step, az))
    assert _angle_diff(axes.axis2_angle_deg, up) < 1.5
    right = _image_angle(ra0, dec0, roll, *_altaz_point_j2000(alt, az + step))
    assert _angle_diff(axes.axis1_angle_deg, right) < 1.5


@pytest.mark.parametrize("dec", [-30.0, 10.0, 75.0])
@pytest.mark.parametrize("roll", [0.0, 90.0, 333.0])
def test_eq_axes_match_projection(dec, roll):
    ra0, dec0 = jnow_to_j2000(120.0, dec)
    axes = mount_axes("eq", ra0, dec0, roll, None, NOW)
    north = _image_angle(ra0, dec0, roll, *jnow_to_j2000(120.0, dec + 0.2))
    east = _image_angle(ra0, dec0, roll, *jnow_to_j2000(120.2, dec))
    assert _angle_diff(axes.axis2_angle_deg, north) < 1.0
    assert _angle_diff(axes.axis1_angle_deg, east) < 1.0


# -- guidance --------------------------------------------------------------------


def test_altaz_needs_location():
    assert mount_axes("altaz", 10.0, 10.0, 0.0, None, NOW) is None
    assert compute_mount_guidance("altaz", 10.0, 10.0, 0.0, 12.0, 10.0, None, NOW) is None


def test_altaz_guidance_is_in_mount_degrees():
    ra0, dec0 = _altaz_point_j2000(40.0, 100.0)
    ra_t, dec_t = _altaz_point_j2000(45.0, 88.0)
    g = compute_mount_guidance("altaz", ra0, dec0, 0.0, ra_t, dec_t, LOC, NOW)
    assert g.axis1_deg == pytest.approx(-12.0, abs=0.01)  # turn left
    assert g.axis2_deg == pytest.approx(5.0, abs=0.01)  # raise
    assert not g.near_pole


def test_near_zenith_base_turn_exceeds_sky_distance():
    """At 85° a 30° base turn is only ~2.6° on the sky; guidance says 30°."""
    ra0, dec0 = _altaz_point_j2000(85.0, 10.0)
    ra_t, dec_t = _altaz_point_j2000(85.0, 40.0)
    g = compute_mount_guidance("altaz", ra0, dec0, 0.0, ra_t, dec_t, LOC, NOW)
    nav = compute_navigation(ra0, dec0, 0.0, ra_t, dec_t, FOV, W, H)
    assert g.axis1_deg == pytest.approx(30.0, abs=0.01)
    assert nav.separation_deg < 3.0
    assert g.near_pole


def test_altaz_turn_wraps_the_short_way():
    ra0, dec0 = _altaz_point_j2000(30.0, 350.0)
    ra_t, dec_t = _altaz_point_j2000(30.0, 10.0)
    g = compute_mount_guidance("altaz", ra0, dec0, 0.0, ra_t, dec_t, LOC, NOW)
    assert g.axis1_deg == pytest.approx(20.0, abs=0.01)


def test_eq_guidance():
    ra0, dec0 = jnow_to_j2000(100.0, 20.0)
    ra_t, dec_t = jnow_to_j2000(95.0, 23.0)
    g = compute_mount_guidance("eq", ra0, dec0, 0.0, ra_t, dec_t, None, NOW)
    assert g.axis1_deg == pytest.approx(-5.0, abs=0.01)  # west
    assert g.axis2_deg == pytest.approx(3.0, abs=0.01)  # north
    assert g.pointing_alt_deg is None


def test_jnow_helpers_roundtrip():
    ra, dec = j2000_to_jnow(*jnow_to_j2000(33.0, 44.0))
    assert ra == pytest.approx(33.0, abs=1e-9) and dec == pytest.approx(44.0, abs=1e-9)


# -- config -----------------------------------------------------------------------


def test_mount_mode_default_and_roundtrip(tmp_path):
    cfg = ConfigManager(config_dir=tmp_path / "c")
    assert cfg.mount_mode == "altaz"
    cfg.mount_mode = "eq"
    assert cfg.mount_mode == "eq"
    with pytest.raises(ValueError):
        cfg.mount_mode = "dob"


def test_old_finder_rotation_is_unmirrored_once(tmp_path):
    d = tmp_path / "c"
    d.mkdir()
    (d / "config.json").write_text(json.dumps({
        "version": 1,
        "calibration": {"finder_rotation": 271.0, "sync_d_body": None},
    }))
    cfg = ConfigManager(config_dir=d)
    assert cfg.finder_rotation == pytest.approx(89.0)
    cfg.save()
    assert ConfigManager(config_dir=d).finder_rotation == pytest.approx(89.0)


def test_new_config_finder_rotation_untouched(tmp_path):
    cfg = ConfigManager(config_dir=tmp_path / "c")
    cfg.finder_rotation = 45.0
    cfg.save()
    assert ConfigManager(config_dir=tmp_path / "c").finder_rotation == 45.0
