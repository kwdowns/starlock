"""Tests for the observation log: dwell logic, storage, clock, CSV and API."""

import csv
import io
import sqlite3
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from aiohttp import ClientSession

from evf.config.manager import ConfigManager
from evf.engine.frame_buffer import LatestFrame
from evf.engine.goto_target import GotoTarget
from evf.engine.observation_log import (
    Clock,
    DwellTracker,
    ObservationLogger,
    ObservationStore,
    entries_to_csv,
)
from evf.engine.pointing import PointingState
from evf.engine.state import StateMachine
from evf.webserver.server import WebServer

T0 = 1_800_000_000.0  # arbitrary unix time


class FakePointing:
    """Stands in for PointingState; mono time is driven by the test."""

    def __init__(self):
        self.ra = 100.0
        self.dec = 20.0
        self.valid = True
        self.mono = 0.0  # time of last successful solve

    def read(self):
        return SimpleNamespace(
            ra_j2000=self.ra, dec_j2000=self.dec, valid=self.valid,
            last_success_timestamp=self.mono,
        )


def run(logger, pointing, seconds, start, *, solving=True, step=1.0):
    """Advance simulated time one step at a time; returns the new time."""
    t = start
    end = start + seconds
    while t < end:
        t += step
        if solving:
            pointing.mono = t
        logger.step(t, T0 + t)
    return t


@pytest.fixture
def store(tmp_path):
    s = ObservationStore(tmp_path / "obs.sqlite3")
    yield s
    s.close()


def make_logger(store, pointing, **kw):
    return ObservationLogger(store, pointing, Clock(), **kw)


# -- dwell logic ----------------------------------------------------------------

def test_tracker_opens_after_dwell_and_closes_on_move():
    tr = DwellTracker(dwell_s=30, radius_deg=1.0, lost_s=15)
    events = []
    for t in range(0, 40):
        events += tr.update(float(t), T0 + t, (100.0, 20.0))
    assert [e.kind for e in events] == ["open"]
    assert events[0].wall == T0  # entry starts when the dwell began
    events = tr.update(40.0, T0 + 40, (110.0, 20.0))
    assert [e.kind for e in events] == ["close"]
    assert events[0].wall == T0 + 39  # last sample on the old spot


def test_tracker_no_entry_for_short_dwell_or_drift():
    tr = DwellTracker(dwell_s=30, radius_deg=1.0)
    out = []
    for t in range(0, 100):
        # 0.1 deg per second drift: never within 1 deg for 30 s
        out += tr.update(float(t), T0 + t, (100.0 + 0.1 * t, 0.0))
    assert out == []


def test_tracker_jitter_within_radius_is_one_entry():
    tr = DwellTracker(dwell_s=30, radius_deg=1.0)
    out = []
    for t in range(0, 120):
        out += tr.update(float(t), T0 + t, (100.0 + 0.3 * (t % 2), 20.0))
    assert [e.kind for e in out] == ["open"]


def test_tracker_lost_closes_at_last_good_sample():
    tr = DwellTracker(dwell_s=30, lost_s=15)
    for t in range(0, 40):
        tr.update(float(t), T0 + t, (50.0, 10.0))
    out = []
    for t in range(40, 60):
        out += tr.update(float(t), T0 + t, None)
    assert [e.kind for e in out] == ["close"]
    assert out[0].wall == T0 + 39


def test_tracker_brief_loss_keeps_entry():
    tr = DwellTracker(dwell_s=30, lost_s=15)
    out = []
    for t in range(0, 40):
        out += tr.update(float(t), T0 + t, (50.0, 10.0))
    for t in range(40, 46):
        out += tr.update(float(t), T0 + t, None)
    out += tr.update(46.0, T0 + 46, (50.0, 10.0))
    assert [e.kind for e in out] == ["open"]


def test_tracker_ra_wraparound_is_same_spot():
    tr = DwellTracker(dwell_s=30, radius_deg=1.0)
    out = []
    for t in range(0, 40):
        out += tr.update(float(t), T0 + t, (359.8 if t % 2 else 0.2, 0.0))
    assert [e.kind for e in out] == ["open"]


def test_tracker_finish_closes_open_entry():
    tr = DwellTracker(dwell_s=5)
    for t in range(0, 10):
        tr.update(float(t), T0 + t, (1.0, 1.0))
    ev = tr.finish()
    assert [e.kind for e in ev] == ["close"]
    assert tr.finish() == []


# -- logger + storage -------------------------------------------------------------

def test_logger_writes_entry_with_target_and_altaz(store):
    p = FakePointing()
    loc = {"latitude": 40.0, "longitude": -75.0}
    target = (100.3, 20.0, "M42")
    lg = make_logger(store, p, location=lambda: loc, target=lambda: target)
    t = run(lg, p, 45, 0)
    rows = store.list(T0 - 10, T0 + 1000)
    assert len(rows) == 1
    e = rows[0]
    assert e["open"] is True
    assert e["target_name"] == "M42"
    assert e["ra_j2000_deg"] == 100.0 and e["dec_j2000_deg"] == 20.0
    assert e["alt_deg"] is not None and -90 <= e["alt_deg"] <= 90
    assert 0 <= e["az_deg"] < 360
    assert e["latitude"] == 40.0
    # move away -> closed
    p.ra = 130.0
    run(lg, p, 2, t)
    e = store.list(T0 - 10, T0 + 1000)[0]
    assert e["open"] is False
    assert e["duration_s"] >= 30


def test_logger_ignores_far_target_and_missing_location(store):
    p = FakePointing()
    lg = make_logger(store, p, target=lambda: (200.0, 20.0, "Far"))
    run(lg, p, 45, 0)
    e = store.list(T0 - 10, T0 + 1000)[0]
    assert e["target_name"] is None
    assert e["alt_deg"] is None and e["latitude"] is None


def test_logger_loss_of_solve_closes_entry(store):
    p = FakePointing()
    lg = make_logger(store, p)
    t = run(lg, p, 45, 0)
    run(lg, p, 30, t, solving=False)
    e = store.list(T0 - 10, T0 + 1000)[0]
    assert e["open"] is False
    assert e["duration_s"] < 50  # ended at the last good solve


def test_logger_disabled_records_nothing(store):
    p = FakePointing()
    lg = make_logger(store, p, enabled=lambda: False)
    run(lg, p, 120, 0)
    assert store.list(T0 - 10, T0 + 1000) == []


def test_heartbeat_fills_in_target_name_later(store):
    p = FakePointing()
    target = [None]
    lg = make_logger(store, p, target=lambda: target[0])
    t = run(lg, p, 40, 0)
    assert store.list(T0 - 10, T0 + 1000)[0]["target_name"] is None
    target[0] = (100.0, 20.0, "Pleiades")
    run(lg, p, 35, t)
    assert store.list(T0 - 10, T0 + 1000)[0]["target_name"] == "Pleiades"


def test_reopen_after_unclean_stop_closes_stale_entry(tmp_path):
    path = tmp_path / "obs.sqlite3"
    s1 = ObservationStore(path)
    p = FakePointing()
    lg = make_logger(s1, p)
    run(lg, p, 70, 0)  # still open, never stopped: simulates power loss
    assert s1.list(T0 - 10, T0 + 1000)[0]["open"] is True
    s1._db.close()  # no clean shutdown

    s2 = ObservationStore(path)
    lg2 = make_logger(s2, FakePointing())
    lg2.start()
    lg2.stop()
    rows = s2.list(T0 - 10, T0 + 1000)
    assert len(rows) == 1
    assert rows[0]["open"] is False
    assert rows[0]["duration_s"] >= 30  # kept up to the last heartbeat
    s2.close()


def test_committed_entry_is_on_disk_without_close(tmp_path):
    path = tmp_path / "obs.sqlite3"
    s = ObservationStore(path)
    p = FakePointing()
    run(make_logger(s, p), p, 40, 0)
    other = sqlite3.connect(str(path))  # a second reader sees it: it was committed
    assert other.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
    other.close()
    s.close()


def test_range_query_and_delete(store):
    a = store.open_entry(T0, 1.0, 2.0)
    store.close_entry(a, T0 + 100)
    b = store.open_entry(T0 + 1000, 3.0, 4.0)
    store.close_entry(b, T0 + 1100)
    assert [e["id"] for e in store.list(T0 + 500, T0 + 2000)] == [b]
    assert {e["id"] for e in store.list(T0 + 50, T0 + 1050)} == {a, b}  # overlap
    assert store.list(T0 + 200, T0 + 900) == []
    assert store.delete(T0 - 1, T0 + 500) == 1
    assert [e["id"] for e in store.list(0, T0 + 5000)] == [b]


def test_delete_keeps_open_entry(store):
    store.open_entry(T0, 1.0, 2.0)
    assert store.delete(T0 - 10, T0 + 10) == 0


# -- clock ------------------------------------------------------------------------

def test_clock_uses_client_when_host_is_wrong():
    host = [T0]
    c = Clock(lambda: host[0])
    assert c.report_client_time(T0 + 1) is False  # within tolerance
    assert c.now() == T0 and c.source == "system"
    assert c.report_client_time(T0 + 86400 * 400) is True
    assert c.source == "client"
    host[0] += 5
    assert c.now() == pytest.approx(T0 + 5 + 86400 * 400)
    assert c.report_client_time(host[0] + 1) is False  # host fixed itself
    assert c.now() == host[0]


def test_entry_records_clock_source(store):
    p = FakePointing()
    clock = Clock()
    clock.report_client_time(T0 * 2)
    lg = ObservationLogger(store, p, clock)
    run(lg, p, 40, 0)
    assert store.list(0, T0 * 3)[0]["clock"] == "client"


# -- CSV --------------------------------------------------------------------------

def test_csv_format_order_and_escaping(store):
    a = store.open_entry(T0 + 100, 10.5, -5.25, target_name='=cmd, "x"', alt=45.0,
                         az=180.0, latitude=40.0, longitude=-75.0)
    store.close_entry(a, T0 + 200)
    b = store.open_entry(T0, 1.0, 2.0)
    store.close_entry(b, T0 + 60)
    text = entries_to_csv(store.list(0, T0 * 2))
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0][0] == "start_utc" and rows[0][3] == "target"
    assert len(rows) == 3
    assert rows[1][2] == "60" and rows[1][3] == ""
    assert rows[2][3] == "'=cmd, \"x\""  # formula neutralised, quoting round-trips
    assert rows[2][4] == "10.5000" and rows[2][6] == "45.00"
    assert rows[1][0].endswith("Z")


# -- API --------------------------------------------------------------------------

@pytest.fixture
def api(tmp_path):
    cfg = ConfigManager(config_dir=tmp_path / "cfg")
    cfg._data["webserver"]["port"] = 0
    store = ObservationStore(tmp_path / "cfg" / "obs.sqlite3")
    clock = Clock()
    lg = ObservationLogger(store, PointingState(), clock)
    actions = MagicMock()
    ws = WebServer(PointingState(), StateMachine(), GotoTarget(), cfg,
                   frame_buffer=LatestFrame(), actions=actions, observations=lg)
    ws.start()
    for _ in range(40):
        if ws._port is not None:
            break
        threading.Event().wait(0.05)
    yield ws, store, clock, actions
    ws.stop()
    store.close()


def _seed(store):
    a = store.open_entry(1_700_000_000, 10.0, 20.0, target_name="M31")
    store.close_entry(a, 1_700_000_300)
    b = store.open_entry(1_700_100_000, 30.0, 40.0)
    store.close_entry(b, 1_700_100_100)


@pytest.mark.asyncio
async def test_api_list_range(api):
    ws, store, _, _ = api
    _seed(store)
    base = f"http://127.0.0.1:{ws._port}/api/observations"
    async with ClientSession() as s:
        async with s.get(base, params={"start": "2023-11-14T00:00:00Z",
                                       "end": "2023-11-15T00:00:00Z"}) as r:
            data = await r.json()
        assert r.status == 200
        assert [e["target_name"] for e in data["entries"]] == ["M31"]
        assert data["enabled"] is True and data["clock"] == "system"
        async with s.get(base, params={"start": "2023-11-14T00:00:00Z",
                                       "end": "2023-11-17T00:00:00+00:00"}) as r:
            assert len((await r.json())["entries"]) == 2
        async with s.get(base, params={"start": "nonsense"}) as r:
            assert r.status == 400
        async with s.get(base, params={"start": "2024-01-02T00:00:00Z",
                                       "end": "2024-01-01T00:00:00Z"}) as r:
            assert r.status == 400


@pytest.mark.asyncio
async def test_api_csv_download(api):
    ws, store, _, _ = api
    _seed(store)
    async with ClientSession() as s:
        async with s.get(f"http://127.0.0.1:{ws._port}/api/observations.csv",
                         params={"start": "2023-11-14T00:00:00Z",
                                 "end": "2023-11-17T00:00:00Z"}) as r:
            assert r.status == 200
            assert r.headers["Content-Type"].startswith("text/csv")
            cd = r.headers["Content-Disposition"]
            assert cd.startswith('attachment; filename="starlock-observations-20231114')
            rows = list(csv.reader(io.StringIO(await r.text())))
    assert len(rows) == 3 and rows[1][3] == "M31"


@pytest.mark.asyncio
async def test_api_delete_and_clock(api):
    ws, store, clock, _ = api
    _seed(store)
    base = f"http://127.0.0.1:{ws._port}"
    async with ClientSession() as s:
        async with s.delete(f"{base}/api/observations") as r:
            assert r.status == 400  # range required
        async with s.delete(f"{base}/api/observations", params={
                "start": "2023-11-14T00:00:00Z", "end": "2023-11-15T00:00:00Z"}) as r:
            assert (await r.json())["deleted"] == 1
        async with s.post(f"{base}/api/clock", json={"unix_ms": 1_000_000_000_000}) as r:
            assert (await r.json())["client_clock_used"] is True
        async with s.post(f"{base}/api/clock", json={}) as r:
            assert r.status == 400
    assert clock.source == "client"
    assert len(store.list(0, 2_000_000_000)) == 1


@pytest.mark.asyncio
async def test_api_goto_name_and_enable_flag(api):
    ws, _, _, actions = api
    base = f"http://127.0.0.1:{ws._port}"
    async with ClientSession() as s:
        async with s.post(f"{base}/api/goto/set",
                          json={"ra_deg": 1, "dec_deg": 2, "name": " M13 "}) as r:
            assert r.status == 204
        async with s.post(f"{base}/api/settings",
                          json={"observation_log_enabled": False}) as r:
            assert r.status == 204
    actions.set_goto_target.assert_called_once_with(1.0, 2.0, "M13")
    actions.set_observation_log_enabled.assert_called_once_with(False)


def test_goto_target_keeps_name():
    g = GotoTarget()
    g._play_ack = lambda: None
    g.set(1.0, 2.0, "M31")
    assert g.read().name == "M31"
    g.set(3.0, 4.0)
    assert g.read().name is None


def test_config_defaults(tmp_path):
    cfg = ConfigManager(config_dir=tmp_path)
    assert cfg.observation_log_enabled is True
    assert cfg.observation_dwell_s == 30.0 and cfg.observation_radius_deg == 1.0
    cfg.observation_log_enabled = False
    assert ConfigManager(config_dir=tmp_path).observation_log_enabled is False


# -- frames -----------------------------------------------------------------------

def _jpeg(w=1280, h=800, shade=40):
    from PIL import Image
    out = io.BytesIO()
    Image.new("L", (w, h), shade).save(out, "JPEG")
    return out.getvalue()


def test_logger_keeps_a_downscaled_frame_per_entry(store):
    from PIL import Image
    p = FakePointing()
    lg = make_logger(store, p, frame=lambda: _jpeg(), frame_limits=lambda: (10 << 20, 0))
    run(lg, p, 45, 0)
    e = store.list(T0 - 10, T0 + 1000)[0]
    assert e["has_frame"] is True
    with Image.open(io.BytesIO(store.frame(e["id"]))) as img:
        assert max(img.size) == 1024
    assert store.frames_bytes() > 0


def test_no_frame_when_off_or_camera_has_none(store):
    p = FakePointing()
    lg = make_logger(store, p, frame=lambda: _jpeg(), frame_limits=lambda: None)
    run(lg, p, 45, 0)
    lg2 = make_logger(store, p, frame=lambda: None, frame_limits=lambda: (10 << 20, 0))
    p.ra = 200.0
    run(lg2, p, 45, 100)
    assert [e["has_frame"] for e in store.list(T0 - 10, T0 + 1000)] == [False, False]


def test_trim_drops_oldest_frames_but_keeps_entries(store):
    ids = []
    for i in range(5):
        eid = store.open_entry(T0 + i * 100, 10.0 + i, 20.0)
        store.close_entry(eid, T0 + i * 100 + 50)
        store.save_frame(eid, b"x" * 1000)
        ids.append(eid)
    # quota fits 2 frames
    assert store.trim_frames(2500, 0, free_bytes=lambda: 1 << 40) == 3
    kept = {e["id"] for e in store.list(T0 - 1, T0 + 1000) if e["has_frame"]}
    assert kept == {ids[3], ids[4]}
    assert len(store.list(T0 - 1, T0 + 1000)) == 5
    assert not (store.frames_dir / f"{ids[0]}.jpg").exists()
    # low disk: drop more even under quota, but never the one being kept
    assert store.trim_frames(10_000, 5000, keep=ids[4], free_bytes=lambda: 0) == 1
    assert store.frame(ids[4]) is not None and store.frame(ids[3]) is None


def test_delete_removes_frame_files(store):
    eid = store.open_entry(T0, 10.0, 20.0)
    store.close_entry(eid, T0 + 60)
    store.save_frame(eid, b"jpeg")
    assert store.delete(T0 - 1, T0 + 100) == 1
    assert not (store.frames_dir / f"{eid}.jpg").exists()


def test_frame_limits_config(tmp_path):
    cfg = ConfigManager(config_dir=tmp_path / "c")
    assert cfg.observation_frame_limits == (2048 << 20, 1024 << 20)
    cfg._data["observation_log"].update({"frame_quota_mb": 100, "min_free_mb": "x"})
    assert cfg.observation_frame_limits == (100 << 20, 1024 << 20)
    cfg._data["observation_log"]["frames"] = False
    assert cfg.observation_frame_limits is None


@pytest.mark.asyncio
async def test_api_frame(api):
    ws, store, _, _ = api
    eid = store.open_entry(1_700_000_000, 10.0, 20.0)
    store.close_entry(eid, 1_700_000_100)
    store.save_frame(eid, _jpeg(64, 40))
    base = f"http://127.0.0.1:{ws._port}/api/observations"
    async with ClientSession() as s:
        async with s.get(f"{base}/{eid}/frame.jpg") as r:
            assert r.status == 200 and r.content_type == "image/jpeg"
            assert (await r.read())[:2] == b"\xff\xd8"
        async with s.get(f"{base}/{eid + 1}/frame.jpg") as r:
            assert r.status == 404
        async with s.get(f"{base}/abc/frame.jpg") as r:
            assert r.status == 400
