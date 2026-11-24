"""Horizon mask, engine-wide clock and mount-model endpoints."""

import threading
import time
from unittest.mock import MagicMock

import pytest
from aiohttp import ClientSession

from evf.config.manager import DEFAULT_HORIZON, ConfigManager, validate_horizon
from evf.engine.clock import Clock
from evf.engine.frame_buffer import LatestFrame
from evf.engine.goto_target import GotoTarget
from evf.engine.mount_model import MountModel
from evf.engine.pointing import PointingState
from evf.engine.state import StateMachine
from evf.webserver.server import WebServer


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = ConfigManager(config_dir=tmp_path / "evf-config")
    cfg._data["webserver"]["port"] = 0
    actions = MagicMock()
    clock = Clock()
    model = MountModel()
    ws = WebServer(
        PointingState(), StateMachine(), GotoTarget(), cfg,
        frame_buffer=LatestFrame(), actions=actions, clock=clock, mount_model=model,
        location=lambda: {"latitude": 40.0, "longitude": -105.0, "source": "manual"},
    )
    ws.start()
    for _ in range(20):
        if ws._port is not None:
            break
        threading.Event().wait(0.05)
    yield ws, actions, cfg, clock
    ws.stop()


def test_config_horizon_default_and_validation(tmp_path):
    cfg = ConfigManager(config_dir=tmp_path)
    assert cfg.horizon == DEFAULT_HORIZON == [3] * 16
    cfg.horizon = [0] * 15 + [511]
    assert ConfigManager(config_dir=tmp_path).horizon[15] == 511
    cfg.horizon = None
    assert cfg.horizon == DEFAULT_HORIZON
    for bad in ([0] * 15, [512] + [0] * 15, [-1] + [0] * 15, [True] + [0] * 15, "x", None):
        with pytest.raises(ValueError):
            validate_horizon(bad)
    cfg._data["horizon"]["obscured"] = "broken"
    assert cfg.horizon == DEFAULT_HORIZON


@pytest.mark.asyncio
async def test_settings_horizon(server):
    ws, actions, _, _ = server
    url = f"http://127.0.0.1:{ws._port}/api/settings"
    mask = [1] * 8 + [7] * 8
    async with ClientSession() as s:
        async with s.post(url, json={"horizon": {"obscured": mask}}) as resp:
            assert resp.status == 204
        actions.set_horizon.assert_called_once_with(mask)
        async with s.post(url, json={"horizon": None}) as resp:
            assert resp.status == 204
        actions.set_horizon.assert_called_with(None)
        async with s.post(url, json={"horizon": {"obscured": [600] * 16}}) as resp:
            assert resp.status == 400
        async with s.post(url, json={"horizon": [3] * 16}) as resp:
            assert resp.status == 400


@pytest.mark.asyncio
async def test_clock_works_without_observation_log(server):
    ws, _, _, clock = server
    url = f"http://127.0.0.1:{ws._port}/api/clock"
    async with ClientSession() as s:
        async with s.post(url, json={"unix_ms": (time.time() + 3600) * 1000}) as resp:
            body = await resp.json()
        assert body["client_clock_used"] is True
        assert body["offset_s"] == pytest.approx(3600, abs=2)
        assert clock.now() == pytest.approx(time.time() + 3600, abs=2)
        async with s.post(url, json={"unix_ms": "nope"}) as resp:
            assert resp.status == 400
        async with s.post(url, json={"unix_ms": 1000}) as resp:
            assert resp.status == 400
        async with s.post(url, json={"unix_ms": time.time() * 1000}) as resp:
            assert (await resp.json())["client_clock_used"] is False
    assert clock.source == "system"


@pytest.mark.asyncio
async def test_payload_has_horizon_clock_and_model(server):
    ws, _, cfg, clock = server
    cfg.horizon = [5] * 16
    clock.report_client_time(time.time() - 600)
    p = ws.build_payload()
    assert p["horizon"] == {"obscured": [5] * 16}
    assert p["clock"]["source"] == "client"
    assert p["clock"]["offset_s"] == pytest.approx(-600, abs=2)
    model = p["mount"]["model"]
    assert model["state"] == "collecting"
    assert model["needed"] == 8 and model["samples"] == 0


@pytest.mark.asyncio
async def test_mount_model_reset(server):
    ws, _, _, _ = server
    async with ClientSession() as s:
        async with s.post(f"http://127.0.0.1:{ws._port}/api/mount/model/reset") as resp:
            assert resp.status == 204
