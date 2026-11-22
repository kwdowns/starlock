"""GET /api/catalog/<name> and the goto name in nav.target_name."""

import gzip
import json
import threading

import pytest
from aiohttp import ClientSession

from evf.config.manager import ConfigManager
from evf.engine.frame_buffer import LatestFrame
from evf.engine.goto_target import GotoTarget
from evf.engine.pointing import PointingState
from evf.engine.state import StateMachine
from evf.paths import catalog_data_dir
from evf.webserver.server import CATALOG_NAMES, WebServer


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = ConfigManager(config_dir=tmp_path / "evf-config")
    cfg._data["webserver"]["port"] = 0
    goto = GotoTarget()
    ws = WebServer(PointingState(), StateMachine(), goto, cfg, frame_buffer=LatestFrame())
    ws.start()
    for _ in range(20):
        if ws._port is not None:
            break
        threading.Event().wait(0.05)
    yield ws, goto
    ws.stop()


def test_catalog_files_exist():
    for name in CATALOG_NAMES:
        assert (catalog_data_dir() / f"{name}.json").is_file()


@pytest.mark.asyncio
async def test_catalog_served_compressed_with_etag(server):
    ws, _ = server
    base = f"http://127.0.0.1:{ws._port}"
    async with ClientSession(auto_decompress=False) as s:
        async with s.get(f"{base}/api/catalog/openngc",
                         headers={"Accept-Encoding": "gzip"}) as r:
            assert r.status == 200
            assert r.headers["Content-Encoding"] == "gzip"
            etag = r.headers["ETag"]
            data = json.loads(gzip.decompress(await r.read()))
            assert len(data) > 10000 and {"id", "ra_deg", "dec_deg"} <= set(data[0])
        async with s.get(f"{base}/api/catalog/openngc.json",
                         headers={"If-None-Match": etag}) as r:
            assert r.status == 304
        async with s.get(f"{base}/api/catalog/../config") as r:
            assert r.status == 404
        async with s.get(f"{base}/api/catalog/secrets") as r:
            assert r.status == 404


def test_nav_target_name_comes_from_the_goto(server):
    ws, goto = server
    goto.set(83.82, -5.39, "M42")
    assert ws.build_payload()["nav"]["target_name"] == "M42"
    goto.set(10.68, 41.27)
    assert ws.build_payload()["nav"]["target_name"] is None
