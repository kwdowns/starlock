"""Settings for the address of the computer running Stellarium."""

import threading
from unittest.mock import MagicMock

import pytest
from aiohttp import ClientSession

from evf.config.manager import ConfigManager, normalize_host
from evf.engine.frame_buffer import LatestFrame
from evf.engine.goto_target import GotoTarget
from evf.engine.pointing import PointingState
from evf.engine.state import StateMachine
from evf.webserver.server import WebServer


@pytest.mark.parametrize("raw, clean", [
    ("", ""),
    (None, ""),
    ("   ", ""),
    ("192.168.1.20", "192.168.1.20"),
    ("  192.168.1.20 ", "192.168.1.20"),
    ("my-laptop", "my-laptop"),
    ("My-Laptop.local", "My-Laptop.local"),
    ("my-laptop.local.", "my-laptop.local"),
    ("2001:db8::5", "2001:db8::5"),
    ("[2001:db8::5]", "2001:db8::5"),
    ("2001:DB8:0:0:0:0:0:5", "2001:db8::5"),
    ("::1", "::1"),
])
def test_normalize_host_accepts(raw, clean):
    assert normalize_host(raw) == clean


@pytest.mark.parametrize("raw", [
    "http://192.168.1.20",
    "192.168.1.20:8090",
    "192.168.1.20/",
    "my laptop",
    "-bad.example",
    "bad-.example",
    "a..b",
    "under_score.local",
    "a" * 64,
    ("a" * 60 + ".") * 5 + "com",
    5,
    ["192.168.1.20"],
])
def test_normalize_host_rejects(raw):
    with pytest.raises(ValueError):
        normalize_host(raw)


def test_config_default_is_empty(tmp_path):
    cfg = ConfigManager(config_dir=tmp_path / "cfg")
    assert cfg.stellarium_rc_host == ""


def test_config_roundtrip_and_clear(tmp_path):
    cfg = ConfigManager(config_dir=tmp_path / "cfg")
    cfg.stellarium_rc_host = " 192.168.1.20 "
    assert cfg.stellarium_rc_host == "192.168.1.20"
    assert ConfigManager(config_dir=tmp_path / "cfg").stellarium_rc_host == "192.168.1.20"
    cfg.stellarium_rc_host = ""
    assert cfg.stellarium_rc_host == ""
    assert ConfigManager(config_dir=tmp_path / "cfg").stellarium_rc_host == ""


def test_config_rejects_bad_value_and_keeps_old(tmp_path):
    cfg = ConfigManager(config_dir=tmp_path / "cfg")
    cfg.stellarium_rc_host = "10.0.0.7"
    with pytest.raises(ValueError):
        cfg.stellarium_rc_host = "http://10.0.0.8:8090"
    assert cfg.stellarium_rc_host == "10.0.0.7"


def test_config_hand_edited_garbage_reads_empty(tmp_path):
    cfg = ConfigManager(config_dir=tmp_path / "cfg")
    cfg.set("stellarium", "remote_control_host", "not a host!")
    assert cfg.stellarium_rc_host == ""


@pytest.fixture
def server_and_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = ConfigManager(config_dir=tmp_path / "evf-config")
    cfg._data["webserver"]["port"] = 0  # ephemeral; bypasses validator
    actions = MagicMock()
    ws = WebServer(
        PointingState(), StateMachine(), GotoTarget(), cfg,
        frame_buffer=LatestFrame(),
        actions=actions,
    )
    ws.start()
    for _ in range(20):
        if ws._port is not None:
            break
        threading.Event().wait(0.05)
    yield ws, actions
    ws.stop()


async def _post(ws, body):
    async with ClientSession() as s:
        async with s.post(f"http://127.0.0.1:{ws._port}/api/settings", json=body) as resp:
            return resp.status, await resp.text()


@pytest.mark.asyncio
async def test_api_sets_host(server_and_actions):
    ws, actions = server_and_actions
    status, _ = await _post(ws, {"stellarium_rc_host": " 192.168.1.20 "})
    assert status == 204
    actions.set_stellarium_rc_host.assert_called_once_with("192.168.1.20")


@pytest.mark.asyncio
async def test_api_empty_clears_host(server_and_actions):
    ws, actions = server_and_actions
    status, _ = await _post(ws, {"stellarium_rc_host": ""})
    assert status == 204
    actions.set_stellarium_rc_host.assert_called_once_with("")


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["http://pc:8090", "pc:8090", "has space", "x" * 300, 42])
async def test_api_rejects_bad_host(server_and_actions, bad):
    ws, actions = server_and_actions
    status, text = await _post(ws, {"stellarium_rc_host": bad})
    assert status == 400
    assert "stellarium_rc_host" in text
    actions.set_stellarium_rc_host.assert_not_called()


def test_engine_action_saves_and_refreshes(tmp_path):
    from evf.engine.engine import Engine

    eng = Engine.__new__(Engine)
    eng._config = ConfigManager(config_dir=tmp_path / "cfg")
    eng._stellarium = MagicMock()
    eng.set_stellarium_rc_host("192.168.1.20")
    assert eng._config.stellarium_rc_host == "192.168.1.20"
    eng._stellarium.refresh_remote_control.assert_called_once()
    with pytest.raises(ValueError):
        eng.set_stellarium_rc_host("nope:1")
    assert eng._config.stellarium_rc_host == "192.168.1.20"
