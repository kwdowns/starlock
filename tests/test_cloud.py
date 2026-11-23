"""Tests for the optional Starlock Cloud link (evf/cloud/)."""

import json
import os
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from aiohttp import ClientSession

from evf.cloud.client import CloudClient, CloudError, Unauthorized
from evf.cloud.link import CloudLink
from evf.cloud.pointing import (
    HEARTBEAT_S,
    PointingReporter,
    SendPolicy,
    build_pointing_body,
)
from evf.cloud.service import CloudService, PairingError, check_base_url
from evf.cloud.uploader import ObservationUploader, to_cloud_entry
from evf.config.manager import ConfigManager
from evf.engine.frame_buffer import LatestFrame
from evf.engine.goto_target import GotoTarget
from evf.engine.observation_log import ObservationStore
from evf.engine.pointing import PointingState
from evf.engine.state import StateMachine
from evf.webserver.server import WebServer

CRED = "sld1.u1.d1.s3cr3t"


# ---------------------------------------------------------------------------
# Pointing body
# ---------------------------------------------------------------------------

def payload(state="TRACKING", valid=True, age=0.4, nav=None, mode="altaz", location=True):
    return {
        "state": state,
        "pointing": {"valid": valid, "ra_deg": 10.61, "dec_deg": 40.95, "solve_age_s": age},
        "nav": nav,
        "mount": {"mode": mode},
        "location": ({"latitude": 51.48, "longitude": 0.0} if location
                     else {"latitude": None, "longitude": None}),
    }


def nav(sep=0.42, mount=True, camera_angle=90.0):
    return {
        "active": True, "target_name": "M31",
        "target_ra_deg": 10.684712, "target_dec_deg": 41.26904,
        "separation_deg": sep, "camera_angle_deg": camera_angle,
        "mount": {"axis1_deg": 0.31, "axis2_deg": -0.28} if mount else None,
    }


def test_tracking_with_mount_axes():
    b = build_pointing_body(payload(nav=nav()), dwelling=True, now=1795230123.0)
    assert b["state"] == "tracking"
    assert b["pointing"]["raJ2000Deg"] == 10.61
    assert b["pointing"]["altDeg"] is not None and 0 <= b["pointing"]["azDeg"] < 360
    assert b["target"] == {"name": "M31", "raJ2000Deg": 10.6847, "decJ2000Deg": 41.269}
    assert b["offsets"] == {"separationDeg": 0.42, "axis1Deg": 0.31, "axis2Deg": -0.28,
                            "frame": "altaz"}
    assert b["onTarget"] is False and b["dwelling"] is True


def test_equatorial_and_camera_frames():
    b = build_pointing_body(payload(nav=nav(), mode="eq"), dwelling=False, now=0)
    assert b["offsets"]["frame"] == "equatorial"
    b = build_pointing_body(payload(nav=nav(sep=2.0, mount=False, camera_angle=90.0)),
                            dwelling=False, now=0)
    assert b["offsets"] == {"separationDeg": 2.0, "axis1Deg": 2.0, "axis2Deg": 0.0,
                            "frame": "camera"}


def test_states_and_on_target():
    assert build_pointing_body(payload(nav=nav(sep=0.1)), dwelling=False, now=0)["onTarget"]
    lost = build_pointing_body(payload(age=30, nav=nav()), dwelling=True, now=0)
    assert lost["state"] == "lost" and lost["pointing"] is None and lost["offsets"] is None
    assert lost["target"]["name"] == "M31" and lost["dwelling"] is False
    assert build_pointing_body(payload(state="SYNC"), dwelling=False, now=0)["state"] == "setup"
    assert build_pointing_body(payload(state="ERROR"), dwelling=False, now=0)["state"] == "idle"
    no_loc = build_pointing_body(payload(location=False), dwelling=False, now=0)
    assert no_loc["pointing"]["altDeg"] is None and no_loc["target"] is None


def test_send_policy():
    p = SendPolicy()
    a = build_pointing_body(payload(nav=nav()), dwelling=False, now=0)
    assert p.due(a, 0)
    p.sent(a, 0)
    assert not p.due(a, 1)                               # unchanged
    sep = a["offsets"]["separationDeg"]
    step = max(0.2, min(2.0, sep * 0.25))
    nudged = {**a, "offsets": {**a["offsets"], "axis1Deg": a["offsets"]["axis1Deg"] + step / 2}}
    assert not p.due(nudged, 30)                         # too small to matter
    moved = {**a, "offsets": {**a["offsets"], "axis1Deg": a["offsets"]["axis1Deg"] + step * 1.1}}
    assert not p.due(moved, 10)                          # meaningful, but < 15 s
    assert p.due(moved, 15.1)
    on = {**a, "onTarget": True}
    assert not p.due(on, 1.0)                            # major change: within 2 s
    assert p.due(on, 2.1)
    assert p.due(a, HEARTBEAT_S + 0.1)                   # heartbeat while tracking
    idle = {**a, "state": "idle"}
    p.sent(idle, 100)
    assert not p.due(idle, 100 + HEARTBEAT_S + 1)        # no heartbeat when idle
    delay = p.failed(200)
    assert delay == 30 and not p.due(on, 229) and p.due(on, 231)
    assert p.failed(231) == 60


def test_send_policy_when_nobody_watches():
    p = SendPolicy()
    a = build_pointing_body(payload(nav=nav()), dwelling=False, now=0)
    p.sent(a, 0, watching=False)
    moved = {**a, "offsets": {**a["offsets"], "axis1Deg": a["offsets"]["axis1Deg"] + 5}}
    assert not p.due(moved, 30)                          # minor changes skipped
    assert p.due({**a, "onTarget": True}, 30)            # major changes still go
    assert p.due(moved, HEARTBEAT_S + 0.1)               # heartbeat: learns when someone watches
    p.sent(moved, 61, watching=True)
    again = {**moved, "offsets": {**moved["offsets"], "axis1Deg": moved["offsets"]["axis1Deg"] + 5}}
    assert p.due(again, 61 + 15.1)
    p.sent(again, 80)                                    # no answer: keep the last word
    assert p.watching is True


def test_an_hour_of_tracking_sends_a_few_hundred_updates_at_most():
    # The scope sweeps toward a target and the solve jitters every update:
    # the old 2 s rule posted ~1,800 times an hour.
    p = SendPolicy()
    base = build_pointing_body(payload(nav=nav()), dwelling=False, now=0)
    sent = 0
    for i in range(7200):                                # 0.5 s polls for an hour
        t = i * 0.5
        body = {**base, "offsets": {**base["offsets"], "axis1Deg": (i % 40) * 0.3}}
        if p.due(body, t):
            p.sent(body, t)
            sent += 1
    assert sent <= 250


class FakeClient:
    def __init__(self, fail=None):
        self.pointing, self.batches, self.fail = [], [], fail
        self._timeout = 10

    def _maybe_fail(self):
        if self.fail:
            raise self.fail

    response = None

    def post_pointing(self, body, session):
        self._maybe_fail()
        self.pointing.append((body, session))
        return self.response

    def post_observations(self, entries):
        self._maybe_fail()
        self.batches.append(entries)
        return {"results": [{"entryId": e["entryId"], "status": "created"} for e in entries]}


def test_reporter_seq_session_and_ended():
    client = FakeClient()
    snap = {"p": payload(nav=nav())}
    t = {"mono": 0.0}
    r = PointingReporter(lambda: client, lambda: snap["p"], lambda: False, lambda: None,
                         wall=lambda: 1795230123.0, mono=lambda: t["mono"])
    assert r.step() and not r.step()
    snap["p"] = payload(nav=nav(sep=0.1))
    t["mono"] = 0.5
    assert not r.step()                                  # on target: a major change, but < 2 s
    t["mono"] = 2.1
    assert r.step()
    assert r._policy.watching is True                    # the service said nothing
    client.response = {"pushed": False, "watching": False}
    t["mono"] = 70.0
    assert r.step()                                      # heartbeat
    assert r._policy.watching is False
    r.stop(send_ended=True)
    seqs = [b["seq"] for b, _ in client.pointing]
    assert seqs == [1, 2, 3, 4]
    assert len({s for _, s in client.pointing}) == 1
    assert client.pointing[-1][0]["state"] == "ended"


def test_reporter_unauthorized_unlinks():
    revoked = []
    client = FakeClient(fail=Unauthorized(401, "revoked"))
    r = PointingReporter(lambda: client, lambda: payload(), lambda: False,
                         lambda: revoked.append(1))
    assert not r.step() and revoked == [1]


def test_reporter_idle_when_unlinked():
    r = PointingReporter(lambda: None, lambda: payload(), lambda: False, lambda: None)
    assert not r.step()


# ---------------------------------------------------------------------------
# Store sync bookkeeping and uploader
# ---------------------------------------------------------------------------

def make_store(tmp_path, n_closed=2, open_one=True):
    st = ObservationStore(tmp_path / "obs.sqlite3")
    for i in range(n_closed):
        eid = st.open_entry(1795228800.0 + i * 600, 10.0, 41.0, target_name="M31")
        st.close_entry(eid, 1795228800.0 + i * 600 + 120)
    if open_one:
        st.open_entry(1795230000.0, 83.8, -5.4)
    return st


def test_db_uuid_is_stable_and_old_databases_migrate(tmp_path):
    path = tmp_path / "old.sqlite3"
    db = sqlite3.connect(path)
    db.executescript("""CREATE TABLE observations (id INTEGER PRIMARY KEY AUTOINCREMENT,
        start_utc REAL NOT NULL, end_utc REAL NOT NULL, is_open INTEGER NOT NULL DEFAULT 1,
        ra_j2000 REAL NOT NULL, dec_j2000 REAL NOT NULL, alt REAL, az REAL, target_name TEXT,
        latitude REAL, longitude REAL, clock TEXT NOT NULL DEFAULT 'system');
        INSERT INTO observations (start_utc, end_utc, is_open, ra_j2000, dec_j2000)
        VALUES (1795228800, 1795228900, 0, 1, 2);""")
    db.commit()
    db.close()
    st = ObservationStore(path)
    uid = st.db_uuid
    assert len(uid) == 32
    assert len(st.pending_cloud(now=1795230000, open_interval_s=300)) == 1
    st.close()
    assert ObservationStore(path).db_uuid == uid


def test_pending_and_synced(tmp_path):
    st = make_store(tmp_path)
    now = 1795230100.0
    pending = st.pending_cloud(now=now, open_interval_s=300)
    assert [e["open"] for e in pending] == [False, False, True]
    st.mark_cloud_synced(pending, now)
    assert st.pending_cloud(now=now, open_interval_s=300) == []
    open_id = pending[-1]["id"]
    st.touch(open_id, 1795230030.0)                      # heartbeat moves the end
    assert st.pending_cloud(now=now + 60, open_interval_s=300) == []      # < 5 min
    assert len(st.pending_cloud(now=now + 301, open_interval_s=300)) == 1
    st.close_entry(open_id, 1795230060.0)                # closing: due at once
    assert len(st.pending_cloud(now=now + 1, open_interval_s=300)) == 1
    st.reset_cloud_sync()
    assert len(st.pending_cloud(now=now, open_interval_s=300)) == 3


def test_cloud_entry_mapping(tmp_path):
    st = make_store(tmp_path, n_closed=1, open_one=False)
    e = to_cloud_entry(st, st.pending_cloud(now=0, open_interval_s=300)[0])
    assert e["entryId"] == f"{st.db_uuid}-1"
    assert e["startUnix"] == 1795228800.0 and e["endUnix"] == 1795228920.0
    assert e["open"] is False and e["targetName"] == "M31" and e["clock"] == "system"
    assert set(e) == {"entryId", "startUnix", "endUnix", "open", "raJ2000Deg", "decJ2000Deg",
                      "altDeg", "azDeg", "targetName", "latitude", "longitude", "clock"}


def test_uploader_success_retry_and_refusal(tmp_path):
    st = make_store(tmp_path)
    ok = FakeClient()
    up = ObservationUploader(lambda: ok, st, lambda: None, wall=lambda: 1795230100.0)
    up.step()
    assert len(ok.batches) == 1 and len(ok.batches[0]) == 3
    up.step()
    assert len(ok.batches) == 1                          # nothing left

    st.reset_cloud_sync()
    down = FakeClient(fail=CloudError(503, "HTTP 503"))
    up = ObservationUploader(lambda: down, st, lambda: None, wall=lambda: 1795230100.0)
    d1, d2 = up.step(), up.step()
    assert 1.5 <= d1 <= 2.5 and 3 <= d2 <= 5             # 2 s, 4 s with jitter
    assert len(st.pending_cloud(now=1795230100.0, open_interval_s=300)) == 3   # kept

    bad = FakeClient(fail=CloudError(400, "HTTP 400: bad"))
    up = ObservationUploader(lambda: bad, st, lambda: None, wall=lambda: 1795230100.0)
    up.step()
    assert st.pending_cloud(now=1795230100.0, open_interval_s=300) == []      # not retried

    st.reset_cloud_sync()
    revoked = []
    gone = FakeClient(fail=Unauthorized(401, "x"))
    ObservationUploader(lambda: gone, st, lambda: revoked.append(1)).step()
    assert revoked == [1]


# ---------------------------------------------------------------------------
# Link file, pairing, unlinking
# ---------------------------------------------------------------------------

class FakeFactoryClient(FakeClient):
    def __init__(self, base_url, credential, claim_error=None):
        super().__init__()
        self.base_url, self.credential, self.claim_error = base_url, credential, claim_error
        self.claims, self.deleted = [], False

    def claim(self, code, name, **kw):
        if self.claim_error:
            raise self.claim_error
        self.claims.append((code, name, kw))
        return {"deviceId": "dev1", "deviceCredential": CRED, "authorizationScheme": "Device"}

    def get_device(self):
        return {"deviceId": "dev1", "name": "Backyard Pi"}

    def delete_device(self):
        self.deleted = True


def make_service(tmp_path, claim_error=None, store=None):
    made = []

    def factory(url, cred):
        c = FakeFactoryClient(url, cred, claim_error)
        made.append(c)
        return c

    svc = CloudService(tmp_path, default_base_url="https://cloud.example", device_local_id="abc",
                       software_version="0.3.0", snapshot=lambda: None, dwelling=lambda: False,
                       store=store, client_factory=factory)
    return svc, made


def test_pair_saves_link_without_exposing_the_credential(tmp_path):
    svc, made = make_service(tmp_path)
    status = svc.pair("k7p4qx9m", name="Backyard Pi")
    assert status["linked"] and status["device_id"] == "dev1"
    assert CRED not in json.dumps(svc.status())
    claim = next(c for c in made if c.claims).claims[0]
    assert claim[0] == "k7p4qx9m" and claim[2]["local_id"] == "abc"
    link_file = tmp_path / "cloud.json"
    assert json.loads(link_file.read_text())["credential"] == CRED
    if sys.platform != "win32":
        assert (os.stat(link_file).st_mode & 0o777) == 0o600
    # A new service instance picks the link up.
    svc2, made2 = make_service(tmp_path)
    assert svc2.status()["linked"] and made2[-1].credential == CRED


def test_pair_errors(tmp_path):
    svc, _ = make_service(tmp_path)
    with pytest.raises(PairingError):
        svc.pair("nope")
    with pytest.raises(PairingError, match="https"):
        svc.pair("K7P4-QX9M", base_url="http://evil.example")
    svc, _ = make_service(tmp_path, claim_error=CloudError(400, "HTTP 400"))
    with pytest.raises(PairingError, match="not valid") as e:
        svc.pair("K7P4-QX9M")
    assert e.value.status == 400
    svc, _ = make_service(tmp_path, claim_error=CloudError(0, "network error"))
    with pytest.raises(PairingError) as e:
        svc.pair("K7P4-QX9M")
    assert e.value.status == 502
    assert not CloudLink(tmp_path).linked


def test_check_base_url():
    assert check_base_url("https://cloud.example/") == "https://cloud.example"
    assert check_base_url("http://localhost:5000") == "http://localhost:5000"
    for bad in ("ftp://x", "https://x/path", "cloud.example"):
        with pytest.raises(PairingError):
            check_base_url(bad)


def test_unlink_and_revocation(tmp_path):
    store = make_store(tmp_path)
    svc, made = make_service(tmp_path, store=store)
    svc.pair("K7P4-QX9M")
    client = made[-1]
    svc.unlink()
    assert client.deleted and not svc.status()["linked"]
    assert not (tmp_path / "cloud.json").exists()
    svc.pair("K7P4-QX9M")
    svc._revoked()
    st = svc.status()
    assert not st["linked"] and "removed" in st["error"]


# ---------------------------------------------------------------------------
# HTTP client against a local server
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *a):
        pass

    def _reply(self, code, body=None):
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        _Handler.seen.append((self.path, dict(self.headers), body))
        if self.path == "/v1/device/pointing":
            if self.headers.get("Authorization") != f"Device {CRED}":
                return self._reply(401, {"title": "Unauthorized"})
            return self._reply(200, {"pushed": False})
        if self.path == "/v1/pairing/claim":
            return self._reply(400, {"title": "Bad code", "detail": "expired"})
        self._reply(404)


@pytest.fixture
def http_server():
    _Handler.seen = []
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_client_headers_and_errors(http_server):
    c = CloudClient(http_server, CRED, timeout=3)
    assert c.post_pointing({"seq": 1, "state": "idle"}, "sess-1") == {"pushed": False}
    path, headers, body = _Handler.seen[-1]
    assert headers["Authorization"] == f"Device {CRED}"
    assert headers["X-Starlock-Session"] == "sess-1" and body["seq"] == 1
    with pytest.raises(Unauthorized):
        CloudClient(http_server, "sld1.wrong", timeout=3).post_pointing({}, "s")
    with pytest.raises(CloudError) as e:
        CloudClient(http_server, timeout=3).claim("K7P4-QX9M", "Pi", model=None,
                                                  software_version=None, local_id=None)
    assert e.value.status == 400 and "expired" in str(e.value)
    assert "Authorization" not in _Handler.seen[-1][1]   # claim is unauthenticated
    with pytest.raises(CloudError) as e:
        CloudClient("http://127.0.0.1:9", timeout=1).get_device()
    assert e.value.status == 0 and e.value.retryable


# ---------------------------------------------------------------------------
# Web endpoints
# ---------------------------------------------------------------------------

@pytest.fixture
def server_with_cloud(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = ConfigManager(config_dir=tmp_path / "evf-config")
    cfg._data["webserver"]["port"] = 0
    svc, _ = make_service(tmp_path / "cloud")
    ws = WebServer(PointingState(), StateMachine(), GotoTarget(), cfg,
                   frame_buffer=LatestFrame(), cloud=lambda: svc)
    ws.start()
    for _ in range(20):
        if ws._port is not None:
            break
        threading.Event().wait(0.05)
    yield ws, svc
    ws.stop()


@pytest.mark.asyncio
async def test_cloud_endpoints(server_with_cloud):
    ws, svc = server_with_cloud
    base = f"http://127.0.0.1:{ws._port}"
    async with ClientSession() as s:
        async with s.get(f"{base}/api/cloud") as r:
            assert (await r.json())["linked"] is False
        async with s.post(f"{base}/api/cloud/pair", json={"code": "bad"}) as r:
            assert r.status == 400
        async with s.post(f"{base}/api/cloud/pair", json={"code": "K7P4-QX9M"}) as r:
            assert r.status == 200
            data = await r.json()
            assert data["linked"] and CRED not in json.dumps(data)
        async with s.get(f"{base}/api/cloud") as r:
            assert CRED not in await r.text()
        async with s.delete(f"{base}/api/cloud") as r:
            assert r.status == 204
    assert not svc.status()["linked"]
    assert ws.build_payload()["state"]
