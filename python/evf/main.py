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

"""Starlock engine entry point.

Runs the engine and its servers with no window of its own: the UI is the web
app it serves (http://<host>:<webserver.port>/) and the native phone apps.
The Raspberry Pi package (starlock-headless) is the supported host; the same
command runs on any PC for development. `--no-window` is accepted for the
Pi's launcher and older scripts; it changes nothing.
"""

import json
import logging
import os
import signal
import socket
import sys
import threading
import urllib.error
import urllib.request

from evf.config.manager import ConfigManager
from evf.engine.debug_pin import debug_flag_set
from evf.engine.engine import Engine

logger = logging.getLogger(__name__)

def _check_single_instance(port: int) -> None:
    """Exit cleanly if another Starlock (or anything) is already on `port`.

    Runs before any engine threads or port binds. Distinguishes "another Starlock" from "another app on the
    port" by hitting our /api/version identifier endpoint, so the
    error message can tell the user what to do.
    """
    # Fast TCP probe first — if the port is free, the slow HTTP probe
    # would just time out. Use 127.0.0.1 explicitly: webserver binds
    # 0.0.0.0 so this always reaches our listener if any.
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            pass  # something is bound
    except OSError:
        return  # port free, fine to start

    # Port is busy. Identify the occupant.
    is_starlock = False
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/version", timeout=0.5
        ) as r:
            if r.status == 200:
                payload = json.loads(r.read(512))
                is_starlock = payload.get("app") == "starlock"
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
        pass

    if is_starlock and os.environ.get("STARLOCK_ROOT"):
        # starlock-headless .deb: the other instance is almost always the service.
        msg = (
            f"Starlock is already running on port {port} "
            f"(probably the starlock-headless service).\n"
            f"Stop it first with: sudo systemctl stop starlock-headless"
        )
    elif is_starlock:
        msg = (
            f"Starlock is already running on port {port}.\n"
            f"Close the existing window before launching another instance."
        )
    else:
        msg = (
            f"Port {port} is in use by another application.\n"
            f"Close it, or change webserver.port in your Starlock config "
            f"(see logs for the config file location)."
        )
    print(msg, file=sys.stderr)
    sys.exit(1)


def main() -> None:
    # STARLOCK_DEBUG=1 / --dev toggles in-app dev features only (sample
    # injection, frame capture, DebugPanel). On the headless Pi a jumper
    # from GPIO21 to GND does the same (evf.engine.debug_pin).
    dev_mode = (
        "--dev" in sys.argv
        or os.environ.get("STARLOCK_DEBUG") == "1"
        or debug_flag_set()
    )

    # Single-instance guard. Reads config first (we need web_port for the
    # probe) and reuses the same ConfigManager for the engine, so it isn't
    # loaded twice from disk.
    config = ConfigManager()
    _check_single_instance(config.web_port)

    engine = Engine(dev_mode=dev_mode, config=config)

    # Engine + servers come up either way
    engine.startup_logging()
    engine.startup_solver()
    engine.startup_stellarium()
    engine.startup_lx200()
    engine.startup_observation_log()
    engine.startup_webserver()
    engine.startup_discovery()
    engine.startup_cloud()

    try:
        engine.startup_camera()
        if engine.camera_connected:
            engine.startup_solver_thread()
    except Exception:
        logger.exception("Camera startup failed")
    # Keep retrying in the background, so a camera plugged in after start
    # (or after recovery gave up) comes up. The LED and CPU-cap helpers do
    # nothing on machines without the Pi's sysfs files.
    engine.start_camera_watchdog()
    engine.start_status_led()
    engine.start_cpu_cap()
    engine.start_mount_model()
    logger.info(
        "Starlock is running: http://localhost:%d/ (Ctrl-C to stop)",
        engine.config.web_port,
    )
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    stop.wait()
    engine.shutdown()


if __name__ == "__main__":
    main()
