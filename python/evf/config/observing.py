"""Saved observing sites and equipment (``config.json`` ``observing``).

A site is a location plus a horizon mask; telescopes, eyepieces and finders
are the gear. ``current`` says which of each is in use. The engine keeps
using the plain ``location`` and ``horizon`` settings everywhere; picking a
site copies its values into them, and while a site is in use, changing the
location or horizon also writes into that site.

Pure helpers (validation, migration, optics) plus ``ObservingLibrary``, the
thread-safe owner of all changes. See specs/start/SPEC_EQUIPMENT_SITES.md.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import uuid

from evf.config.manager import DEFAULT_HORIZON, ConfigManager, validate_horizon

logger = logging.getLogger(__name__)

KINDS = ("sites", "telescopes", "eyepieces", "finders")
# The `current` slot for each kind.
SLOTS = {
    "sites": "site_id",
    "telescopes": "telescope_id",
    "eyepieces": "eyepiece_id",
    "finders": "finder_id",
}
MAX_ITEMS = 50
NAME_MAX = 60
DEFAULT_AFOV_DEG = 52
DEFAULT_REFLEX_RINGS = [0.5, 2, 4]
MIGRATED_SITE_NAME = "My site"

_ID = re.compile(r"^[0-9a-f]{32}$")


class NotFound(LookupError):
    """Unknown kind or id (HTTP 404)."""


def empty() -> dict:
    return {
        "sites": [], "telescopes": [], "eyepieces": [], "finders": [],
        "current": {slot: None for slot in SLOTS.values()},
    }


def new_id() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _name(body: dict) -> str:
    name = body.get("name")
    if not isinstance(name, str):
        raise ValueError("name is required")
    name = name.strip()
    if not 1 <= len(name) <= NAME_MAX:
        raise ValueError(f"name must be 1-{NAME_MAX} characters")
    return name


def _number(body: dict, key: str, lo: float, hi: float, default=None):
    value = body.get(key)
    if value is None and default is not None:
        return default
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)):
        raise ValueError(f"{key} must be a number")
    if not lo <= value <= hi:
        raise ValueError(f"{key} must be {lo:g}-{hi:g}")
    return value


def _rings(value) -> list:
    if value is None:
        return list(DEFAULT_REFLEX_RINGS)
    if not isinstance(value, list) or not 1 <= len(value) <= 4:
        raise ValueError("rings_deg must be 1-4 numbers")
    out = []
    for v in value:
        if (isinstance(v, bool) or not isinstance(v, (int, float))
                or not math.isfinite(v) or not 0.1 <= v <= 10):
            raise ValueError("each ring must be 0.1-10 degrees")
        if out and v <= out[-1]:
            raise ValueError("rings_deg must be in ascending order")
        out.append(v)
    return out


def validate_item(kind: str, body: object) -> dict:
    """The item (without id) as it will be stored; raises ValueError.

    Unknown fields are dropped; an ``id`` in the body is ignored.
    """
    if kind not in KINDS:
        raise NotFound(f"unknown kind {kind!r}")
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    item: dict = {"name": _name(body)}
    if kind == "sites":
        item["latitude"] = _number(body, "latitude", -90, 90)
        item["longitude"] = _number(body, "longitude", -180, 180)
        horizon = body.get("horizon")
        try:
            item["horizon"] = (list(DEFAULT_HORIZON) if horizon is None
                               else validate_horizon(horizon))
        except ValueError as exc:
            raise ValueError(f"horizon: {exc}") from None
    elif kind == "telescopes":
        item["aperture_mm"] = _number(body, "aperture_mm", 10, 2000)
        item["focal_length_mm"] = _number(body, "focal_length_mm", 50, 20000)
    elif kind == "eyepieces":
        item["focal_length_mm"] = _number(body, "focal_length_mm", 1, 100)
        item["afov_deg"] = _number(body, "afov_deg", 20, 120, DEFAULT_AFOV_DEG)
    else:  # finders
        finder_kind = body.get("kind")
        if finder_kind == "optical":
            item["kind"] = "optical"
            item["field_deg"] = _number(body, "field_deg", 0.5, 20)
        elif finder_kind == "reflex":
            item["kind"] = "reflex"
            item["rings_deg"] = _rings(body.get("rings_deg"))
        else:
            raise ValueError("kind must be 'optical' or 'reflex'")
    return item


def sanitize(raw: object) -> tuple[dict, bool]:
    """Check a saved ``observing`` block: broken entries are dropped with a
    warning, never fatal. Returns (clean block, whether anything changed)."""
    if not isinstance(raw, dict):
        logger.warning("observing: not an object, starting empty")
        return empty(), True
    out = empty()
    for kind in KINDS:
        items = raw.get(kind, [])
        if not isinstance(items, list):
            logger.warning("observing.%s: not a list, dropped", kind)
            continue
        seen: set[str] = set()
        for entry in items:
            try:
                if not isinstance(entry, dict):
                    raise ValueError("not an object")
                item_id = entry.get("id")
                if not isinstance(item_id, str) or not _ID.match(item_id):
                    raise ValueError("bad id")
                if item_id in seen:
                    raise ValueError("duplicate id")
                if len(out[kind]) >= MAX_ITEMS:
                    raise ValueError(f"more than {MAX_ITEMS} items")
                item = {"id": item_id, **validate_item(kind, entry)}
            except ValueError as exc:
                logger.warning("observing.%s: dropped a broken entry (%s): %r",
                               kind, exc, entry)
                continue
            seen.add(item_id)
            out[kind].append(item)
    current = raw.get("current")
    current = current if isinstance(current, dict) else {}
    for kind, slot in SLOTS.items():
        value = current.get(slot)
        if value is not None and not any(i["id"] == value for i in out[kind]):
            logger.warning("observing.current.%s: unknown id %r, cleared", slot, value)
            value = None
        out["current"][slot] = value
    return out, out != raw


def migrate(latitude, longitude, horizon) -> dict:
    """The first ``observing`` block for a config from before sites existed:
    one site "My site" from the location and horizon, in use; or nothing
    when no location is set."""
    obs = empty()
    try:
        site = validate_item("sites", {
            "name": MIGRATED_SITE_NAME, "latitude": latitude, "longitude": longitude,
        })
    except ValueError:
        return obs
    try:
        site["horizon"] = validate_horizon(horizon)
    except ValueError:
        pass
    site = {"id": new_id(), **site}
    obs["sites"].append(site)
    obs["current"]["site_id"] = site["id"]
    logger.info("observing: saved the location as the site %r", MIGRATED_SITE_NAME)
    return obs


# ---------------------------------------------------------------------------
# Read side
# ---------------------------------------------------------------------------

def _find(obs: dict, kind: str, item_id) -> dict | None:
    if item_id is None:
        return None
    return next((i for i in obs.get(kind, []) if i["id"] == item_id), None)


def in_use(obs: dict) -> dict:
    """The items in use: {"site", "telescope", "eyepiece", "finder"} (None each)."""
    cur = obs.get("current") or {}
    return {
        "site": _find(obs, "sites", cur.get("site_id")),
        "telescope": _find(obs, "telescopes", cur.get("telescope_id")),
        "eyepiece": _find(obs, "eyepieces", cur.get("eyepiece_id")),
        "finder": _find(obs, "finders", cur.get("finder_id")),
    }


def compute_optics(telescope: dict | None, eyepiece: dict | None,
                   finder: dict | None) -> dict:
    """Magnification, true field and exit pupil (2 decimals; null unless a
    telescope and an eyepiece are both given), and the finder's circles."""
    mag = field = pupil = None
    if telescope is not None and eyepiece is not None:
        m = telescope["focal_length_mm"] / eyepiece["focal_length_mm"]
        mag = round(m, 2)
        field = round(eyepiece["afov_deg"] / m, 2)
        pupil = round(telescope["aperture_mm"] / m, 2)
    rings = None
    if finder is not None:
        rings = ([finder["field_deg"]] if finder["kind"] == "optical"
                 else list(finder["rings_deg"]))
    return {
        "magnification": mag,
        "true_field_deg": field,
        "exit_pupil_mm": pupil,
        "finder_rings_deg": rings,
    }


def payload(obs: dict) -> dict:
    """The ``/ws`` ``observing`` block."""
    use = in_use(obs)
    return {
        **{kind: obs.get(kind, []) for kind in KINDS},
        "current": {slot: (obs.get("current") or {}).get(slot) for slot in SLOTS.values()},
        "optics": compute_optics(use["telescope"], use["eyepiece"], use["finder"]),
    }


def log_fields(obs: dict) -> dict:
    """Names in use and the magnification, for a new observation log entry."""
    use = in_use(obs)
    optics = compute_optics(use["telescope"], use["eyepiece"], use["finder"])
    return {
        "site_name": use["site"]["name"] if use["site"] else None,
        "telescope": use["telescope"]["name"] if use["telescope"] else None,
        "eyepiece": use["eyepiece"]["name"] if use["eyepiece"] else None,
        "finder": use["finder"]["name"] if use["finder"] else None,
        "magnification": optics["magnification"],
    }


# ---------------------------------------------------------------------------
# Changes
# ---------------------------------------------------------------------------

class ObservingLibrary:
    """All changes to sites, equipment, the location and the horizon.

    Every change is one read-modify-write under a lock and one config save,
    so the site in use and the location / horizon never drift apart.
    """

    def __init__(self, config: ConfigManager) -> None:
        self._config = config
        self._lock = threading.Lock()

    # -- read -----------------------------------------------------------------

    def snapshot(self) -> dict:
        return payload(self._config.observing)

    def log_fields(self) -> dict:
        return log_fields(self._config.observing)

    # -- helpers --------------------------------------------------------------

    def _apply_site(self, site: dict) -> None:
        """Copy a site's location and horizon into the engine's settings."""
        self._config.location = (float(site["latitude"]), float(site["longitude"]))
        self._config.horizon = site["horizon"]

    @staticmethod
    def _index(obs: dict, kind: str, item_id: str) -> int:
        if kind not in KINDS:
            raise NotFound(f"unknown kind {kind!r}")
        for n, item in enumerate(obs[kind]):
            if item["id"] == item_id:
                return n
        raise NotFound(f"no such {kind[:-1]}")

    # -- items ------------------------------------------------------------------

    def create(self, kind: str, body: object) -> str:
        item = validate_item(kind, body)
        with self._lock, self._config.batch():
            obs = self._config.observing
            if len(obs[kind]) >= MAX_ITEMS:
                raise ValueError(f"at most {MAX_ITEMS} {kind}")
            item = {"id": new_id(), **item}
            obs[kind].append(item)
            self._config.observing = obs
        return item["id"]

    def update(self, kind: str, item_id: str, body: object) -> None:
        if kind not in KINDS:
            raise NotFound(f"unknown kind {kind!r}")
        item = validate_item(kind, body)
        with self._lock, self._config.batch():
            obs = self._config.observing
            n = self._index(obs, kind, item_id)
            obs[kind][n] = {"id": item_id, **item}
            self._config.observing = obs
            if kind == "sites" and obs["current"]["site_id"] == item_id:
                self._apply_site(obs[kind][n])

    def delete(self, kind: str, item_id: str) -> None:
        """Delete an item; deleting the one in use clears that slot (the
        site's location and horizon stay, as ad-hoc values)."""
        with self._lock, self._config.batch():
            obs = self._config.observing
            n = self._index(obs, kind, item_id)
            del obs[kind][n]
            slot = SLOTS[kind]
            if obs["current"][slot] == item_id:
                obs["current"][slot] = None
            self._config.observing = obs

    def set_current(self, body: object) -> None:
        """Choose the items in use. A missing key leaves that slot; null
        clears it. Selecting a site applies its location and horizon."""
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
        with self._lock, self._config.batch():
            obs = self._config.observing
            changes: dict[str, str | None] = {}
            for kind, slot in SLOTS.items():
                if slot not in body:
                    continue
                value = body[slot]
                if value is not None and not isinstance(value, str):
                    raise ValueError(f"{slot} must be an id or null")
                if value is not None:
                    self._index(obs, kind, value)  # NotFound
                changes[slot] = value
            if not changes:
                return
            obs["current"].update(changes)
            self._config.observing = obs
            site_id = changes.get("site_id")
            if site_id is not None:
                self._apply_site(obs["sites"][self._index(obs, "sites", site_id)])

    # -- location and horizon (POST /api/settings) ------------------------------

    def set_location(self, latitude: float | None, longitude: float | None) -> None:
        """The manual location. With a site in use it moves that site too;
        clearing it (None) also clears the site in use."""
        with self._lock, self._config.batch():
            obs = self._config.observing
            site_id = obs["current"]["site_id"]
            if latitude is None or longitude is None:
                self._config.location = None
                if site_id is not None:
                    obs["current"]["site_id"] = None
                    self._config.observing = obs
                return
            lat, lon = float(latitude), float(longitude)
            self._config.location = (lat, lon)  # validates; raises ValueError
            if site_id is not None:
                site = obs["sites"][self._index(obs, "sites", site_id)]
                site["latitude"], site["longitude"] = lat, lon
                self._config.observing = obs

    def set_horizon(self, obscured: list[int] | None) -> None:
        """The horizon mask (None = the default). With a site in use it is
        saved into that site too."""
        mask = list(DEFAULT_HORIZON) if obscured is None else validate_horizon(obscured)
        with self._lock, self._config.batch():
            self._config.horizon = mask
            obs = self._config.observing
            site_id = obs["current"]["site_id"]
            if site_id is not None:
                obs["sites"][self._index(obs, "sites", site_id)]["horizon"] = mask
                self._config.observing = obs
