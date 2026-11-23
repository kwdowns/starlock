"""Moon / planets / bright asteroids: positions and the /api/solar-system endpoint."""

import math
import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from aiohttp import ClientSession

from evf.config.manager import ConfigManager
from evf.engine.frame_buffer import LatestFrame
from evf.engine.goto_target import GotoTarget
from evf.engine.pointing import PointingState
from evf.engine.solar_system import load_minor_planets, positions
from evf.engine.state import StateMachine
from evf.paths import minor_planets_json
from evf.webserver.server import WebServer

T = 1795400000  # 2026-11-22T01:33:20Z

# JPL Horizons, geocentric astrometric J2000 at T.
HORIZONS = {
    "Ceres": (116.1766, 25.3287),
    "Vesta": (15.2753, -4.2357),
    "Pallas": (13.2698, -21.5077),
    "Jupiter": (148.5232, 13.5737),
    "Neptune": (1.7908, -0.7536),
    "Moon": (35.2572, 19.1624),
}


def _sep_arcmin(a, b):
    ra1, d1, ra2, d2 = map(math.radians, (*a, *b))
    c = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(ra1 - ra2)
    return math.degrees(math.acos(min(1.0, c))) * 60


def test_matches_jpl_horizons():
    bodies = {b["name"]: b for b in positions(T, minor_planets=load_minor_planets(minor_planets_json()))}
    for name, ref in HORIZONS.items():
        b = bodies[name]
        assert _sep_arcmin((b["ra_j2000_deg"], b["dec_j2000_deg"]), ref) < 1.0, name


def test_lists_planets_and_never_the_sun():
    names = [b["name"] for b in positions(T)]
    assert names[:9] == ["Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn",
                         "Uranus", "Neptune", "Pluto"]
    assert "Sun" not in names


def test_topocentric_moon_differs_by_parallax():
    geo = next(b for b in positions(T) if b["id"] == "moon")
    topo = next(b for b in positions(T, 40.0, -75.0) if b["id"] == "moon")
    shift = _sep_arcmin((geo["ra_j2000_deg"], geo["dec_j2000_deg"]),
                        (topo["ra_j2000_deg"], topo["dec_j2000_deg"]))
    assert 5 < shift < 65


def test_fields_and_near_sun_flag():
    bodies = positions(T, minor_planets=load_minor_planets(minor_planets_json()))
    mercury = next(b for b in bodies if b["id"] == "mercury")
    assert mercury["constellation"] == "Libra"
    assert {"magnitude", "elongation_deg", "near_sun", "kind", "distance_au"} <= mercury.keys()
    assert next(b for b in bodies if b["id"] == "ceres")["kind"] == "dwarf-planet"
    assert all(b["near_sun"] == (b["elongation_deg"] < 15) for b in bodies)


def test_missing_elements_file_lists_no_asteroids(tmp_path):
    assert load_minor_planets(tmp_path / "nope.json") == []


@pytest.fixture
def server(tmp_path):
    cfg = ConfigManager(config_dir=tmp_path / "cfg")
    cfg._data["webserver"]["port"] = 0
    ws = WebServer(PointingState(), StateMachine(), GotoTarget(), cfg,
                   frame_buffer=LatestFrame(), actions=MagicMock(),
                   location=lambda: {"latitude": 40.0, "longitude": -75.0, "source": "manual"})
    ws.start()
    for _ in range(40):
        if ws._port is not None:
            break
        threading.Event().wait(0.05)
    yield ws
    ws.stop()


@pytest.mark.asyncio
async def test_api(server):
    base = f"http://127.0.0.1:{server._port}/api/solar-system"
    async with ClientSession() as s:
        async with s.get(base, params={"at": "2026-11-22T01:33:20Z"}) as r:
            data = await r.json()
            assert r.status == 200
        assert data["at_utc"] == "2026-11-22T01:33:20Z" and data["topocentric"] is True
        assert {b["id"] for b in data["bodies"]} >= {"moon", "jupiter", "neptune", "ceres", "vesta"}
        async with s.get(base) as r:
            assert r.status == 200
            now = datetime.fromisoformat((await r.json())["at_utc"].replace("Z", "+00:00"))
            assert abs((now - datetime.now(timezone.utc)).total_seconds()) < 120
        async with s.get(base, params={"at": "yesterday"}) as r:
            assert r.status == 400
