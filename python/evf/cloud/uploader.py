"""Observation-log backup: ``POST /v1/device/observations``.

Closed entries go up within about a minute of closing; open entries at most
every 5 minutes. Batches of up to 100, oldest first. Network errors, 429 and
5xx retry the same batch with exponential backoff and jitter (2 s .. 15 min).
A 400 for the whole batch, and entries the service rejects one by one, are
logged once and marked as sent so they aren't retried forever.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Callable

from evf.cloud.client import CloudClient, CloudError, Unauthorized
from evf.engine.observation_log import ObservationStore

logger = logging.getLogger(__name__)

BATCH = 100
POLL_S = 30.0
OPEN_INTERVAL_S = 300.0
BACKOFF_MIN_S = 2.0
BACKOFF_MAX_S = 900.0


def to_cloud_entry(store: ObservationStore, e: dict) -> dict:
    return {
        "entryId": store.cloud_entry_id(e["id"]),
        "startUnix": e["start_unix"],
        "endUnix": e["end_unix"],
        "open": e["open"],
        "raJ2000Deg": e["ra_j2000_deg"],
        "decJ2000Deg": e["dec_j2000_deg"],
        "altDeg": e["alt_deg"],
        "azDeg": e["az_deg"],
        "targetName": e["target_name"],
        "latitude": e["latitude"],
        "longitude": e["longitude"],
        "clock": e["clock"],
    }


class ObservationUploader:
    def __init__(
        self,
        client_fn: Callable[[], CloudClient | None],
        store: ObservationStore,
        on_unauthorized: Callable[[], None],
        *,
        wall: Callable[[], float] = time.time,
        sleep: Callable[[float], bool] | None = None,
    ) -> None:
        self._client_fn = client_fn
        self._store = store
        self._on_unauthorized = on_unauthorized
        self._wall = wall
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._sleep = sleep or self._wait
        self._thread: threading.Thread | None = None
        self._backoff = 0.0
        self.last_error: str | None = None
        self.last_upload_at: float | None = None
        self.uploaded = 0

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="cloud-upload", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def kick(self) -> None:
        """Upload now (e.g. right after linking)."""
        self._backoff = 0.0
        self._wake.set()

    def _wait(self, seconds: float) -> bool:
        """Sleep, waking early on kick/stop. Returns False when stopping."""
        self._wake.wait(seconds)
        self._wake.clear()
        return not self._stop.is_set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                delay = self.step()
            except Exception as exc:
                logger.warning("Cloud upload step failed: %s", exc)
                delay = POLL_S
            if not self._sleep(delay):
                break

    def step(self) -> float:
        """Upload one batch if due; returns seconds until the next step."""
        client = self._client_fn()
        if client is None:
            return POLL_S
        now = self._wall()
        pending = self._store.pending_cloud(now=now, open_interval_s=OPEN_INTERVAL_S,
                                            limit=BATCH)
        if not pending:
            return POLL_S
        try:
            result = client.post_observations([to_cloud_entry(self._store, e) for e in pending])
        except Unauthorized:
            self._on_unauthorized()
            return POLL_S
        except CloudError as exc:
            if not exc.retryable:
                logger.warning("Cloud refused an observation batch (%s); not retrying it", exc)
                self._store.mark_cloud_synced(pending, now)
                self.last_error = str(exc)
                return 0.0
            self._backoff = min(BACKOFF_MAX_S, max(BACKOFF_MIN_S, self._backoff * 2))
            delay = self._backoff * random.uniform(0.8, 1.2)
            if exc.retry_after:
                delay = max(delay, exc.retry_after)
            if self.last_error != str(exc):
                logger.info("Observation upload failed (%s); retrying in %.0f s", exc, delay)
            self.last_error = str(exc)
            return delay
        for r in (result or {}).get("results", []):
            if r.get("status") == "rejected":
                logger.warning("Cloud rejected observation %s: %s", r.get("entryId"), r.get("error"))
        self._store.mark_cloud_synced(pending, now)
        self._backoff = 0.0
        self.last_error = None
        self.last_upload_at = now
        self.uploaded += len(pending)
        return 0.0 if len(pending) == BATCH else POLL_S
