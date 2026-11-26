"""Saved observing sites and equipment (specs/start/SPEC_EQUIPMENT_SITES.md):
validation, migration, the site <-> location/horizon link, optics, the
on-target radius, the HTTP routes and the observation log columns."""

import csv
import io
import json
import sqlite3
import threading
from types import SimpleNamespace

import pytest
from aiohttp import ClientSession

from evf.config import observing as obs
from evf.config.manager import DEFAULT_HORIZON, ConfigManager
from evf.engine.clock import Clock
from evf.engine.engine import Engine
from evf.engine.frame_buffer import LatestFrame
from evf.engine.goto_target import GotoTarget
from evf.engine.navigation import on_target_radius_deg
from evf.engine.observation_log import (
    CSV_HEADER,
    ObservationLogger,
    ObservationStore,
    entries_to_csv,
)
from evf.engine.pointing import PointingState
from evf.engine.state import StateMachine
from evf.webserver.server import WebServer

SITE = {"name": "Back yard", "latitude": 40.01, "longitude": -105.27}
DOB = {"name": '8" Dob', "aperture_mm": 203, "focal_length_mm": 1200}
PLOSSL = {"name": "25 mm Plössl", "focal_length_mm": 25, "afov_deg": 52}
TELRAD = {"name": "Telrad", "kind": "reflex", "rings_deg": [0.5, 2, 4]}
RACI = {"name": "8x50 RACI", "kind": "optical", "field_deg": 6}


def _write_config(path, data):
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.json").write_text(json.dumps({"version": 1, **data}))


def _saved(cfg_dir):
    return json.loads((cfg_dir / "config.json").read_text())


# -- validation -------------------------------------------------------------------

def test_validate_items_and_defaults():
    site = obs.validate_item("sites", {**SITE, "id": "ignored", "extra": 1})
    assert site == {**SITE, "horizon": DEFAULT_HORIZON}
    assert obs.validate_item("sites", {**SITE, "horizon": [0] * 16})["horizon"] == [0] * 16
    assert obs.validate_item("telescopes", DOB) == DOB
    assert obs.validate_item("eyepieces", {"name": "10 mm", "focal_length_mm": 10}) == {
        "name": "10 mm", "focal_length_mm": 10, "afov_deg": 52}
    assert obs.validate_item("finders", {"name": "Telrad", "kind": "reflex"})["rings_deg"] == [
        0.5, 2, 4]
    assert obs.validate_item("finders", {"name": "Red dot", "kind": "reflex",
                                         "rings_deg": [0.1]})["rings_deg"] == [0.1]
    # Fields of the other finder kind are dropped.
    assert obs.validate_item("finders", {**RACI, "rings_deg": [1]}) == RACI
    assert obs.validate_item("sites", {**SITE, "name": "  Field  "})["name"] == "Field"


@pytest.mark.parametrize("kind, body", [
    ("sites", {**SITE, "name": "   "}),
    ("sites", {**SITE, "name": "x" * 61}),
    ("sites", {**SITE, "name": 5}),
    ("sites", {**SITE, "latitude": 91}),
    ("sites", {**SITE, "longitude": -180.5}),
    ("sites", {**SITE, "latitude": None}),
    ("sites", {**SITE, "latitude": True}),
    ("sites", {**SITE, "horizon": [3] * 15}),
    ("sites", {**SITE, "horizon": [512] * 16}),
    ("telescopes", {**DOB, "aperture_mm": 9}),
    ("telescopes", {**DOB, "focal_length_mm": 20001}),
    ("telescopes", {**DOB, "focal_length_mm": "1200"}),
    ("eyepieces", {**PLOSSL, "focal_length_mm": 0.5}),
    ("eyepieces", {**PLOSSL, "afov_deg": 121}),
    ("finders", {**RACI, "kind": "laser"}),
    ("finders", {**RACI, "field_deg": 0.4}),
    ("finders", {"name": "x", "kind": "optical"}),
    ("finders", {**TELRAD, "rings_deg": []}),
    ("finders", {**TELRAD, "rings_deg": [0.5, 1, 2, 3, 4]}),
    ("finders", {**TELRAD, "rings_deg": [2, 1]}),
    ("finders", {**TELRAD, "rings_deg": [1, 1]}),
    ("finders", {**TELRAD, "rings_deg": [0.05]}),
    ("finders", {**TELRAD, "rings_deg": [11]}),
    ("finders", {**TELRAD, "rings_deg": 2}),
    ("sites", [1, 2]),
])
def test_validate_rejects(kind, body):
    with pytest.raises(ValueError):
        obs.validate_item(kind, body)


def test_unknown_kind_is_not_found():
    with pytest.raises(obs.NotFound):
        obs.validate_item("mounts", {"name": "x"})


def test_load_drops_broken_entries(tmp_path):
    good = "a" * 32
    _write_config(tmp_path, {"observing": {
        "sites": [{**SITE, "id": good}, {**SITE, "id": "short"},
                  {**SITE, "id": good}, {**SITE, "id": "b" * 32, "latitude": 100}, "junk"],
        "telescopes": "not a list",
        "eyepieces": [{**PLOSSL, "id": "c" * 32}],
        "current": {"site_id": good, "telescope_id": "d" * 32, "eyepiece_id": "c" * 32},
    }})
    cfg = ConfigManager(config_dir=tmp_path)
    o = cfg.observing
    assert [s["id"] for s in o["sites"]] == [good]
    assert o["sites"][0]["horizon"] == DEFAULT_HORIZON  # missing: the default
    assert o["telescopes"] == [] and o["finders"] == []
    assert o["current"] == {"site_id": good, "telescope_id": None,
                            "eyepiece_id": "c" * 32, "finder_id": None}
    assert _saved(tmp_path)["observing"] == o  # cleaned copy written back


def test_load_caps_lists_at_50(tmp_path):
    many = [{**DOB, "id": f"{n:032x}"} for n in range(60)]
    _write_config(tmp_path, {"observing": {"telescopes": many}})
    assert len(ConfigManager(config_dir=tmp_path).observing["telescopes"]) == 50


def test_load_survives_a_non_object(tmp_path):
    _write_config(tmp_path, {"observing": "garbage",
                             "location": {"latitude": 1.0, "longitude": 2.0}})
    o = ConfigManager(config_dir=tmp_path).observing
    assert o == obs.empty()


# -- migration ----------------------------------------------------------------------

def test_migration_makes_my_site_from_location_and_horizon(tmp_path):
    mask = [1] * 8 + [7] * 8
    _write_config(tmp_path, {"location": {"latitude": 51.5, "longitude": -0.1},
                             "horizon": {"obscured": mask}})
    cfg = ConfigManager(config_dir=tmp_path)
    o = cfg.observing
    assert len(o["sites"]) == 1
    site = o["sites"][0]
    assert site["name"] == "My site"
    assert (site["latitude"], site["longitude"], site["horizon"]) == (51.5, -0.1, mask)
    assert len(site["id"]) == 32 and int(site["id"], 16) >= 0
    assert o["current"]["site_id"] == site["id"]
    assert cfg.location == (51.5, -0.1) and cfg.horizon == mask
    # Once only: loading again keeps the same single site.
    assert ConfigManager(config_dir=tmp_path).observing == o


def test_migration_without_location_is_empty(tmp_path):
    _write_config(tmp_path, {"location": {"latitude": None, "longitude": None}})
    assert ConfigManager(config_dir=tmp_path).observing == obs.empty()
    assert ConfigManager(config_dir=tmp_path / "fresh").observing == obs.empty()


def test_migration_with_broken_horizon_uses_default(tmp_path):
    _write_config(tmp_path, {"location": {"latitude": 10.0, "longitude": 20.0},
                             "horizon": {"obscured": "bad"}})
    assert ConfigManager(config_dir=tmp_path).observing["sites"][0]["horizon"] == DEFAULT_HORIZON


# -- optics -------------------------------------------------------------------------

def test_optics_maths():
    tel = {**DOB, "id": "t"}
    ep = {**PLOSSL, "id": "e"}
    o = obs.compute_optics(tel, ep, None)
    assert o == {"magnification": 48.0, "true_field_deg": 1.08,
                 "exit_pupil_mm": 4.23, "finder_rings_deg": None}
    o = obs.compute_optics(tel, {"focal_length_mm": 7, "afov_deg": 82}, None)
    assert o["magnification"] == 171.43 and o["true_field_deg"] == 0.48
    assert o["exit_pupil_mm"] == 1.18
    assert obs.compute_optics(tel, None, RACI) == {
        "magnification": None, "true_field_deg": None, "exit_pupil_mm": None,
        "finder_rings_deg": [6]}
    assert obs.compute_optics(None, ep, TELRAD)["finder_rings_deg"] == [0.5, 2, 4]
    assert obs.compute_optics(None, ep, TELRAD)["magnification"] is None


# -- the library: site <-> location / horizon ---------------------------------------

@pytest.fixture
def lib(tmp_path):
    cfg = ConfigManager(config_dir=tmp_path)
    return obs.ObservingLibrary(cfg), cfg, tmp_path


def test_select_site_applies_location_and_horizon(lib):
    library, cfg, path = lib
    mask = [0] * 16
    sid = library.create("sites", {**SITE, "horizon": mask})
    assert cfg.location is None
    library.set_current({"site_id": sid})
    assert cfg.location == (40.01, -105.27) and cfg.horizon == mask
    saved = _saved(path)
    assert saved["location"] == {"latitude": 40.01, "longitude": -105.27}
    assert saved["observing"]["current"]["site_id"] == sid


def test_location_and_horizon_edits_follow_into_site_in_use(lib):
    library, cfg, _ = lib
    a = library.create("sites", SITE)
    b = library.create("sites", {**SITE, "name": "Dark site"})
    library.set_current({"site_id": a})
    library.set_location(41.0, -104.0)
    library.set_horizon([5] * 16)
    sites = {s["id"]: s for s in cfg.observing["sites"]}
    assert (sites[a]["latitude"], sites[a]["longitude"]) == (41.0, -104.0)
    assert sites[a]["horizon"] == [5] * 16
    assert sites[b]["latitude"] == 40.01 and sites[b]["horizon"] == DEFAULT_HORIZON
    library.set_horizon(None)  # reset: the default, into the site too
    assert cfg.observing["sites"][0]["horizon"] == DEFAULT_HORIZON
    # Switching sites brings the other one's values.
    library.set_current({"site_id": b})
    assert cfg.location == (40.01, -105.27) and cfg.horizon == DEFAULT_HORIZON


def test_clearing_location_clears_site_in_use(lib):
    library, cfg, _ = lib
    sid = library.create("sites", SITE)
    library.set_current({"site_id": sid})
    library.set_location(None, None)
    assert cfg.location is None
    assert cfg.observing["current"]["site_id"] is None
    assert len(cfg.observing["sites"]) == 1  # the site itself stays


def test_ad_hoc_location_without_site(lib):
    library, cfg, _ = lib
    sid = library.create("sites", SITE)
    library.set_location(1.0, 2.0)
    library.set_horizon([0] * 16)
    assert cfg.location == (1.0, 2.0)
    assert cfg.observing["sites"][0]["latitude"] == 40.01
    assert cfg.observing["sites"][0]["id"] == sid


def test_bad_location_changes_nothing(lib):
    library, cfg, _ = lib
    sid = library.create("sites", SITE)
    library.set_current({"site_id": sid})
    with pytest.raises(ValueError):
        library.set_location(95.0, 0.0)
    assert cfg.location == (40.01, -105.27)
    assert cfg.observing["sites"][0]["latitude"] == 40.01


def test_update_site_in_use_reapplies(lib):
    library, cfg, _ = lib
    sid = library.create("sites", SITE)
    other = library.create("sites", SITE)
    library.set_current({"site_id": sid})
    library.update("sites", sid, {"name": "Moved", "latitude": -33.0, "longitude": 151.0,
                                  "horizon": [1] * 16})
    assert cfg.location == (-33.0, 151.0) and cfg.horizon == [1] * 16
    library.update("sites", other, {**SITE, "latitude": 0.0})  # not in use: no effect
    assert cfg.location == (-33.0, 151.0)
    with pytest.raises(obs.NotFound):
        library.update("sites", "f" * 32, SITE)


def test_delete_in_use_items(lib):
    library, cfg, _ = lib
    sid = library.create("sites", SITE)
    ep = library.create("eyepieces", PLOSSL)
    tel = library.create("telescopes", DOB)
    library.set_current({"site_id": sid, "eyepiece_id": ep, "telescope_id": tel})
    library.delete("sites", sid)
    library.delete("eyepieces", ep)
    o = cfg.observing
    assert o["sites"] == [] and o["eyepieces"] == []
    assert o["current"] == {"site_id": None, "telescope_id": tel,
                            "eyepiece_id": None, "finder_id": None}
    # The deleted site's location and horizon stay as ad-hoc values.
    assert cfg.location == (40.01, -105.27)
    with pytest.raises(obs.NotFound):
        library.delete("eyepieces", ep)


def test_set_current_partial_null_and_unknown(lib):
    library, cfg, _ = lib
    tel = library.create("telescopes", DOB)
    fid = library.create("finders", RACI)
    library.set_current({"telescope_id": tel, "finder_id": fid})
    library.set_current({"finder_id": None})
    assert cfg.observing["current"]["telescope_id"] == tel
    assert cfg.observing["current"]["finder_id"] is None
    with pytest.raises(obs.NotFound):
        library.set_current({"telescope_id": None, "eyepiece_id": "e" * 32})
    assert cfg.observing["current"]["telescope_id"] == tel  # all or nothing
    with pytest.raises(obs.NotFound):
        library.set_current({"telescope_id": fid})  # a finder's id is no telescope
    with pytest.raises(ValueError):
        library.set_current({"telescope_id": 5})


def test_at_most_50_items(lib):
    library, _, _ = lib
    for _ in range(50):
        library.create("eyepieces", PLOSSL)
    with pytest.raises(ValueError):
        library.create("eyepieces", PLOSSL)


def test_snapshot_and_log_fields(lib):
    library, _, _ = lib
    sid = library.create("sites", SITE)
    tel = library.create("telescopes", DOB)
    ep = library.create("eyepieces", PLOSSL)
    fid = library.create("finders", TELRAD)
    assert library.snapshot()["optics"]["magnification"] is None
    assert library.log_fields() == {"site_name": None, "telescope": None, "eyepiece": None,
                                    "finder": None, "magnification": None}
    library.set_current({"site_id": sid, "telescope_id": tel, "eyepiece_id": ep,
                         "finder_id": fid})
    snap = library.snapshot()
    assert set(snap) == {"sites", "telescopes", "eyepieces", "finders", "current", "optics"}
    assert snap["optics"] == {"magnification": 48.0, "true_field_deg": 1.08,
                              "exit_pupil_mm": 4.23, "finder_rings_deg": [0.5, 2, 4]}
    assert snap["telescopes"][0] == {"id": tel, **DOB}
    assert library.log_fields() == {"site_name": "Back yard", "telescope": '8" Dob',
                                    "eyepiece": "25 mm Plössl", "finder": "Telrad",
                                    "magnification": 48.0}


def test_concurrent_creates_lose_nothing(lib):
    library, cfg, _ = lib
    threads = [threading.Thread(target=library.create, args=("eyepieces", PLOSSL))
               for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(cfg.observing["eyepieces"]) == 20


# -- on target ------------------------------------------------------------------------

def test_on_target_radius_with_and_without_eyepiece():
    # Without an eyepiece: unchanged.
    assert on_target_radius_deg(None) == 0.15
    assert on_target_radius_deg(None, None) == 0.15
    assert on_target_radius_deg(1.0) == pytest.approx(0.3)
    # With the true field: 35 % of it, or 30 % of a big object, 0.05-1.5.
    assert on_target_radius_deg(None, 1.08) == pytest.approx(0.378)
    assert on_target_radius_deg(0.05, 0.48) == pytest.approx(0.168)
    assert on_target_radius_deg(3.0, 1.08) == pytest.approx(0.9)
    assert on_target_radius_deg(None, 0.1) == 0.05    # floor
    assert on_target_radius_deg(None, 6.0) == 1.5     # cap
    assert on_target_radius_deg(20.0, 1.0) == 1.5


# -- HTTP routes and the /ws payload ------------------------------------------------

@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = ConfigManager(config_dir=tmp_path / "evf-config")
    cfg._data["webserver"]["port"] = 0
    engine = Engine(config=cfg)
    goto = GotoTarget()
    ws = WebServer(
        PointingState(), StateMachine(), goto, cfg,
        frame_buffer=LatestFrame(), actions=engine, clock=Clock(),
        location=lambda: engine.location, observing=engine.observing.snapshot,
    )
    ws.start()
    for _ in range(40):
        if ws._port is not None:
            break
        threading.Event().wait(0.05)
    yield ws, engine, cfg, goto
    ws.stop()


async def test_crud_routes(server):
    ws, _, cfg, _ = server
    base = f"http://127.0.0.1:{ws._port}/api/observing"
    async with ClientSession() as s:
        async with s.post(f"{base}/telescopes", json=DOB) as r:
            assert r.status == 201
            tel = (await r.json())["id"]
        assert cfg.observing["telescopes"] == [{"id": tel, **DOB}]
        async with s.post(f"{base}/telescopes", json={**DOB, "aperture_mm": 5}) as r:
            assert r.status == 400 and "aperture_mm" in await r.text()
        async with s.post(f"{base}/mounts", json=DOB) as r:
            assert r.status == 404
        async with s.post(f"{base}/telescopes", data="nope",
                          headers={"Content-Type": "application/json"}) as r:
            assert r.status == 400
        async with s.put(f"{base}/telescopes/{tel}", json={**DOB, "name": "Dob"}) as r:
            assert r.status == 204
        assert cfg.observing["telescopes"][0]["name"] == "Dob"
        async with s.put(f"{base}/telescopes/{'0' * 32}", json=DOB) as r:
            assert r.status == 404
        async with s.put(f"{base}/telescopes/{tel}", json={"name": "Dob"}) as r:
            assert r.status == 400
        async with s.delete(f"{base}/telescopes/{tel}") as r:
            assert r.status == 204
        async with s.delete(f"{base}/telescopes/{tel}") as r:
            assert r.status == 404
        assert cfg.observing["telescopes"] == []


async def test_current_route_and_settings_follow_site(server):
    ws, engine, cfg, _ = server
    root = f"http://127.0.0.1:{ws._port}/api"
    async with ClientSession() as s:
        async with s.post(f"{root}/observing/sites", json={**SITE, "horizon": [0] * 16}) as r:
            sid = (await r.json())["id"]
        async with s.post(f"{root}/observing/current", json={"site_id": sid}) as r:
            assert r.status == 204
        assert engine.location["latitude"] == 40.01 and cfg.horizon == [0] * 16
        async with s.post(f"{root}/observing/current", json={"eyepiece_id": "a" * 32}) as r:
            assert r.status == 404
        async with s.post(f"{root}/observing/current", json=[1]) as r:
            assert r.status == 400
        # The old Settings calls edit the site in use.
        async with s.post(f"{root}/settings",
                          json={"location": {"latitude": 12.5, "longitude": 77.5},
                                "horizon": {"obscured": [9] * 16}}) as r:
            assert r.status == 204
        site = cfg.observing["sites"][0]
        assert (site["latitude"], site["longitude"], site["horizon"]) == (12.5, 77.5, [9] * 16)
        async with s.post(f"{root}/settings", json={"location": None}) as r:
            assert r.status == 204
        assert cfg.observing["current"]["site_id"] is None
        assert engine.location["latitude"] is None


async def test_payload_observing_and_on_target(server):
    ws, engine, _, goto = server
    p = ws.build_payload()
    assert p["observing"] == {
        "sites": [], "telescopes": [], "eyepieces": [], "finders": [],
        "current": {"site_id": None, "telescope_id": None, "eyepiece_id": None,
                    "finder_id": None},
        "optics": {"magnification": None, "true_field_deg": None, "exit_pupil_mm": None,
                   "finder_rings_deg": None},
    }
    goto.set(83.8, -5.4, "M42", None)
    assert ws.build_payload()["nav"]["on_target_deg"] == 0.15
    tel = engine.create_observing_item("telescopes", DOB)
    ep = engine.create_observing_item("eyepieces", PLOSSL)
    fid = engine.create_observing_item("finders", RACI)
    engine.set_observing_current({"telescope_id": tel, "eyepiece_id": ep, "finder_id": fid})
    p = ws.build_payload()
    assert p["observing"]["optics"] == {"magnification": 48.0, "true_field_deg": 1.08,
                                        "exit_pupil_mm": 4.23, "finder_rings_deg": [6]}
    assert p["observing"]["current"]["eyepiece_id"] == ep
    assert p["nav"]["on_target_deg"] == pytest.approx(0.378)
    assert p["nav"]["off_target_deg"] == pytest.approx(0.567)
    json.dumps(p)  # the payload stays JSON


def test_payload_observing_without_callable(tmp_path):
    cfg = ConfigManager(config_dir=tmp_path)
    ws = WebServer(PointingState(), StateMachine(), GotoTarget(), cfg)
    assert ws.build_payload()["observing"]["optics"]["magnification"] is None


# -- observation log ----------------------------------------------------------------

def test_store_adds_equipment_columns_to_old_db(tmp_path):
    path = tmp_path / "obs.sqlite3"
    db = sqlite3.connect(str(path))
    db.executescript("""
        CREATE TABLE observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, start_utc REAL NOT NULL,
            end_utc REAL NOT NULL, is_open INTEGER NOT NULL DEFAULT 1,
            ra_j2000 REAL NOT NULL, dec_j2000 REAL NOT NULL, alt REAL, az REAL,
            target_name TEXT, latitude REAL, longitude REAL,
            clock TEXT NOT NULL DEFAULT 'system');
        INSERT INTO observations (start_utc, end_utc, is_open, ra_j2000, dec_j2000)
            VALUES (1800000000, 1800000060, 0, 1.0, 2.0);
    """)
    db.commit()
    db.close()
    st = ObservationStore(path)
    e = st.list(0, 2e9)[0]
    for field in ("site_name", "telescope", "eyepiece", "finder", "magnification"):
        assert e[field] is None
    st.close()


def test_logger_records_equipment_and_csv(tmp_path):
    st = ObservationStore(tmp_path / "obs.sqlite3")

    class P:
        def read(self):
            return SimpleNamespace(ra_j2000=100.0, dec_j2000=20.0, valid=True,
                                   last_success_timestamp=self.mono)

    p = P()
    fields = {"site_name": "Back yard", "telescope": '8" Dob', "eyepiece": "=25 mm",
              "finder": None, "magnification": 48.0}
    lg = ObservationLogger(st, p, Clock(), equipment=lambda: fields)
    for t in range(1, 40):
        p.mono = float(t)
        lg.step(float(t), 1_800_000_000.0 + t)
    e = st.list(0, 2e9)[0]
    assert (e["site_name"], e["telescope"], e["eyepiece"], e["finder"], e["magnification"]) == (
        "Back yard", '8" Dob', "=25 mm", None, 48.0)
    rows = list(csv.reader(io.StringIO(entries_to_csv(st.list(0, 2e9)))))
    header = rows[0]
    assert header == CSV_HEADER
    i = header.index("longitude")
    assert header[i + 1:i + 6] == ["site_name", "telescope", "eyepiece", "finder",
                                   "magnification"]
    assert header[-1] == "clock"
    assert rows[1][i + 1:i + 6] == ["Back yard", '8" Dob', "'=25 mm", "", "48.00"]
    st.close()


async def test_api_observations_carry_equipment(tmp_path):
    cfg = ConfigManager(config_dir=tmp_path / "cfg")
    cfg._data["webserver"]["port"] = 0
    st = ObservationStore(tmp_path / "cfg" / "obs.sqlite3")
    st.open_entry(1_700_000_000, 10.0, 20.0, equipment={
        "site_name": "Back yard", "telescope": "Dob", "magnification": 48.0})
    ws = WebServer(PointingState(), StateMachine(), GotoTarget(), cfg,
                   observations=ObservationLogger(st, PointingState(), Clock()))
    ws.start()
    for _ in range(40):
        if ws._port is not None:
            break
        threading.Event().wait(0.05)
    try:
        async with ClientSession() as s:
            async with s.get(f"http://127.0.0.1:{ws._port}/api/observations",
                             params={"start": "2023-11-14T00:00:00Z",
                                     "end": "2023-11-15T00:00:00Z"}) as r:
                e = (await r.json())["entries"][0]
            async with s.get(f"http://127.0.0.1:{ws._port}/api/observations.csv",
                             params={"start": "2023-11-14T00:00:00Z",
                                     "end": "2023-11-15T00:00:00Z"}) as r:
                rows = list(csv.reader(io.StringIO(await r.text())))
    finally:
        ws.stop()
        st.close()
    assert e["site_name"] == "Back yard" and e["telescope"] == "Dob"
    assert e["eyepiece"] is None and e["finder"] is None and e["magnification"] == 48.0
    i = rows[0].index("site_name")
    assert rows[1][i:i + 5] == ["Back yard", "Dob", "", "", "48.00"]
