"""Request guard: Host / Origin / Content-Type checks (SPEC_FIRST_RUN §7.2)."""

import threading
from unittest.mock import MagicMock

import aiohttp
import pytest
from aiohttp import ClientSession

from evf.config.manager import ConfigManager
from evf.engine.frame_buffer import LatestFrame
from evf.engine.goto_target import GotoTarget
from evf.engine.pointing import PointingState
from evf.engine.state import StateMachine
from evf.webserver.server import WebServer, request_guard_problem


@pytest.mark.parametrize("host", [
    "192.168.1.52", "192.168.1.52:80", "127.0.0.1:8780", "[fe80::1]:80", "[::1]",
    "localhost:5173", "starlock-3f2a.local", "starlock-3f2a.local.", "rp4b-black",
    "rp4b-black.lan", "pi.home.arpa",
])
def test_local_hosts_pass(host):
    assert request_guard_problem("GET", host, None, "") is None


@pytest.mark.parametrize("host", ["evil.example.com", "evil.example.com:80", "", "1.2.3.4.nip.io"])
def test_public_hosts_refused(host):
    assert request_guard_problem("GET", host, None, "") == "unknown host"


def test_native_clients_without_origin_pass():
    assert request_guard_problem("POST", "192.168.1.52", None, "application/json") is None
    assert request_guard_problem("POST", "192.168.1.52", None, "") is None
    assert request_guard_problem("DELETE", "192.168.1.52", None, "") is None


def test_same_origin_browser_passes():
    assert request_guard_problem("POST", "192.168.1.52", "http://192.168.1.52",
                                 "application/json") is None
    assert request_guard_problem("POST", "localhost:5173", "http://localhost:5173", "") is None


def test_cross_site_writes_refused():
    for method in ("POST", "DELETE", "PUT"):
        assert request_guard_problem(method, "192.168.1.52", "https://evil.example.com",
                                     "application/json") == "cross-site request"
    assert request_guard_problem("POST", "192.168.1.52", "null", "") == "cross-site request"


def test_cross_site_reads_allowed_by_guard():
    # Plain GETs (images, the page itself) aren't writes; /ws is checked separately.
    assert request_guard_problem("GET", "192.168.1.52", "https://evil.example.com", "") is None


@pytest.mark.parametrize("ctype", ["text/plain", "application/x-www-form-urlencoded",
                                   "multipart/form-data"])
def test_simple_content_types_refused(ctype):
    assert request_guard_problem("POST", "192.168.1.52", None, ctype) == \
        "use Content-Type: application/json"


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = ConfigManager(config_dir=tmp_path / "evf-config")
    cfg._data["webserver"]["port"] = 0
    actions = MagicMock()
    ws = WebServer(PointingState(), StateMachine(), GotoTarget(), cfg,
                   frame_buffer=LatestFrame(), actions=actions)
    ws.start()
    for _ in range(20):
        if ws._port is not None:
            break
        threading.Event().wait(0.05)
    yield ws, actions
    ws.stop()


@pytest.mark.asyncio
async def test_cross_site_post_never_reaches_the_engine(server):
    ws, actions = server
    url = f"http://127.0.0.1:{ws._port}/api/goto/clear"
    async with ClientSession() as s:
        async with s.post(url, headers={"Origin": "https://evil.example.com"}) as resp:
            assert resp.status == 403
        async with s.post(url, data="{}", headers={"Content-Type": "text/plain"}) as resp:
            assert resp.status == 403
        async with s.get(f"http://127.0.0.1:{ws._port}/api/version",
                         headers={"Host": "evil.example.com"}) as resp:
            assert resp.status == 403
        async with s.post(url) as resp:
            assert resp.status == 204
    actions.clear_goto_target.assert_called_once()


@pytest.mark.asyncio
async def test_cross_site_websocket_refused(server):
    ws, _ = server
    async with ClientSession() as s:
        with pytest.raises(aiohttp.WSServerHandshakeError):
            await s.ws_connect(f"http://127.0.0.1:{ws._port}/ws",
                               headers={"Origin": "https://evil.example.com"})
        conn = await s.ws_connect(f"http://127.0.0.1:{ws._port}/ws",
                                  headers={"Origin": f"http://127.0.0.1:{ws._port}"})
        await conn.close()


@pytest.mark.asyncio
async def test_capture_frame_needs_debug_mode(server):
    ws, actions = server
    async with ClientSession() as s:
        async with s.post(f"http://127.0.0.1:{ws._port}/api/dev/capture-frame") as resp:
            assert resp.status == 404
    actions.capture_frame.assert_not_called()


def test_owner_allowed_hosts_behind_a_reverse_proxy():
    allowed = ["*.home.example.net", "scope.example.org"]
    # Browser -> proxy keeps Host
    assert request_guard_problem("POST", "starlock.home.example.net", "https://starlock.home.example.net",
                                 "application/json", allowed) is None
    # Proxy rewrote Host to the Pi's IP; Origin is the owner's name
    assert request_guard_problem("POST", "192.168.1.52", "https://scope.example.org",
                                 "application/json", allowed) is None
    assert request_guard_problem("GET", "192.168.1.52", "https://scope.example.org", "",
                                 allowed, "/ws") is None
    # Not on the list
    assert request_guard_problem("GET", "home.example.net.evil.com", None, "", allowed) == "unknown host"
    assert request_guard_problem("GET", "192.168.1.52", "https://evil.example.com", "",
                                 allowed, "/ws") == "cross-site WebSocket"


def test_allowed_hosts_config(tmp_path):
    cfg = ConfigManager(config_dir=tmp_path / "c")
    assert cfg.web_allowed_hosts == []
    cfg._data["webserver"]["allowed_hosts"] = ["Starlock.Home.Example.NET.", " ", 5]
    assert cfg.web_allowed_hosts == ["starlock.home.example.net", "5"]


@pytest.mark.asyncio
async def test_version_reports_api_range(server):
    ws, _ = server
    async with ClientSession() as s:
        async with s.get(f"http://127.0.0.1:{ws._port}/api/version") as resp:
            body = await resp.json()
    assert body["app"] == "starlock"
    assert body["api"] >= body["api_min"] >= 1
