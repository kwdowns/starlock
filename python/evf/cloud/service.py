"""Owns the cloud link and its two workers (pointing reporter, log uploader)."""

from __future__ import annotations

import logging
import re
import socket
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from evf.cloud.client import CloudClient, CloudError, Unauthorized
from evf.cloud.link import CloudLink, LinkInfo
from evf.cloud.pointing import PointingReporter
from evf.cloud.uploader import ObservationUploader
from evf.engine.observation_log import ObservationStore

logger = logging.getLogger(__name__)

# Pairing code from the app: XXXX-XXXX; case and the dash don't matter.
_CODE_RE = re.compile(r"^[A-Za-z0-9]{4}-?[A-Za-z0-9]{4}$")


class PairingError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def check_base_url(url: str) -> str:
    """Only https (or http to localhost, for development)."""
    u = urlparse(url.strip())
    if not u.netloc or u.path not in ("", "/") or u.query or u.fragment:
        raise PairingError("Cloud URL must look like https://host")
    if u.scheme != "https" and not (u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1")):
        raise PairingError("Cloud URL must use https")
    return f"{u.scheme}://{u.netloc}"


def pi_model() -> str | None:
    try:
        return Path("/proc/device-tree/model").read_text(errors="ignore").strip("\x00\n ") or None
    except OSError:
        return None


class CloudService:
    def __init__(
        self,
        config_dir: Path,
        *,
        default_base_url: str | None,
        device_local_id: str,
        software_version: str | None,
        snapshot: Callable[[], dict | None],
        dwelling: Callable[[], bool],
        store: ObservationStore | None,
        client_factory: Callable[[str, str | None], CloudClient] = CloudClient,
    ) -> None:
        self._link = CloudLink(config_dir)
        self._default_base_url = default_base_url
        self._local_id = device_local_id
        self._version = software_version
        self._factory = client_factory
        self._store = store
        self._lock = threading.Lock()
        self._client: CloudClient | None = None
        self._status_error: str | None = None
        self._rebuild_client()
        self.reporter = PointingReporter(self._current_client, snapshot, dwelling,
                                         self._revoked)
        self.uploader = (ObservationUploader(self._current_client, store, self._revoked)
                         if store is not None else None)

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        self.reporter.start()
        if self.uploader:
            self.uploader.start()
        if self._link.linked:
            threading.Thread(target=self.check_link, name="cloud-check", daemon=True).start()

    def stop(self) -> None:
        self.reporter.stop(send_ended=True)
        if self.uploader:
            self.uploader.stop()

    # -- link state ----------------------------------------------------------

    def _rebuild_client(self) -> None:
        info = self._link.get()
        with self._lock:
            self._client = self._factory(info.base_url, info.credential) if info else None

    def _current_client(self) -> CloudClient | None:
        with self._lock:
            return self._client

    def _revoked(self) -> None:
        """A device call got 401: the user removed this Pi or deleted the account."""
        if self._link.linked:
            logger.warning("Starlock Cloud link was revoked; unlinking")
        self._link.clear()
        self._rebuild_client()
        with self._lock:
            self._status_error = "This Starlock was removed from your Starlock Cloud account."

    def check_link(self) -> None:
        client = self._current_client()
        if client is None:
            return
        try:
            info = client.get_device()
            if isinstance(info, dict):
                self._link.set_name(info.get("name"))
            with self._lock:
                self._status_error = None
        except Unauthorized:
            self._revoked()
        except CloudError as exc:
            with self._lock:
                self._status_error = f"Can't reach Starlock Cloud: {exc}"

    def status(self) -> dict:
        out = self._link.public()
        with self._lock:
            out["error"] = self._status_error
        out["last_pointing_at"] = self.reporter.last_sent_at
        out["pointing_error"] = self.reporter.last_error
        if self.uploader:
            out["last_upload_at"] = self.uploader.last_upload_at
            out["upload_error"] = self.uploader.last_error
        out["default_base_url"] = self._default_base_url
        return out

    # -- pairing -------------------------------------------------------------

    def pair(self, code: str, base_url: str | None = None, name: str | None = None) -> dict:
        """Claim a pairing code. Blocking: call from a worker thread."""
        code = (code or "").strip()
        if not _CODE_RE.match(code):
            raise PairingError("Pairing codes look like K7P4-QX9M")
        url = check_base_url(base_url) if base_url else self._default_base_url
        if not url:
            raise PairingError("No Starlock Cloud address is configured")
        url = check_base_url(url)
        name = (name or "").strip() or f"Starlock ({socket.gethostname().split('.')[0]})"
        client = self._factory(url, None)
        try:
            resp = client.claim(code, name, model=pi_model(), software_version=self._version,
                                local_id=self._local_id)
        except CloudError as exc:
            if exc.status == 400:
                raise PairingError("Code not valid; get a new one in the app") from None
            if exc.status == 429:
                raise PairingError("Too many attempts; wait a minute and try again", 429) from None
            raise PairingError(f"Couldn't reach Starlock Cloud: {exc}", 502) from None
        try:
            device_id = str(resp["deviceId"])
            credential = str(resp["deviceCredential"])
        except (KeyError, TypeError):
            raise PairingError("Unexpected reply from Starlock Cloud", 502) from None
        self._link.save(LinkInfo(base_url=url, device_id=device_id, credential=credential,
                                 paired_at=time.time(), name=name))
        self._rebuild_client()
        with self._lock:
            self._status_error = None
        self.reporter.reset()
        if self._store is not None:
            # A new account has none of this Pi's history yet.
            self._store.reset_cloud_sync()
        if self.uploader:
            self.uploader.kick()
        logger.info("Linked to Starlock Cloud as device %s", device_id)
        return self._link.public()

    def unlink(self) -> None:
        """Unlink on the Pi: tell the service (best effort), then forget the credential."""
        client = self._current_client()
        if client is not None:
            try:
                client.delete_device()
            except CloudError as exc:
                logger.info("Couldn't remove the device from Starlock Cloud: %s", exc)
        self._link.clear()
        self._rebuild_client()
        with self._lock:
            self._status_error = None
