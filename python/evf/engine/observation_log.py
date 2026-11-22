"""Observation log: what the scope pointed at, and when.

An entry is written once the plate-solved pointing has dwelt within
`radius_deg` of one spot for `dwell_s` seconds, and closed when the scope
moves away, solving is lost for `lost_s` seconds, or the engine stops.

Three parts:
  DwellTracker      pure dwell logic (no I/O, no threads) -> open/close events
  ObservationStore  SQLite persistence, one commit per change, plus one
                    downscaled camera frame per entry in a folder next to the
                    database, trimmed oldest-first to a size quota
  ObservationLogger polling thread that reads PointingState once a second and
                    drives the two above. It never runs on the solver thread,
                    so disk I/O cannot stall solving.

Coordinates are stored as J2000 (what the solver produces). Times are UTC
unix seconds, taken from a `Clock` that can be corrected by a connected web
client when the host (e.g. a Pi hotspot without RTC or network) has a wrong
clock.
"""

import csv
import io
import logging
import os
import shutil
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from evf.engine.epoch import j2000_to_jnow
from evf.engine.mount import local_sidereal_deg, radec_to_altaz
from evf.engine.navigation import angular_separation

logger = logging.getLogger(__name__)

DB_NAME = "observations.sqlite3"

DEFAULT_DWELL_S = 30.0
DEFAULT_RADIUS_DEG = 1.0
DEFAULT_LOST_S = 15.0
HEARTBEAT_S = 30.0
POLL_S = 1.0
# A solve older than this no longer counts as the scope's current pointing.
STALE_SOLVE_S = 5.0
# A client clock differing from the host's by more than this wins.
CLOCK_TOLERANCE_S = 60.0
# Stored frames: long side in pixels, JPEG quality.
FRAME_MAX_SIDE = 1024
FRAME_QUALITY = 80
FRAMES_DIR = "observation_frames"


def shrink_jpeg(jpeg: bytes, max_side: int = FRAME_MAX_SIDE,
                quality: int = FRAME_QUALITY) -> bytes:
    """Re-encode a camera frame for storage: at most ``max_side`` pixels on
    the long side, no metadata."""
    from PIL import Image
    with Image.open(io.BytesIO(jpeg)) as img:
        img = img.convert("L" if img.mode in ("L", "I;16") else "RGB")
        img.thumbnail((max_side, max_side))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=quality, optimize=True)
        return out.getvalue()


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

class Clock:
    """Wall-clock seconds, optionally corrected by a client-reported time."""

    def __init__(self, time_fn: Callable[[], float] = time.time) -> None:
        self._time = time_fn
        self._lock = threading.Lock()
        self._offset = 0.0
        self._corrected = False

    def report_client_time(self, client_unix_s: float) -> bool:
        """Take a connecting client's clock. Returns True if it is now used.

        Within CLOCK_TOLERANCE_S of the host clock the host is trusted and any
        earlier correction is dropped; otherwise the client wins.
        """
        diff = float(client_unix_s) - self._time()
        with self._lock:
            if abs(diff) > CLOCK_TOLERANCE_S:
                self._offset = diff
                self._corrected = True
            else:
                self._offset = 0.0
                self._corrected = False
            return self._corrected

    def now(self) -> float:
        with self._lock:
            return self._time() + self._offset

    @property
    def source(self) -> str:
        with self._lock:
            return "client" if self._corrected else "system"


# ---------------------------------------------------------------------------
# Dwell logic
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DwellEvent:
    kind: str  # "open" | "close"
    wall: float  # entry start (open) or end (close), unix seconds
    ra: float = 0.0
    dec: float = 0.0


class DwellTracker:
    """Turns a stream of (time, pointing-or-None) samples into open/close events."""

    def __init__(
        self,
        dwell_s: float = DEFAULT_DWELL_S,
        radius_deg: float = DEFAULT_RADIUS_DEG,
        lost_s: float = DEFAULT_LOST_S,
    ) -> None:
        self.dwell_s = dwell_s
        self.radius_deg = radius_deg
        self.lost_s = lost_s
        self._anchor: tuple[float, float] | None = None
        self._anchor_mono = 0.0
        self._anchor_wall = 0.0
        self._last_mono = 0.0
        self._last_wall = 0.0
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def anchor(self) -> tuple[float, float] | None:
        return self._anchor

    @property
    def last_wall(self) -> float:
        return self._last_wall

    def _close(self, events: list[DwellEvent]) -> None:
        if self._open:
            events.append(DwellEvent("close", self._last_wall))
        self._anchor = None
        self._open = False

    def update(
        self, mono: float, wall: float, pos: tuple[float, float] | None,
    ) -> list[DwellEvent]:
        """Feed one sample. `pos` is (ra, dec) J2000 degrees, or None if no lock."""
        events: list[DwellEvent] = []
        if self._anchor is not None and mono - self._last_mono >= self.lost_s:
            self._close(events)  # lost for too long (or sampling stalled)
        if pos is None:
            return events
        if self._anchor is not None and angular_separation(
            pos[0], pos[1], self._anchor[0], self._anchor[1]
        ) > self.radius_deg:
            self._close(events)  # moved away
        if self._anchor is None:
            self._anchor = pos
            self._anchor_mono = mono
            self._anchor_wall = wall
        elif not self._open and mono - self._anchor_mono >= self.dwell_s:
            self._open = True
            events.append(DwellEvent("open", self._anchor_wall, *self._anchor))
        self._last_mono = mono
        self._last_wall = wall
        return events

    def finish(self) -> list[DwellEvent]:
        """Close an open entry (engine stopping)."""
        events: list[DwellEvent] = []
        self._close(events)
        return events


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_utc REAL NOT NULL,
    end_utc REAL NOT NULL,
    is_open INTEGER NOT NULL DEFAULT 1,
    ra_j2000 REAL NOT NULL,
    dec_j2000 REAL NOT NULL,
    alt REAL,
    az REAL,
    target_name TEXT,
    latitude REAL,
    longitude REAL,
    clock TEXT NOT NULL DEFAULT 'system'
);
CREATE INDEX IF NOT EXISTS observations_start ON observations (start_utc);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

# Columns added after the first release; created on open when missing.
# cloud_synced_end / cloud_synced_open: the end_utc / is_open last uploaded
# to Starlock Cloud (NULL = never). cloud_synced_at: when, unix seconds.
# frame_bytes: size of the entry's stored frame (NULL = none, or trimmed).
_CLOUD_COLUMNS = (
    ("cloud_synced_end", "REAL"),
    ("cloud_synced_open", "INTEGER"),
    ("cloud_synced_at", "REAL"),
    ("frame_bytes", "INTEGER"),
)

_COLUMNS = (
    "id, start_utc, end_utc, is_open, ra_j2000, dec_j2000, alt, az, "
    "target_name, latitude, longitude, clock, frame_bytes"
)


def iso_utc(unix_s: float) -> str:
    return datetime.fromtimestamp(unix_s, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_dict(row: tuple) -> dict:
    (id_, start, end, is_open, ra, dec, alt, az, name, lat, lon, clock, frame_bytes) = row
    return {
        "id": id_,
        "start_utc": iso_utc(start),
        "end_utc": iso_utc(end),
        "start_unix": start,
        "end_unix": end,
        "duration_s": max(0, int(round(end - start))),
        "open": bool(is_open),
        "ra_j2000_deg": ra,
        "dec_j2000_deg": dec,
        "alt_deg": alt,
        "az_deg": az,
        "target_name": name,
        "latitude": lat,
        "longitude": lon,
        "clock": clock,
        "has_frame": frame_bytes is not None,
    }


class ObservationStore:
    """SQLite store. Thread-safe; every change is committed immediately."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.frames_dir = self.path.parent / FRAMES_DIR
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        with self._lock:
            # FULL sync: the Pi is unplugged without warning.
            self._db.execute("PRAGMA synchronous=FULL")
            self._db.executescript(_SCHEMA)
            have = {r[1] for r in self._db.execute("PRAGMA table_info(observations)")}
            for name, kind in _CLOUD_COLUMNS:
                if name not in have:
                    self._db.execute(f"ALTER TABLE observations ADD COLUMN {name} {kind}")
            row = self._db.execute("SELECT value FROM meta WHERE key='db_uuid'").fetchone()
            if row is None:
                self._db_uuid = uuid.uuid4().hex
                self._db.execute("INSERT INTO meta (key, value) VALUES ('db_uuid', ?)",
                                 (self._db_uuid,))
            else:
                self._db_uuid = row[0]
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    @property
    def db_uuid(self) -> str:
        """Random id made when the database was created; part of cloud entry ids."""
        return self._db_uuid

    def cloud_entry_id(self, row_id: int) -> str:
        return f"{self._db_uuid}-{row_id}"

    def pending_cloud(self, *, now: float, open_interval_s: float,
                      limit: int = 100) -> list[dict]:
        """Entries Starlock Cloud doesn't have in their current form, oldest first.

        Closed entries are due as soon as they change. An open entry is due
        when it has never been sent, or its end moved and it was last sent
        more than ``open_interval_s`` ago (its heartbeat moves the end every
        30 s; the cloud doesn't need every one).
        """
        sql = (
            f"SELECT {_COLUMNS} FROM observations WHERE "
            "(is_open=0 AND (cloud_synced_end IS NULL OR cloud_synced_end != end_utc "
            "                OR cloud_synced_open IS NULL OR cloud_synced_open != 0)) "
            "OR (is_open=1 AND (cloud_synced_end IS NULL "
            "                OR (cloud_synced_end != end_utc AND cloud_synced_at <= ?))) "
            "ORDER BY start_utc, id LIMIT ?"
        )
        with self._lock:
            rows = self._db.execute(sql, (now - open_interval_s, int(limit))).fetchall()
        return [_row_dict(r) for r in rows]

    def mark_cloud_synced(self, entries: list[dict], at: float) -> None:
        """Record that these entries (as returned by pending_cloud) were uploaded."""
        with self._lock:
            self._db.executemany(
                "UPDATE observations SET cloud_synced_end=?, cloud_synced_open=?, "
                "cloud_synced_at=? WHERE id=?",
                [(e["end_unix"], 1 if e["open"] else 0, at, e["id"]) for e in entries],
            )
            self._db.commit()

    def reset_cloud_sync(self) -> None:
        """Forget what was uploaded (after linking to a new account)."""
        with self._lock:
            self._db.execute(
                "UPDATE observations SET cloud_synced_end=NULL, cloud_synced_open=NULL, "
                "cloud_synced_at=NULL")
            self._db.commit()

    def close_stale(self) -> int:
        """Mark entries left open by an unclean stop as closed.

        Their end_utc is the last heartbeat, so that is where they end.
        """
        with self._lock:
            cur = self._db.execute("UPDATE observations SET is_open=0 WHERE is_open=1")
            self._db.commit()
            return cur.rowcount

    def open_entry(
        self, start: float, ra: float, dec: float, *, alt: float | None = None,
        az: float | None = None, target_name: str | None = None,
        latitude: float | None = None, longitude: float | None = None,
        clock: str = "system",
    ) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO observations (start_utc, end_utc, is_open, ra_j2000, "
                "dec_j2000, alt, az, target_name, latitude, longitude, clock) "
                "VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)",
                (start, start, ra, dec, alt, az, target_name, latitude, longitude, clock),
            )
            self._db.commit()
            return int(cur.lastrowid)

    def touch(self, entry_id: int, end: float, target_name: str | None = None) -> None:
        """Heartbeat: move the end time on, and fill in a target name if newly known."""
        with self._lock:
            self._db.execute(
                "UPDATE observations SET end_utc=MAX(end_utc, ?), "
                "target_name=COALESCE(?, target_name) WHERE id=?",
                (end, target_name, entry_id),
            )
            self._db.commit()

    def close_entry(self, entry_id: int, end: float) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE observations SET end_utc=MAX(end_utc, ?), is_open=0 WHERE id=?",
                (end, entry_id),
            )
            self._db.commit()

    # -- frames ---------------------------------------------------------------

    def _frame_file(self, entry_id: int) -> Path:
        return self.frames_dir / f"{int(entry_id)}.jpg"

    def save_frame(self, entry_id: int, jpeg: bytes) -> None:
        """Store (or replace) an entry's frame. Written to a temp file and
        renamed, so a power cut never leaves half a JPEG."""
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        dest = self._frame_file(entry_id)
        tmp = dest.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            f.write(jpeg)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, dest)
        with self._lock:
            self._db.execute("UPDATE observations SET frame_bytes=? WHERE id=?",
                             (len(jpeg), entry_id))
            self._db.commit()

    def frame(self, entry_id: int) -> bytes | None:
        with self._lock:
            row = self._db.execute(
                "SELECT frame_bytes FROM observations WHERE id=?", (int(entry_id),)).fetchone()
        if row is None or row[0] is None:
            return None
        try:
            return self._frame_file(entry_id).read_bytes()
        except OSError:
            return None

    def frames_bytes(self) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT COALESCE(SUM(frame_bytes), 0) FROM observations").fetchone()
        return int(row[0])

    def _drop_frames(self, ids: list[int]) -> None:
        for i in ids:
            try:
                self._frame_file(i).unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                logger.warning("Couldn't delete frame %s: %s", i, exc)

    def trim_frames(self, quota_bytes: int, min_free_bytes: int = 0,
                    keep: int | None = None,
                    free_bytes: Callable[[], int] | None = None) -> int:
        """Delete the oldest frames until they use at most ``quota_bytes``
        and the disk has at least ``min_free_bytes`` free. The entries stay;
        only their pictures go. Returns how many frames were deleted."""
        if free_bytes is None:
            def free_bytes() -> int:
                try:
                    return shutil.disk_usage(self.path.parent).free
                except OSError:
                    return 1 << 62
        with self._lock:
            rows = self._db.execute(
                "SELECT id, frame_bytes FROM observations WHERE frame_bytes IS NOT NULL "
                "ORDER BY start_utc, id").fetchall()
        total = sum(b for _, b in rows)
        dropped: list[int] = []
        freed = 0
        free = free_bytes()
        for entry_id, size in rows:
            if total <= quota_bytes and free + freed >= min_free_bytes:
                break
            if entry_id == keep:
                continue
            dropped.append(entry_id)
            total -= size
            freed += size
        if dropped:
            with self._lock:
                self._db.executemany("UPDATE observations SET frame_bytes=NULL WHERE id=?",
                                     [(i,) for i in dropped])
                self._db.commit()
            self._drop_frames(dropped)
            logger.info("Observation log: trimmed %d oldest frame(s)", len(dropped))
        return len(dropped)

    def list(self, start: float, end: float, limit: int | None = None) -> list[dict]:
        """Entries overlapping [start, end], newest first."""
        sql = (
            f"SELECT {_COLUMNS} FROM observations "
            "WHERE start_utc <= ? AND end_utc >= ? ORDER BY start_utc DESC, id DESC"
        )
        params: list = [end, start]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._lock:
            rows = self._db.execute(sql, params).fetchall()
        return [_row_dict(r) for r in rows]

    def delete(self, start: float, end: float) -> int:
        """Delete closed entries overlapping [start, end], and their frames."""
        where = "start_utc <= ? AND end_utc >= ? AND is_open=0"
        with self._lock:
            ids = [r[0] for r in self._db.execute(
                f"SELECT id FROM observations WHERE {where} AND frame_bytes IS NOT NULL",
                (end, start))]
            cur = self._db.execute(f"DELETE FROM observations WHERE {where}", (end, start))
            self._db.commit()
            n = cur.rowcount
        self._drop_frames(ids)
        return n


CSV_HEADER = [
    "start_utc", "end_utc", "duration_s", "target", "ra_j2000_deg",
    "dec_j2000_deg", "alt_deg", "az_deg", "latitude", "longitude", "clock",
]


def _csv_text(value: str | None) -> str:
    # Stop spreadsheet apps treating a name as a formula.
    if value and value[0] in "=+-@\t\r":
        return "'" + value
    return value or ""


def _num(value: float | None, digits: int) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def entries_to_csv(entries: list[dict]) -> str:
    """CSV text, oldest entry first. RA/Dec are J2000 degrees."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(CSV_HEADER)
    for e in sorted(entries, key=lambda e: (e["start_unix"], e["id"])):
        w.writerow([
            e["start_utc"], e["end_utc"], e["duration_s"], _csv_text(e["target_name"]),
            _num(e["ra_j2000_deg"], 4), _num(e["dec_j2000_deg"], 4),
            _num(e["alt_deg"], 2), _num(e["az_deg"], 2),
            _num(e["latitude"], 4), _num(e["longitude"], 4), e["clock"],
        ])
    return out.getvalue()


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

class ObservationLogger:
    """Samples pointing once a second and records dwell entries.

    pointing:  PointingState (read-only use)
    location:  () -> {"latitude", "longitude", ...}; either may be None
    target:    () -> (ra_j2000, dec_j2000, name_or_None) of the active GOTO
               target, or None
    enabled:   () -> bool, checked every step (config flag)
    frame:     () -> latest camera JPEG or None; stored (downscaled) with each
               new entry when given
    frame_limits: () -> (quota_bytes, min_free_bytes) for stored frames, or
               None to store no frames
    """

    def __init__(
        self,
        store: ObservationStore,
        pointing,
        clock: Clock,
        *,
        location: Callable[[], dict] | None = None,
        target: Callable[[], tuple[float, float, str | None] | None] | None = None,
        tracker: DwellTracker | None = None,
        enabled: Callable[[], bool] = lambda: True,
        frame: Callable[[], bytes | None] | None = None,
        frame_limits: Callable[[], tuple[int, int] | None] | None = None,
    ) -> None:
        self._store = store
        self._frame = frame
        self._frame_limits = frame_limits
        self._pointing = pointing
        self._clock = clock
        self._location = location
        self._target = target
        self._tracker = tracker or DwellTracker()
        self._enabled = enabled
        self._lock = threading.Lock()
        self._entry_id: int | None = None
        self._last_heartbeat = 0.0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        n = self._store.close_stale()
        if n:
            logger.info("Observation log: closed %d entry(ies) left open", n)
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="observation-log", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        with self._lock:
            self._apply(self._tracker.finish())

    def _run(self) -> None:
        while not self._stop.wait(POLL_S):
            try:
                self.step(time.monotonic(), self._clock.now())
            except Exception as exc:  # never let logging kill the thread
                logger.warning("Observation log step failed: %s", exc)

    # -- one sampling step (also called directly by tests) --------------------

    @property
    def dwelling(self) -> bool:
        """An entry is open: the scope has dwelt here long enough to log it."""
        with self._lock:
            return self._entry_id is not None

    def _sample(self, mono: float) -> tuple[float, float] | None:
        snap = self._pointing.read()
        if not snap.valid or mono - snap.last_success_timestamp > STALE_SOLVE_S:
            return None
        return (snap.ra_j2000, snap.dec_j2000)

    def step(self, mono: float, wall: float) -> None:
        with self._lock:
            if not self._enabled():
                self._apply(self._tracker.finish())
                return
            self._apply(self._tracker.update(mono, wall, self._sample(mono)), mono)
            if self._entry_id is not None and mono - self._last_heartbeat >= HEARTBEAT_S:
                self._heartbeat(mono)

    def _matching_target_name(self, ra: float, dec: float) -> str | None:
        if self._target is None:
            return None
        t = self._target()
        if t is None or not t[2]:
            return None
        if angular_separation(ra, dec, t[0], t[1]) <= self._tracker.radius_deg:
            return t[2]
        return None

    def _heartbeat(self, mono: float) -> None:
        anchor = self._tracker.anchor
        name = self._matching_target_name(*anchor) if anchor else None
        try:
            self._store.touch(self._entry_id, self._tracker.last_wall, name)
        except Exception as exc:
            logger.warning("Observation log write failed: %s", exc)
        self._last_heartbeat = mono

    def _apply(self, events: list[DwellEvent], mono: float = 0.0) -> None:
        for ev in events:
            try:
                if ev.kind == "open":
                    self._open(ev, mono)
                elif self._entry_id is not None:
                    self._store.close_entry(self._entry_id, ev.wall)
            except Exception as exc:
                logger.warning("Observation log write failed: %s", exc)
            if ev.kind == "close":
                self._entry_id = None

    def _open(self, ev: DwellEvent, mono: float) -> None:
        lat = lon = alt = az = None
        if self._location is not None:
            loc = self._location()
            lat, lon = loc.get("latitude"), loc.get("longitude")
        if lat is not None and lon is not None:
            ra_now, dec_now = j2000_to_jnow(ev.ra, ev.dec)
            alt, az = radec_to_altaz(
                ra_now, dec_now, lat, local_sidereal_deg(lon, ev.wall))
        self._entry_id = self._store.open_entry(
            ev.wall, ev.ra, ev.dec, alt=alt, az=az,
            target_name=self._matching_target_name(ev.ra, ev.dec),
            latitude=lat, longitude=lon, clock=self._clock.source,
        )
        self._last_heartbeat = mono
        logger.info("Observation log: opened entry %d at RA %.2f Dec %.2f",
                    self._entry_id, ev.ra, ev.dec)
        self._store_frame(self._entry_id)

    def _store_frame(self, entry_id: int) -> None:
        """Keep the frame the scope is resting on (it has been still for the
        whole dwell), then trim the oldest frames back under the quota."""
        if self._frame is None or self._frame_limits is None:
            return
        limits = self._frame_limits()
        if limits is None:
            return
        try:
            jpeg = self._frame()
            if not jpeg:
                return
            self._store.save_frame(entry_id, shrink_jpeg(jpeg))
            self._store.trim_frames(limits[0], limits[1], keep=entry_id)
        except Exception as exc:
            logger.warning("Observation log: couldn't store frame: %s", exc)

    # -- read side used by the web server ---------------------------------------

    @property
    def store(self) -> ObservationStore:
        return self._store

    @property
    def clock(self) -> Clock:
        return self._clock
