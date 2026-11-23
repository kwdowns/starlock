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

"""Mobile web interface — aiohttp HTTP + WebSocket server.

Serves the React build under web_dist_dir() and pushes JSON state at ~10 Hz
over WebSocket. Runs in a dedicated daemon thread with its own asyncio event
loop.
"""

import asyncio
import hashlib
import io
import json
import logging
import math
import mimetypes
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Iterable, Protocol

from aiohttp import WSCloseCode, web
from PIL import Image

from evf.cloud.service import CloudService, PairingError

# Catalog files served at /api/catalog/<name> (see catalog_data_dir()).
CATALOG_NAMES = ("objects", "openngc", "hyg-bright", "object_sizes")
from evf.config.manager import ConfigManager, normalize_host
from evf.discovery import API_MIN_VERSION, API_VERSION
from evf.engine.frame_buffer import LatestFrame
from evf.engine.goto_target import GotoTarget
from evf.engine.mount import MOUNT_MODES, compute_mount_guidance, mount_axes
from evf.engine.navigation import (
    compute_navigation,
    OnTargetLatch,
    edge_arrow_position,
    off_target_radius_deg,
    on_target_radius_deg,
)
from evf.engine.observation_log import ObservationLogger, entries_to_csv
from evf.wifi_signal import WifiSignal
from evf.engine.pointing import PointingState
from evf.engine.state import StateMachine
from evf.network import local_ip
from evf.paths import catalog_data_dir, sounds_dir, version_json, web_dist_dir

logger = logging.getLogger(__name__)


_MAX_WS_CLIENTS = 10  # cap concurrent WebSocket connections
_MAX_MJPEG_CLIENTS = 4
_MJPEG_BOUNDARY = b"frame"
_MJPEG_INTERVAL = 0.1  # 10 Hz

# Camera image geometry. The horizontal FOV is set by the lens and the
# sensor width; the frame size is read from the frames themselves (see
# WebServer._frame_dims): 1280x800 for the OV9281's full frame, 1280x720 for
# modules that only offer its centre crop, or a dev-mode sample image's size.
# The React UI takes image_w / image_h from the payload.
_FOV_H = 8.86   # horizontal FOV in degrees
_DEFAULT_IMG_W = 1280   # used until the first frame arrives
_DEFAULT_IMG_H = 800


class EngineActions(Protocol):
    """Action surface the WebServer calls into. Implemented by Engine."""

    def step_advance(self) -> None: ...
    def sync_retry(self) -> None: ...
    def set_sync_selected(self, idx: int) -> None: ...
    def use_previous_calibration(self) -> None: ...
    def recenter_on_target(self) -> float: ...
    def retry_camera(self) -> bool: ...
    def set_control(self, name: str, value: int) -> None: ...
    def clear_goto_target(self) -> None: ...
    def set_goto_target(
        self, ra_deg: float, dec_deg: float, name: str | None = None,
    ) -> None: ...
    def set_observation_log_enabled(self, enabled: bool) -> None: ...
    def set_audio_enabled(self, enabled: bool) -> None: ...
    def set_cpu_cap(self, enabled: bool) -> None: ...
    def set_mount_mode(self, mode: str) -> None: ...
    def inject_sample(self, name: str | None) -> None: ...
    def inject_target(self, ra_deg: float, dec_deg: float) -> None: ...
    def capture_frame(self): ...  # returns Path | None
    def set_min_matches(self, value: int) -> None: ...
    def set_max_prob(self, value: float) -> None: ...
    def set_location(
        self, latitude: float | None, longitude: float | None,
    ) -> None: ...


def _compute_origin(
    config: ConfigManager, img_w: int, img_h: int,
) -> tuple[float, float]:
    """Pixel position of the sync offset (pointing center) in image coords.

    Falls back to image center when no sync calibration is available.
    """
    cx, cy = img_w / 2.0, img_h / 2.0
    d_body = config.sync_d_body
    if d_body is not None and d_body[2] > 0.1:
        scale = img_w / (2.0 * math.tan(math.radians(_FOV_H / 2.0)))
        cx += (-d_body[0] / d_body[2]) * scale
        cy += (-d_body[1] / d_body[2]) * scale
    return cx, cy


# Python's mimetypes only knows .webmanifest on some platforms (not on a
# stock Windows registry or minimal Linux), and browsers want this type.
mimetypes.add_type("application/manifest+json", ".webmanifest")


@web.middleware
async def _security_headers_middleware(request: web.Request, handler) -> web.StreamResponse:
    """Add basic security headers to every HTTP response."""
    response = await handler(request)
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault(
        "Content-Security-Policy",
        # 'self' is required for the React build's external <script> and
        # <link rel="stylesheet"> tags pointing at /static/*; without it
        # the browser silently drops them and renders a blank page.
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        # blob: for the live view, which shows each fetched /frame.jpg
        # through an object URL (see web/src/hooks/useLatestFrame.ts).
        "img-src 'self' data: blob:",
    )
    return response


# Content types a browser may send cross-site without a CORS preflight.
_SIMPLE_CONTENT_TYPES = frozenset({
    "application/x-www-form-urlencoded",
    "multipart/form-data",
    "text/plain",
})
_LOCAL_SUFFIXES = (".local", ".lan", ".home", ".home.arpa", ".internal", ".localdomain")


def _host_name(host: str) -> str:
    """Host header value without port, lower case, no trailing dot."""
    host = host.strip().lower()
    if host.startswith("["):  # [v6]:port
        host = host[1:host.find("]")] if "]" in host else host[1:]
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host.rstrip(".")


def _in_allowed(name: str, allowed: Iterable[str]) -> bool:
    for pattern in allowed:
        if pattern.startswith("*."):
            if name.endswith(pattern[1:]):
                return True
        elif name == pattern:
            return True
    return False


def _host_is_local(host: str, allowed: Iterable[str] = ()) -> bool:
    """Whether a Host header value names this unit.

    Accepts IP literals, ``localhost``, single-label names, the usual LAN
    suffixes (``starlock-3f2a.local``) and the owner's own names from
    ``webserver.allowed_hosts``. Anything else is a public DNS name, which
    is how a DNS-rebinding page would reach the unit.
    """
    import ipaddress
    name = _host_name(host)
    if not name:
        return False
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    return (name == "localhost" or "." not in name or name.endswith(_LOCAL_SUFFIXES)
            or _in_allowed(name, allowed))


def _origin_ok(origin: str, host: str, allowed: Iterable[str] = ()) -> bool:
    """Same origin as the request, or one of the owner's allowed names
    (a reverse proxy may rewrite Host to the Pi's IP)."""
    import urllib.parse
    try:
        parts = urllib.parse.urlsplit(origin)
    except ValueError:
        return False
    netloc = parts.netloc.lower()
    if not netloc:
        return False
    return netloc == host.strip().lower() or _in_allowed(_host_name(netloc), allowed)


def request_guard_problem(method: str, host: str, origin: str | None,
                          content_type: str, allowed: Iterable[str] = (),
                          path: str = "") -> str | None:
    """Why a request must be refused, or None.

    Stops other web pages from driving the unit through the owner's
    browser: DNS rebinding (Host check), cross-site writes and WebSocket
    reads (Origin check; native apps and tools send no Origin), and
    form/text posts that skip the CORS preflight. See
    specs/start/SPEC_FIRST_RUN.md §7.2.
    """
    if not _host_is_local(host, allowed):
        return "unknown host"
    if origin is not None and not _origin_ok(origin, host, allowed):
        if method not in ("GET", "HEAD", "OPTIONS"):
            return "cross-site request"
        if path == "/ws":
            return "cross-site WebSocket"
    if method in ("POST", "PUT", "PATCH") and content_type in _SIMPLE_CONTENT_TYPES:
        return "use Content-Type: application/json"
    return None


def _request_guard_middleware(allowed_hosts: Callable[[], list[str]]):
    @web.middleware
    async def guard(request: web.Request, handler) -> web.StreamResponse:
        origin = request.headers.get("Origin")
        problem = request_guard_problem(
            request.method, request.host or "", origin,
            request.content_type if request.body_exists else "",
            allowed_hosts(), request.path,
        )
        if problem is not None:
            logger.warning("Refused %s %s (Host %r, Origin %r): %s",
                           request.method, request.path, request.host, origin, problem)
            return web.Response(status=403, text=problem)
        return await handler(request)
    return guard


def _is_local_origin(origin: str) -> bool:
    """Return True if the WebSocket Origin header looks like a local address."""
    import urllib.parse
    try:
        host = urllib.parse.urlparse(origin).hostname or ""
        return (
            host == "localhost"
            or host.startswith("127.")
            or host.startswith("192.168.")
            or host.startswith("10.")
            or host.startswith("172.")
        )
    except Exception:
        return False


class WebServer:
    """HTTP + WebSocket server for the mobile web interface.

    Always-on subsystem: started with the engine, stopped on shutdown.
    HTTP GET /          — serves the React build (web_dist_dir / index.html)
    HTTP GET /static/*  — React build assets (when web_dist_dir() exists)
    HTTP GET /sounds/*  — serves WAV audio files
    HTTP GET /frame.jpg  — the latest camera frame as one JPEG (used by the UI)
    HTTP GET /frame.mjpg — multipart MJPEG of the latest camera frame
    WebSocket /ws       — pushes JSON state at ~10 Hz to all clients
    HTTP POST /api/*    — wizard, controls, settings, dev actions
    """

    def __init__(
        self,
        pointing: PointingState,
        state_machine: StateMachine,
        goto_target: GotoTarget,
        config: ConfigManager,
        *,
        frame_buffer: LatestFrame | None = None,
        solver_failures: Callable[[], int] | None = None,
        stellarium_object: Callable[[], dict | None] | None = None,
        camera_controls: Callable[[], list[dict] | None] | None = None,
        sync_state: Callable[[], dict] | None = None,
        activity: Callable[[], dict] | None = None,
        stellarium_location: Callable[[], dict | None] | None = None,
        location: Callable[[], dict] | None = None,
        dev_mode: bool = False,
        sample_active: Callable[[], str | None] | None = None,
        actions: "EngineActions | None" = None,
        on_client_connected: Callable[[], None] | None = None,
        observations: ObservationLogger | None = None,
        cloud: Callable[[], "CloudService | None"] | None = None,
    ) -> None:
        self._observations = observations
        self._cloud_fn = cloud
        self._catalog_cache: dict[str, tuple[bytes, str]] = {}
        self._pointing = pointing
        self._state_machine = state_machine
        self._goto_target = goto_target
        self._config = config
        self._frame_buffer = frame_buffer
        self._img_dims: tuple[int, int] = (_DEFAULT_IMG_W, _DEFAULT_IMG_H)
        self._img_dims_frame_id: int | None = None
        self._solver_failures = solver_failures
        self._stellarium_object = stellarium_object
        self._camera_controls = camera_controls
        self._sync_state = sync_state
        self._activity = activity
        self._stellarium_location = stellarium_location
        self._location_fn = location
        self._minor_planet_cache = None
        self._wifi = WifiSignal()
        self._on_target = OnTargetLatch()
        self._dev_mode = dev_mode
        self._sample_active = sample_active
        self._actions = actions
        self._on_client_connected = on_client_connected

        self._clients: set[web.WebSocketResponse] = set()
        # Set while WebSocket clients are connected; with none, the
        # broadcast loop sleeps on it instead of waking at 10 Hz.
        # Created in _serve so it belongs to the server's own event loop.
        self._have_clients: asyncio.Event | None = None
        self._mjpeg_clients: int = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._serve_task: asyncio.Task | None = None
        self._thread: threading.Thread | None = None
        self._port: int | None = None  # actual bound port (for tests on ephemeral port)

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="webserver", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        # Cancel the serve task (not loop.stop()) so _serve's finally block
        # can close websockets and release the port before the loop exits.
        if self._loop is not None and self._serve_task is not None:
            try:
                self._loop.call_soon_threadsafe(self._serve_task.cancel)
            except RuntimeError:
                pass  # loop already closed
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        logger.info("Web server stopped")

    @property
    def url(self) -> str | None:
        """LAN URL of the mobile interface, or None without a LAN address.

        Looked up on every call rather than once at start, so it follows the
        network: a Pi's hotspot or Wi-Fi may come up after Starlock does.
        """
        ip = local_ip()
        return f"http://{ip}:{self._config.web_port}" if ip else None

    # -- internal -------------------------------------------------------------

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._serve_task = self._loop.create_task(self._serve())
        try:
            self._loop.run_until_complete(self._serve_task)
        except asyncio.CancelledError:
            pass  # normal stop()
        except Exception as exc:
            logger.error("Web server error: %s", exc)
        finally:
            # Request handlers still streaming (MJPEG) can outlive
            # runner.cleanup(); cancel and drain them before closing.
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()

    async def _serve(self) -> None:
        port = self._config.web_port
        url = self.url
        if url is None:
            logger.warning(
                "Mobile web interface listening on port %d but no LAN IP "
                "detected — mobile devices cannot reach the server",
                port,
            )
        else:
            logger.info("Mobile web interface at %s", url)

        self._have_clients = asyncio.Event()
        app = web.Application(middlewares=[
            _security_headers_middleware,
            _request_guard_middleware(lambda: self._config.web_allowed_hosts),
        ])
        app.router.add_get("/", self._handle_index)
        app.router.add_get("/api/version", self._handle_version)
        app.router.add_get("/ws", self._handle_ws)
        app.router.add_get("/frame.mjpg", self._handle_mjpeg)
        app.router.add_get("/frame.jpg", self._handle_frame_jpg)
        app.router.add_post("/api/wizard/advance", self._api_wizard_advance)
        app.router.add_post("/api/sync/retry", self._api_sync_retry)
        app.router.add_post("/api/sync/select", self._api_sync_select)
        app.router.add_post("/api/sync/recenter", self._api_sync_recenter)
        app.router.add_post("/api/calibration/use-previous", self._api_use_previous_calibration)
        app.router.add_post("/api/camera/retry", self._api_camera_retry)
        app.router.add_post("/api/control", self._api_set_control)
        app.router.add_post("/api/goto/clear", self._api_goto_clear)
        app.router.add_post("/api/goto/set", self._api_goto_set)
        app.router.add_post("/api/clock", self._api_clock)
        app.router.add_get("/api/observations", self._api_observations)
        app.router.add_get("/api/observations.csv", self._api_observations_csv)
        app.router.add_delete("/api/observations", self._api_observations_delete)
        app.router.add_get("/api/observations/{id}/frame.jpg", self._api_observation_frame)
        app.router.add_get("/api/solar-system", self._api_solar_system)
        app.router.add_get("/api/catalog/{name}", self._api_catalog)
        app.router.add_get("/api/cloud", self._api_cloud_status)
        app.router.add_post("/api/cloud/pair", self._api_cloud_pair)
        app.router.add_delete("/api/cloud", self._api_cloud_unlink)
        app.router.add_post("/api/settings", self._api_settings)
        app.router.add_post("/api/dev/inject-sample", self._api_dev_inject_sample)
        app.router.add_post("/api/dev/inject-target", self._api_dev_inject_target)
        app.router.add_post("/api/dev/capture-frame", self._api_dev_capture_frame)
        app.router.add_static("/sounds", sounds_dir(), name="sounds")
        dist = web_dist_dir()
        if dist.exists():
            app.router.add_static("/static", dist, name="react_static")

        # Short shutdown_timeout: /frame.mjpg streams never finish on their
        # own, and aiohttp would otherwise wait 60 s for them in cleanup().
        runner = web.AppRunner(app, shutdown_timeout=0.5)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        # Capture the actually-bound port only when caller asked for ephemeral.
        # Reaches into aiohttp internals, so we restrict to the test path.
        if port == 0:
            try:
                self._port = site._server.sockets[0].getsockname()[1]
            except Exception:
                self._port = port
        else:
            self._port = port
        logger.info("Web server listening on port %d", self._port)

        try:
            await self._broadcast_loop()
        finally:
            for ws in list(self._clients):
                await ws.close(code=WSCloseCode.GOING_AWAY, message=b"server shutdown")
            self._clients.clear()
            await runner.cleanup()

    async def _handle_index(self, request: web.Request) -> web.StreamResponse:
        """Serve the React app shell from web_dist_dir().

        Returns 503 when the React build is missing (dev mode without
        ``npm run build``); the dev workflow uses Vite on port 5173 instead.
        """
        dist = web_dist_dir()
        index = dist / "index.html"
        if index.exists():
            # Force revalidation on every load so a stale index.html in
            # WKWebView's persistent NetworkCache can't pin the page to an
            # obsolete content-hashed JS bundle. The bundle URLs themselves
            # are content-addressed so they're safe to cache.
            return web.FileResponse(
                index, headers={"Cache-Control": "no-cache, must-revalidate"},
            )
        return web.Response(
            status=503,
            text=(
                "React build not found at "
                f"{dist}. Run 'npm run build' in web/ or use "
                "'npm run dev' (Vite on :5173) for dev."
            ),
        )

    async def _handle_version(self, request: web.Request) -> web.Response:
        """Identify-as-Starlock endpoint.

        Used by the single-instance check in main.py: a second launch
        probes this URL and exits cleanly if the response carries our
        ``app == "starlock"`` marker. Independently useful for clients
        and scripts that want app/protocol version info.
        """
        try:
            with open(version_json()) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            data = {}
        return web.json_response({
            "app": "starlock",
            "version": data.get("app_version"),
            "protocol_version": data.get("protocol_version"),
            # API contract range, as in the mDNS TXT record (api, api_min),
            # for apps that were given an address instead of discovering it.
            "api": int(API_VERSION),
            "api_min": int(API_MIN_VERSION),
            # Same id as the mDNS TXT record, so an app can match an
            # address it was given to a Starlock it discovered before.
            "device_id": self._config.device_id,
        })

    # -- Camera frames ------------------------------------------------------

    async def _handle_frame_jpg(self, request: web.Request) -> web.Response:
        """The latest camera frame as one JPEG.

        The React UI fetches this whenever the WebSocket payload's
        `camera.frame_id` changes. Unlike a long-lived MJPEG stream, a plain
        request per frame survives a phone locking and unlocking: the next
        payload simply triggers the next fetch. The `?id=` query the UI adds
        is only there to keep caches out of the way.
        """
        if self._frame_buffer is None:
            return web.Response(status=503, text="No frame buffer")
        jpeg, _ts, fid = self._frame_buffer.get()
        if jpeg is None:
            return web.Response(status=404, text="No frame yet")
        return web.Response(
            body=jpeg,
            content_type="image/jpeg",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "X-Frame-Id": str(fid),
            },
        )


    async def _handle_mjpeg(self, request: web.Request) -> web.StreamResponse:
        """Multipart MJPEG stream of the latest camera frame.

        Browsers and OS webviews render multipart/x-mixed-replace natively in
        an <img> tag, so the React UI does not need any JS-side JPEG decoding.
        """
        if self._frame_buffer is None:
            return web.Response(status=503, text="No frame buffer")
        if self._mjpeg_clients >= _MAX_MJPEG_CLIENTS:
            logger.warning("MJPEG client limit reached (%d), rejecting", _MAX_MJPEG_CLIENTS)
            raise web.HTTPServiceUnavailable(reason="Too many MJPEG clients")
        self._mjpeg_clients += 1
        try:
            resp = web.StreamResponse(
                status=200,
                headers={
                    "Content-Type": (
                        "multipart/x-mixed-replace; "
                        f"boundary={_MJPEG_BOUNDARY.decode()}"
                    ),
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                },
            )
            await resp.prepare(request)
            last_frame_id = -1
            try:
                while True:
                    jpeg, _ts, fid = self._frame_buffer.get()
                    if jpeg is not None and fid != last_frame_id:
                        last_frame_id = fid
                        part = (
                            b"--" + _MJPEG_BOUNDARY + b"\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                            + jpeg + b"\r\n"
                        )
                        await resp.write(part)
                    await asyncio.sleep(_MJPEG_INTERVAL)
            except (asyncio.CancelledError, ConnectionResetError):
                pass
        finally:
            self._mjpeg_clients -= 1
        return resp

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        # Reject if connection cap reached
        if len(self._clients) >= _MAX_WS_CLIENTS:
            logger.warning("WebSocket connection limit reached (%d), rejecting", _MAX_WS_CLIENTS)
            raise web.HTTPServiceUnavailable(reason="Too many clients")

        # Warn on non-local origin (informational — LAN clients have no Origin header)
        origin = request.headers.get("Origin", "")
        if origin and not _is_local_origin(origin):
            logger.warning("WebSocket connection from non-local origin: %s", origin)

        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)
        self._have_clients.set()
        logger.info("Web client connected")
        if self._on_client_connected is not None:
            try:
                self._on_client_connected()
            except Exception as exc:
                logger.debug("on_client_connected failed: %s", exc)
        try:
            async for _msg in ws:
                pass  # read-only; ignore any incoming messages
        finally:
            self._clients.discard(ws)
            logger.info("Web client disconnected")
        return ws

    async def _broadcast_loop(self) -> None:
        while True:
            if not self._clients:
                self._have_clients.clear()
                await self._have_clients.wait()
            await asyncio.sleep(0.1)  # 10 Hz
            if not self._clients:
                continue
            try:
                payload = json.dumps(self._build_payload())
            except Exception as exc:
                logger.debug("Payload build error: %s", exc)
                continue
            dead: set[web.WebSocketResponse] = set()
            for ws in list(self._clients):
                try:
                    await ws.send_str(payload)
                except Exception:
                    dead.add(ws)
            self._clients -= dead

    # -- API actions ----------------------------------------------------------

    async def _handle_api(self, request: web.Request, fn) -> web.Response:
        """Run a synchronous engine action and return 204."""
        if self._actions is None:
            return web.Response(status=503, text="No actions wired")
        try:
            await asyncio.to_thread(fn)
        except Exception as exc:
            logger.exception("API action failed: %s", exc)
            return web.Response(status=500, text=str(exc))
        return web.Response(status=204)

    async def _api_wizard_advance(self, request):
        return await self._handle_api(request, lambda: self._actions.step_advance())

    async def _api_sync_retry(self, request):
        return await self._handle_api(request, lambda: self._actions.sync_retry())

    async def _api_sync_recenter(self, request):
        """The target is centred in the eyepiece: re-aim the sync on it.
        200 {shift_deg}, or 409 with a message for the user."""
        if self._actions is None:
            return web.Response(status=503, text="No actions wired")
        try:
            shift = await asyncio.to_thread(self._actions.recenter_on_target)
        except Exception as exc:
            if type(exc).__name__ == "RecenterError":
                return web.Response(status=409, text=str(exc))
            logger.exception("Recenter failed: %s", exc)
            return web.Response(status=500, text=str(exc))
        return web.json_response({"shift_deg": round(float(shift or 0.0), 3)})

    async def _api_sync_select(self, request):
        body = await request.json()
        idx = int(body["idx"])
        return await self._handle_api(request, lambda: self._actions.set_sync_selected(idx))

    async def _api_use_previous_calibration(self, request):
        return await self._handle_api(request, lambda: self._actions.use_previous_calibration())

    async def _api_camera_retry(self, request: web.Request) -> web.Response:
        """Re-attempt camera startup. Returns 200 + {connected: bool}."""
        if self._actions is None:
            return web.Response(status=503, text="No actions wired")
        try:
            connected = await asyncio.to_thread(self._actions.retry_camera)
        except Exception as exc:
            logger.exception("retry_camera failed: %s", exc)
            return web.Response(status=500, text=str(exc))
        return web.json_response({"connected": bool(connected)})

    async def _api_set_control(self, request):
        body = await request.json()
        name = str(body["name"])
        value = int(body["value"])
        return await self._handle_api(request, lambda: self._actions.set_control(name, value))

    async def _api_goto_clear(self, request):
        return await self._handle_api(request, lambda: self._actions.clear_goto_target())

    async def _api_goto_set(self, request: web.Request) -> web.Response:
        body = await request.json()
        ra = float(body["ra_deg"])
        dec = float(body["dec_deg"])
        name = body.get("name")
        name = name.strip()[:120] if isinstance(name, str) and name.strip() else None
        # Optional apparent size (major axis, degrees): big objects count as
        # on target over more of their extent.
        size = body.get("size_deg")
        try:
            size = float(size) if size is not None else None
        except (TypeError, ValueError):
            return web.Response(status=400, text="size_deg must be a number")
        if size is not None and not (0 < size <= 90):
            size = None
        if size is None:
            if name is None:
                return await self._handle_api(
                    request, lambda: self._actions.set_goto_target(ra, dec))
            return await self._handle_api(
                request, lambda: self._actions.set_goto_target(ra, dec, name))
        return await self._handle_api(
            request, lambda: self._actions.set_goto_target(ra, dec, name, size))

    # -- observation log ------------------------------------------------------

    def _obs_unavailable(self) -> web.Response | None:
        if self._observations is None:
            return web.Response(status=503, text="Observation log unavailable")
        return None

    def _obs_range(self, request: web.Request) -> tuple[float, float]:
        """(start, end) unix seconds from ?start=&end= ISO-8601; default last 24 h."""
        def parse(text: str) -> float:
            dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        try:
            q = request.query
            end = parse(q["end"]) if q.get("end") else self._observations.clock.now()
            start = parse(q["start"]) if q.get("start") else end - 86400.0
        except ValueError as exc:
            raise web.HTTPBadRequest(text=f"start/end must be ISO-8601: {exc}")
        if start > end:
            raise web.HTTPBadRequest(text="start must not be after end")
        return start, end

    async def _api_clock(self, request: web.Request) -> web.Response:
        """A web client reports its clock; used when the host clock is wrong."""
        if (resp := self._obs_unavailable()) is not None:
            return resp
        try:
            body = await request.json()
            client_s = float(body["unix_ms"]) / 1000.0
        except (ValueError, KeyError, TypeError):
            return web.Response(status=400, text="unix_ms required")
        used = self._observations.clock.report_client_time(client_s)
        return web.json_response({"client_clock_used": used})

    async def _api_observations(self, request: web.Request) -> web.Response:
        if (resp := self._obs_unavailable()) is not None:
            return resp
        start, end = self._obs_range(request)
        try:
            limit = int(request.query["limit"]) if "limit" in request.query else 500
        except ValueError:
            return web.Response(status=400, text="limit must be an integer")
        store = self._observations.store
        entries = await asyncio.to_thread(store.list, start, end, max(1, limit))
        return web.json_response({
            "enabled": self._config.observation_log_enabled,
            "clock": self._observations.clock.source,
            "now_utc": datetime.fromtimestamp(
                self._observations.clock.now(), timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "entries": entries,
        })

    async def _api_observations_csv(self, request: web.Request) -> web.Response:
        if (resp := self._obs_unavailable()) is not None:
            return resp
        start, end = self._obs_range(request)
        entries = await asyncio.to_thread(self._observations.store.list, start, end)
        def stamp(t: float) -> str:
            return datetime.fromtimestamp(t, timezone.utc).strftime("%Y%m%d-%H%M")
        return web.Response(
            body=entries_to_csv(entries).encode("utf-8"),
            content_type="text/csv",
            charset="utf-8",
            headers={"Content-Disposition":
                     f'attachment; filename="starlock-observations-{stamp(start)}-{stamp(end)}.csv"'},
        )

    async def _api_observations_delete(self, request: web.Request) -> web.Response:
        """Delete closed entries in a range. start and end are both required."""
        if (resp := self._obs_unavailable()) is not None:
            return resp
        if "start" not in request.query or "end" not in request.query:
            return web.Response(status=400, text="start and end are required")
        start, end = self._obs_range(request)
        n = await asyncio.to_thread(self._observations.store.delete, start, end)
        return web.json_response({"deleted": n})

    async def _api_observation_frame(self, request: web.Request) -> web.Response:
        """The camera frame kept with a log entry (404 if none or trimmed)."""
        if (resp := self._obs_unavailable()) is not None:
            return resp
        try:
            entry_id = int(request.match_info["id"])
        except ValueError:
            return web.Response(status=400, text="id must be an integer")
        jpeg = await asyncio.to_thread(self._observations.store.frame, entry_id)
        if jpeg is None:
            return web.Response(status=404, text="No frame for this entry")
        return web.Response(body=jpeg, content_type="image/jpeg",
                            headers={"Cache-Control": "private, max-age=86400"})

    async def _api_solar_system(self, request: web.Request) -> web.Response:
        """Moon, planets and bright asteroids at ``at`` (ISO time, default
        now), J2000 RA/Dec, topocentric when the observer location is known.
        They move, so unlike /api/catalog this is computed per request."""
        from evf.engine.solar_system import positions
        if "at" in request.query:
            try:
                when = datetime.fromisoformat(request.query["at"].replace("Z", "+00:00"))
            except ValueError:
                return web.Response(status=400, text="at must be an ISO 8601 time")
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
        else:
            now = self._observations.clock.now() if self._observations is not None else time.time()
            when = datetime.fromtimestamp(now, timezone.utc)
        loc = (self._location_fn() if self._location_fn else None) or {}
        bodies = await asyncio.to_thread(
            positions, when, loc.get("latitude"), loc.get("longitude"), self._minor_planets())
        return web.json_response({
            "at_utc": when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "topocentric": loc.get("latitude") is not None and loc.get("longitude") is not None,
            "bodies": bodies,
        }, headers={"Cache-Control": "no-store"})

    def _minor_planets(self):
        if self._minor_planet_cache is None:
            from evf.engine.solar_system import load_minor_planets
            from evf.paths import minor_planets_json
            self._minor_planet_cache = load_minor_planets(minor_planets_json())
        return self._minor_planet_cache

    # -- Catalog data ------------------------------------------------------------

    async def _api_catalog(self, request: web.Request) -> web.Response:
        """The web UI's catalog JSON, for native apps (fetched at runtime).

        objects (curated), openngc (OpenNGC, CC-BY-SA 4.0) and hyg-bright
        (HYG v3, CC-BY-SA 4.0). Gzipped when the client accepts it, with an
        ETag so an app can keep a cached copy.
        """
        name = request.match_info["name"].removesuffix(".json")
        if name not in CATALOG_NAMES:
            raise web.HTTPNotFound(text="unknown catalog")
        cached = self._catalog_cache.get(name)
        if cached is None:
            path = catalog_data_dir() / f"{name}.json"
            try:
                body = await asyncio.to_thread(path.read_bytes)
            except OSError:
                raise web.HTTPNotFound(text="catalog not installed")
            cached = (body, '"' + hashlib.sha1(body).hexdigest() + '"')
            self._catalog_cache[name] = cached
        body, etag = cached
        headers = {"ETag": etag, "Cache-Control": "no-cache"}
        if request.headers.get("If-None-Match") == etag:
            return web.Response(status=304, headers=headers)
        resp = web.Response(body=body, content_type="application/json", headers=headers)
        resp.enable_compression()
        return resp

    # -- Starlock Cloud link ---------------------------------------------------

    def _cloud(self) -> "CloudService | None":
        return self._cloud_fn() if self._cloud_fn else None

    async def _api_cloud_status(self, request: web.Request) -> web.Response:
        """Link status for the Settings sheet. Never includes the credential."""
        cloud = self._cloud()
        if cloud is None:
            return web.json_response({"available": False, "linked": False})
        return web.json_response({"available": True, **cloud.status()})

    async def _api_cloud_pair(self, request: web.Request) -> web.Response:
        """Link to Starlock Cloud with a pairing code from the phone app.

        Body: {"code": "K7P4-QX9M", "base_url"?: "https://…", "name"?: "Backyard Pi"}.
        Sent by the Settings sheet or by the phone app over the LAN.
        """
        cloud = self._cloud()
        if cloud is None:
            return web.Response(status=503, text="Starlock Cloud unavailable")
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            return web.Response(status=400, text="JSON body required")
        if not isinstance(body, dict) or not isinstance(body.get("code"), str):
            return web.Response(status=400, text="code required")
        base_url = body.get("base_url") if isinstance(body.get("base_url"), str) else None
        name = body.get("name") if isinstance(body.get("name"), str) else None
        try:
            status = await asyncio.to_thread(cloud.pair, body["code"], base_url, name)
        except PairingError as exc:
            return web.Response(status=exc.status, text=str(exc))
        return web.json_response({"available": True, **status})

    async def _api_cloud_unlink(self, request: web.Request) -> web.Response:
        cloud = self._cloud()
        if cloud is None:
            return web.Response(status=503, text="Starlock Cloud unavailable")
        await asyncio.to_thread(cloud.unlink)
        return web.Response(status=204)

    async def _api_settings(self, request):
        body = await request.json()
        if "audio_enabled" in body:
            resp = await self._handle_api(
                request,
                lambda: self._actions.set_audio_enabled(bool(body["audio_enabled"])),
            )
            if resp.status >= 400:
                return resp
        if "mount_mode" in body:
            mode = body["mount_mode"]
            if mode not in MOUNT_MODES:
                return web.Response(status=400, text=f"mount_mode must be one of {MOUNT_MODES}")
            resp = await self._handle_api(
                request, lambda: self._actions.set_mount_mode(mode),
            )
            if resp.status >= 400:
                return resp
        if "cpu_cap" in body:
            resp = await self._handle_api(
                request,
                lambda: self._actions.set_cpu_cap(bool(body["cpu_cap"])),
            )
            if resp.status >= 400:
                return resp
        if "min_matches" in body:
            resp = await self._handle_api(
                request,
                lambda: self._actions.set_min_matches(int(body["min_matches"])),
            )
            if resp.status >= 400:
                return resp
        if "max_prob" in body:
            resp = await self._handle_api(
                request,
                lambda: self._actions.set_max_prob(float(body["max_prob"])),
            )
            if resp.status >= 400:
                return resp
        if "location" in body:
            loc = body["location"]
            if loc is None:
                resp = await self._handle_api(
                    request, lambda: self._actions.set_location(None, None),
                )
            else:
                lat = float(loc["latitude"])
                lon = float(loc["longitude"])
                resp = await self._handle_api(
                    request, lambda: self._actions.set_location(lat, lon),
                )
            if resp.status >= 400:
                return resp
        if "observation_log_enabled" in body:
            resp = await self._handle_api(
                request,
                lambda: self._actions.set_observation_log_enabled(
                    bool(body["observation_log_enabled"])),
            )
            if resp.status >= 400:
                return resp
        if "stellarium_rc_host" in body:
            try:
                host = normalize_host(body["stellarium_rc_host"])
            except ValueError as exc:
                return web.Response(status=400, text=f"stellarium_rc_host: {exc}")
            resp = await self._handle_api(
                request, lambda: self._actions.set_stellarium_rc_host(host),
            )
            if resp.status >= 400:
                return resp
        if "lx200_epoch" in body:
            resp = await self._handle_api(
                request,
                lambda: self._actions.set_lx200_epoch(str(body["lx200_epoch"])),
            )
            if resp.status >= 400:
                return resp
        return web.Response(status=204)

    async def _api_dev_inject_sample(self, request):
        body = await request.json()
        name = body.get("name")  # str or None
        return await self._handle_api(
            request, lambda: self._actions.inject_sample(name),
        )

    async def _api_dev_inject_target(self, request):
        body = await request.json()
        ra = float(body["ra_deg"])
        dec = float(body["dec_deg"])
        return await self._handle_api(
            request, lambda: self._actions.inject_target(ra, dec),
        )

    async def _api_dev_capture_frame(self, request):
        """Save the latest frame to ~/Downloads. Returns 200 + JSON {path}."""
        if not self._dev_mode:
            return web.Response(status=404, text="Debug mode only")
        if self._actions is None:
            return web.Response(status=503, text="No actions wired")
        try:
            path = await asyncio.to_thread(self._actions.capture_frame)
        except Exception as exc:
            logger.exception("capture_frame failed: %s", exc)
            return web.Response(status=500, text=str(exc))
        if path is None:
            return web.json_response({"path": None, "error": "no frame"}, status=409)
        return web.json_response({"path": str(path)})

    # -- payload --------------------------------------------------------------

    def _frame_dims(self) -> tuple[int, int]:
        """(width, height) of the latest frame, or the last size seen.

        Reads only the JPEG header, and only once per new frame id.
        """
        if self._frame_buffer is not None:
            jpeg, _ts, frame_id = self._frame_buffer.get()
            if jpeg and frame_id != self._img_dims_frame_id:
                self._img_dims_frame_id = frame_id
                try:
                    with Image.open(io.BytesIO(jpeg)) as img:
                        self._img_dims = img.size
                except Exception as exc:  # noqa: BLE001 — keep the last good size
                    logger.debug("Could not read frame size: %s", exc)
        return self._img_dims

    def build_payload(self) -> dict | None:
        """The /ws state dict, for other subsystems (Starlock Cloud). None on error."""
        try:
            return self._build_payload()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Payload build error: %s", exc)
            return None

    def _build_payload(self) -> dict:
        state = self._state_machine.state
        snap = self._pointing.read()
        target = self._goto_target.read()
        failures = self._solver_failures() if self._solver_failures else 0
        img_w, img_h = self._frame_dims()
        origin_x, origin_y = _compute_origin(self._config, img_w, img_h)
        dx_off = origin_x - img_w / 2.0
        dy_off = origin_y - img_h / 2.0

        pointing_data = {
            "valid": snap.valid,
            "ra_deg": snap.ra_j2000,
            "dec_deg": snap.dec_j2000,
            "roll_deg": snap.roll,
            "matches": snap.matches,
            "prob": snap.prob,
            "solve_age_s": (
                round(time.monotonic() - snap.last_success_timestamp, 1)
                if snap.valid else None
            ),
        }

        location_blk = self._location_fn() if self._location_fn else {
            "latitude": None, "longitude": None, "source": None,
        }
        location = (
            (location_blk["latitude"], location_blk["longitude"])
            if location_blk.get("latitude") is not None
            and location_blk.get("longitude") is not None
            else None
        )
        mount_mode = self._config.mount_mode
        now = time.time()

        axes = None
        if snap.valid:
            axes = mount_axes(
                mount_mode, snap.ra_j2000, snap.dec_j2000, snap.roll, location, now,
            )
        mount_blk = {
            "mode": mount_mode,
            # Alt-az guidance needs the observer's location for the zenith.
            "needs_location": mount_mode == "altaz" and location is None,
            "axes": (
                {"axis1_angle_deg": axes.axis1_angle_deg,
                 "axis2_angle_deg": axes.axis2_angle_deg}
                if axes is not None else None
            ),
        }

        nav_data = self._build_nav(
            snap, target, origin_x, origin_y, dx_off, dy_off, img_w, img_h,
            mount_mode, location, now,
        )

        controls = self._camera_controls() if self._camera_controls else []
        sync_blk = self._sync_state() if self._sync_state else {
            "in_progress": False, "candidates": [], "selected_idx": None, "error": None,
        }
        activity_blk = self._activity() if self._activity else {}
        jpeg, _ts, frame_id = (
            self._frame_buffer.get() if self._frame_buffer else (None, 0.0, 0)
        )
        camera_blk = {
            "connected": jpeg is not None,
            # Changes with every new frame; the UI fetches /frame.jpg on change.
            "frame_id": frame_id if jpeg is not None else None,
            "all_centroids": snap.all_centroids if snap.valid else None,
            "matched_centroids": snap.matched_centroids if snap.valid else None,
        }

        stellarium_blk = dict(
            activity_blk.get("stellarium", {"active": False, "address": None})
        )
        if self._stellarium_location is not None:
            try:
                stellarium_blk["location"] = self._stellarium_location()
            except Exception:
                stellarium_blk["location"] = None
        else:
            stellarium_blk.setdefault("location", None)

        return {
            "state": state.value,
            "failures": failures,
            # The Pi's own Wi-Fi link (None on Ethernet / hotspot / desktop).
            "wifi": self._wifi.snapshot(),
            "pointing": pointing_data,
            "nav": nav_data,
            "origin_x": origin_x,
            "origin_y": origin_y,
            "image_w": img_w,
            "image_h": img_h,
            "finder_rotation": self._config.finder_rotation,
            "fov_h_deg": _FOV_H,
            "has_calibration": self._config.has_calibration,
            "mount": mount_blk,
            "image_size": list(snap.image_size) if snap.valid and snap.image_size else None,
            "controls": controls or [],
            "sync": sync_blk,
            "stellarium": stellarium_blk,
            "lx200":      activity_blk.get("lx200",      {"active": False, "address": None}),
            "webserver":  activity_blk.get("webserver",  {"url": None}),
            "audio_enabled": activity_blk.get("audio_enabled", True),
            "power": activity_blk.get(
                "power", {"available": False, "cpu_cap": False, "max_freq_mhz": None}
            ),
            "camera": camera_blk,
            "location": location_blk,
            "dev_mode": self._dev_mode,
            "min_matches": self._config.min_matches,
            "max_prob": self._config.max_prob,
            "sample_active": (
                self._sample_active() if self._sample_active else None
            ),
        }

    def _build_nav(
        self, snap, target, origin_x, origin_y, dx_off, dy_off, img_w, img_h,
        mount_mode="altaz", location=None, now=None,
    ) -> dict | None:
        if not target.active:
            return None

        # The name sent with the target (web UI, phone app) wins; otherwise the
        # object selected in desktop Stellarium, which sends no name itself.
        obj_name = getattr(target, "name", None)
        if not obj_name and self._stellarium_object:
            obj = self._stellarium_object()
            if obj:
                obj_name = obj.get("localized-name") or obj.get("name")

        size = getattr(target, "size_deg", None)
        base = {
            "active": True,
            "target_name": obj_name,
            "target_ra_deg": target.ra_j2000,
            "target_dec_deg": target.dec_j2000,
            "target_size_deg": size,
            # Clients and Starlock Cloud use this for "on target".
            "on_target_deg": on_target_radius_deg(size),
            "off_target_deg": off_target_radius_deg(on_target_radius_deg(size)),
        }
        latch_key = (target.ra_j2000, target.dec_j2000, size)

        if not snap.valid:
            self._on_target.update(latch_key, None, base["on_target_deg"])
            return {**base, "on_target": False, "separation_deg": None, "direction_text": "--",
                    "in_fov": False, "pixel_x": None, "pixel_y": None,
                    "camera_angle_deg": None, "edge_x": None, "edge_y": None,
                    "edge_angle_deg": None, "mount": None}

        nav = compute_navigation(
            snap.ra_j2000, snap.dec_j2000, snap.roll,
            target.ra_j2000, target.dec_j2000,
            _FOV_H, img_w, img_h,
        )

        # Apply sync offset to in-FOV pixel coords so the React side renders the
        # target marker at its actual position in the camera image. compute_navigation
        # returns coords assuming "image center == pointing center", but the
        # eyepiece's projected center is offset by (dx_off, dy_off) from the
        # camera image center.
        offset_pixel_x = nav.pixel_x + dx_off if nav.pixel_x is not None else None
        offset_pixel_y = nav.pixel_y + dy_off if nav.pixel_y is not None else None

        # in_fov must use the offset position — that's where the marker actually
        # lands on the displayed frame. nav.in_fov is computed pre-offset, so
        # it disagrees with the rendered position whenever sync has a non-zero
        # offset (target visually in-frame but flagged as outside, or vice versa).
        in_fov = (
            offset_pixel_x is not None
            and offset_pixel_y is not None
            and 0 <= offset_pixel_x < img_w
            and 0 <= offset_pixel_y < img_h
        )

        edge_x = edge_y = edge_angle = None
        if not in_fov:
            if offset_pixel_x is not None:
                edge_x, edge_y, edge_angle = edge_arrow_position(
                    offset_pixel_x, offset_pixel_y,
                    img_w, img_h, margin=68,
                    origin_x=origin_x, origin_y=origin_y,
                )
            else:
                # Target behind camera — derive direction from camera_angle_deg
                far = max(img_w, img_h) * 10.0
                rad = math.radians(nav.camera_angle_deg)
                far_x = origin_x + far * math.sin(rad)
                far_y = origin_y - far * math.cos(rad)
                edge_x, edge_y, edge_angle = edge_arrow_position(
                    far_x, far_y, img_w, img_h, margin=68,
                    origin_x=origin_x, origin_y=origin_y,
                )

        guidance = compute_mount_guidance(
            mount_mode, snap.ra_j2000, snap.dec_j2000, snap.roll,
            target.ra_j2000, target.dec_j2000, location, now,
        )
        mount_nav = None
        if guidance is not None:
            mount_nav = {
                "axis1_deg": guidance.axis1_deg,
                "axis2_deg": guidance.axis2_deg,
                "axis1_angle_deg": guidance.axes.axis1_angle_deg,
                "axis2_angle_deg": guidance.axes.axis2_angle_deg,
                "near_pole": guidance.near_pole,
                "pointing_alt_deg": guidance.pointing_alt_deg,
                "target_alt_deg": guidance.target_alt_deg,
            }

        return {
            **base,
            # Latched: stays true until off_target_deg, so a by-eye centre
            # that the solve puts a little off doesn't bring back guidance.
            "on_target": self._on_target.update(
                latch_key, nav.separation_deg, base["on_target_deg"]),
            "mount": mount_nav,
            "separation_deg": nav.separation_deg,
            "direction_text": nav.direction_text,
            "in_fov": in_fov,
            "pixel_x": offset_pixel_x,
            "pixel_y": offset_pixel_y,
            "camera_angle_deg": nav.camera_angle_deg,
            "edge_x": edge_x,
            "edge_y": edge_y,
            "edge_angle_deg": edge_angle,
        }
