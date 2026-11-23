# Copyright (C) 2026 Arun Venkataswamy
# Copyright (C) 2026 Kyle Downs
#
# This file is part of Starlock.
#
# Starlock is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Starlock is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Starlock. If not, see <https://www.gnu.org/licenses/>.

"""Tests for POST /api/* action endpoints."""

import asyncio
import threading
from unittest.mock import MagicMock

import pytest
from aiohttp import ClientSession

from evf.config.manager import ConfigManager
from evf.engine.frame_buffer import LatestFrame
from evf.engine.goto_target import GotoTarget
from evf.engine.pointing import PointingState
from evf.engine.state import StateMachine
from evf.webserver.server import WebServer


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


@pytest.mark.asyncio
async def test_wizard_advance(server_and_actions):
    ws, actions = server_and_actions
    async with ClientSession() as s:
        async with s.post(f"http://127.0.0.1:{ws._port}/api/wizard/advance") as resp:
            assert resp.status == 204
    actions.step_advance.assert_called_once()


@pytest.mark.asyncio
async def test_sync_select_with_idx(server_and_actions):
    ws, actions = server_and_actions
    async with ClientSession() as s:
        async with s.post(f"http://127.0.0.1:{ws._port}/api/sync/select", json={"idx": 2}) as resp:
            assert resp.status == 204
    actions.set_sync_selected.assert_called_once_with(2)


@pytest.mark.asyncio
async def test_set_control(server_and_actions):
    ws, actions = server_and_actions
    async with ClientSession() as s:
        async with s.post(f"http://127.0.0.1:{ws._port}/api/control",
                          json={"name": "exposure", "value": 42}) as resp:
            assert resp.status == 204
    actions.set_control.assert_called_once_with("exposure", 42)


@pytest.mark.asyncio
async def test_goto_set_with_ra_dec(server_and_actions):
    ws, actions = server_and_actions
    async with ClientSession() as s:
        async with s.post(
            f"http://127.0.0.1:{ws._port}/api/goto/set",
            json={"ra_deg": 79.1723, "dec_deg": 45.998},
        ) as resp:
            assert resp.status == 204
    actions.set_goto_target.assert_called_once_with(79.1723, 45.998)


@pytest.mark.asyncio
async def test_settings_audio(server_and_actions):
    ws, actions = server_and_actions
    async with ClientSession() as s:
        async with s.post(f"http://127.0.0.1:{ws._port}/api/settings",
                          json={"audio_enabled": False}) as resp:
            assert resp.status == 204
    actions.set_audio_enabled.assert_called_once_with(False)


@pytest.mark.asyncio
async def test_settings_lx200_epoch(server_and_actions):
    ws, actions = server_and_actions
    async with ClientSession() as s:
        async with s.post(f"http://127.0.0.1:{ws._port}/api/settings",
                          json={"lx200_epoch": "j2000"}) as resp:
            assert resp.status == 204
    actions.set_lx200_epoch.assert_called_once_with("j2000")


@pytest.mark.asyncio
async def test_actions_none_returns_503(tmp_path, monkeypatch):
    """When no actions are wired, POST /api/* returns 503 instead of 500."""
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = ConfigManager(config_dir=tmp_path / "evf-config")
    cfg._data["webserver"]["port"] = 0
    ws = WebServer(
        PointingState(), StateMachine(), GotoTarget(), cfg,
        frame_buffer=LatestFrame(),
        # NOTE: no actions= passed
    )
    ws.start()
    try:
        for _ in range(20):
            if ws._port is not None:
                break
            threading.Event().wait(0.05)
        async with ClientSession() as s:
            async with s.post(f"http://127.0.0.1:{ws._port}/api/wizard/advance") as resp:
                assert resp.status == 503
    finally:
        ws.stop()


@pytest.mark.asyncio
async def test_settings_returns_500_when_first_setter_raises(server_and_actions):
    """When set_audio_enabled raises, the response is 500 and later setters are NOT called."""
    ws, actions = server_and_actions
    actions.set_audio_enabled.side_effect = RuntimeError("boom")
    async with ClientSession() as s:
        async with s.post(
            f"http://127.0.0.1:{ws._port}/api/settings",
            json={"audio_enabled": False, "min_matches": 10},
        ) as resp:
            assert resp.status == 500
    actions.set_audio_enabled.assert_called_once_with(False)
    actions.set_min_matches.assert_not_called()


@pytest.mark.asyncio
async def test_settings_location(server_and_actions):
    ws, actions = server_and_actions
    async with ClientSession() as s:
        async with s.post(
            f"http://127.0.0.1:{ws._port}/api/settings",
            json={"location": {"latitude": 13.0878, "longitude": 80.2785}},
        ) as resp:
            assert resp.status == 204
    actions.set_location.assert_called_once_with(13.0878, 80.2785)


@pytest.mark.asyncio
async def test_settings_location_clear(server_and_actions):
    ws, actions = server_and_actions
    async with ClientSession() as s:
        async with s.post(
            f"http://127.0.0.1:{ws._port}/api/settings",
            json={"location": None},
        ) as resp:
            assert resp.status == 204
    actions.set_location.assert_called_once_with(None, None)


@pytest.mark.asyncio
async def test_ws_connect_calls_on_client_connected(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = ConfigManager(config_dir=tmp_path / "evf-config")
    cfg._data["webserver"]["port"] = 0
    calls = []
    ws = WebServer(
        PointingState(), StateMachine(), GotoTarget(), cfg,
        frame_buffer=LatestFrame(),
        actions=MagicMock(),
        on_client_connected=lambda: calls.append(1),
    )
    ws.start()
    try:
        for _ in range(20):
            if ws._port is not None:
                break
            threading.Event().wait(0.05)
        async with ClientSession() as s:
            for _ in range(2):
                async with s.ws_connect(f"http://127.0.0.1:{ws._port}/ws"):
                    pass
        for _ in range(40):  # the handler runs the callback after the handshake
            if len(calls) == 2:
                break
            await asyncio.sleep(0.025)
        assert len(calls) == 2
    finally:
        ws.stop()


@pytest.mark.asyncio
async def test_ws_gets_state_after_idle_and_reconnect(server_and_actions):
    """The broadcast loop sleeps with no clients; a new client must wake it."""
    ws, _ = server_and_actions
    async with ClientSession() as s:
        for _ in range(2):  # second pass: loop went idle again in between
            async with s.ws_connect(f"http://127.0.0.1:{ws._port}/ws") as conn:
                msg = await asyncio.wait_for(conn.receive_str(), timeout=2.0)
                assert msg.startswith("{")
            await asyncio.sleep(0.3)


@pytest.mark.asyncio
async def test_settings_cpu_cap(server_and_actions):
    ws, actions = server_and_actions
    async with ClientSession() as s:
        async with s.post(f"http://127.0.0.1:{ws._port}/api/settings",
                          json={"cpu_cap": False}) as resp:
            assert resp.status == 204
    actions.set_cpu_cap.assert_called_once_with(False)


@pytest.mark.asyncio
async def test_settings_mount_mode(server_and_actions):
    ws, actions = server_and_actions
    async with ClientSession() as s:
        url = f"http://127.0.0.1:{ws._port}/api/settings"
        async with s.post(url, json={"mount_mode": "eq"}) as resp:
            assert resp.status == 204
        async with s.post(url, json={"mount_mode": "fork"}) as resp:
            assert resp.status == 400
    actions.set_mount_mode.assert_called_once_with("eq")


@pytest.mark.asyncio
async def test_pwa_manifest_and_icons_served(server_and_actions, tmp_path, monkeypatch):
    """The manifest is served as application/manifest+json and the page + icons resolve."""
    ws, _ = server_and_actions
    ws.stop()  # restart with a fake build dir (web_dist_dir is read at start)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>Starlock</title>")
    (dist / "manifest.webmanifest").write_text('{"name": "Starlock"}')
    (dist / "icon-192.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr("evf.webserver.server.web_dist_dir", lambda: dist)
    ws._port = None
    ws.start()
    for _ in range(40):
        if ws._port is not None:
            break
        threading.Event().wait(0.05)
    base = f"http://127.0.0.1:{ws._port}"
    async with ClientSession() as s:
        async with s.get(f"{base}/static/manifest.webmanifest") as r:
            assert r.status == 200
            assert r.headers["Content-Type"].startswith("application/manifest+json")
            assert (await r.json(content_type=None))["name"] == "Starlock"
        async with s.get(f"{base}/static/icon-192.png") as r:
            assert r.status == 200
            assert r.headers["Content-Type"] == "image/png"
        async with s.get(f"{base}/") as r:
            assert r.status == 200
            assert "no-cache" in r.headers["Cache-Control"]


def test_on_target_radius_grows_with_size():
    from evf.engine.navigation import on_target_radius_deg
    assert on_target_radius_deg(None) == 0.15
    assert on_target_radius_deg(0.05) == 0.15          # small galaxy: the floor
    assert abs(on_target_radius_deg(185 / 60) - 0.925) < 1e-9  # Alpha Persei Cluster
    assert on_target_radius_deg(15.0) == 1.5           # Great Square: capped


@pytest.mark.asyncio
async def test_goto_set_with_size(server_and_actions):
    ws, actions = server_and_actions
    url = f"http://127.0.0.1:{ws._port}/api/goto/set"
    async with ClientSession() as s:
        async with s.post(url, json={"ra_deg": 51.0, "dec_deg": 49.0,
                                     "name": "Alpha Persei Cluster", "size_deg": 3.08}) as resp:
            assert resp.status == 204
        actions.set_goto_target.assert_called_with(51.0, 49.0, "Alpha Persei Cluster", 3.08)
        async with s.post(url, json={"ra_deg": 1.0, "dec_deg": 2.0, "size_deg": "big"}) as resp:
            assert resp.status == 400
        async with s.post(url, json={"ra_deg": 1.0, "dec_deg": 2.0, "size_deg": -1}) as resp:
            assert resp.status == 204
        actions.set_goto_target.assert_called_with(1.0, 2.0)


def test_goto_target_keeps_size():
    from evf.engine.goto_target import GotoTarget
    t = GotoTarget()
    t.set(10.0, 20.0, "M45", 1.83)
    assert t.read().size_deg == 1.83
    t.set(10.0, 20.0, "Vega")
    assert t.read().size_deg is None


def test_on_target_latch_hysteresis():
    from evf.engine.navigation import OnTargetLatch, off_target_radius_deg
    latch = OnTargetLatch()
    key = (10.0, 41.0, None)
    assert off_target_radius_deg(0.15) == 0.5
    assert latch.update(key, 0.3, 0.15) is False      # not yet on it
    assert latch.update(key, 0.10, 0.15) is True       # on target
    assert latch.update(key, 0.33, 0.15) is True       # nudged by eye: still on
    assert latch.update(key, None, 0.15) is False      # solve lost: reports off...
    assert latch.update(key, 0.4, 0.15) is True        # ...but keeps the latch
    assert latch.update(key, 0.6, 0.15) is False       # really off
    assert latch.update(key, 0.3, 0.15) is False       # must re-enter
    assert latch.update(key, 0.1, 0.15) is True
    assert latch.update((11.0, 41.0, None), 0.1, 0.15) is True   # new target starts fresh
    assert latch.update((12.0, 41.0, None), 0.3, 0.15) is False


@pytest.mark.asyncio
async def test_recenter_endpoint(server_and_actions):
    from evf.engine.engine import RecenterError
    ws, actions = server_and_actions
    url = f"http://127.0.0.1:{ws._port}/api/sync/recenter"
    actions.recenter_on_target.return_value = 0.33
    async with ClientSession() as s:
        async with s.post(url) as resp:
            assert resp.status == 200 and (await resp.json()) == {"shift_deg": 0.33}
        actions.recenter_on_target.side_effect = RecenterError("Set a target first.")
        async with s.post(url) as resp:
            assert resp.status == 409 and await resp.text() == "Set a target first."


def test_recentered_sync_points_at_the_target():
    import numpy as np
    from evf.solver.sync import apply_body_frame_sync, compute_body_frame_sync
    cam = (10.5, 41.0, 37.0)
    target = (10.68, 41.27)  # M31
    d = compute_body_frame_sync(*cam, *target)
    ra, dec = apply_body_frame_sync(d, *cam)
    assert abs(ra - target[0]) < 1e-6 and abs(dec - target[1]) < 1e-6
    assert abs(np.linalg.norm(d) - 1) < 1e-9


def _recenter_engine(state, target_active=True, raw_age=0.5, old=None):
    import time
    from types import SimpleNamespace
    from evf.engine.goto_target import GotoTargetSnapshot
    cfg = SimpleNamespace(sync_d_body=old)
    solver = MagicMock()
    solver.last_raw_solve.return_value = (10.5, 41.0, 37.0, time.monotonic() - raw_age)
    return SimpleNamespace(
        _state_machine=SimpleNamespace(state=state),
        _goto_target=SimpleNamespace(read=lambda: GotoTargetSnapshot(10.68, 41.27, target_active, "M31")),
        _solver_thread=solver,
        _config=cfg,
    )


def test_engine_recenter_rules():
    import numpy as np
    from evf.engine.engine import Engine, RecenterError
    from evf.engine.state import EngineState
    from evf.solver.sync import compute_body_frame_sync

    for kwargs, msg in [
        (dict(state=EngineState.SYNC), "while tracking"),
        (dict(state=EngineState.TRACKING, target_active=False), "Set a target"),
        (dict(state=EngineState.TRACKING, raw_age=10), "Waiting for a solve"),
    ]:
        with pytest.raises(RecenterError, match=msg):
            Engine.recenter_on_target(_recenter_engine(**kwargs))

    # A small bump: accepted and saved
    near = compute_body_frame_sync(10.5, 41.0, 37.0, 10.9, 41.27).tolist()
    e = _recenter_engine(EngineState.TRACKING, old=near)
    shift = Engine.recenter_on_target(e)
    assert 0.1 < shift < 0.3
    assert np.allclose(e._config.sync_d_body, compute_body_frame_sync(10.5, 41.0, 37.0, 10.68, 41.27))
    e._solver_thread.set_sync_d_body.assert_called_once()

    # A big jump isn't a bump: refused, nothing saved
    far = compute_body_frame_sync(10.5, 41.0, 37.0, 20.0, 45.0).tolist()
    e = _recenter_engine(EngineState.TRACKING, old=far)
    with pytest.raises(RecenterError, match="more than a bump"):
        Engine.recenter_on_target(e)
    assert e._config.sync_d_body == far
