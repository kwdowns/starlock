"""Where the Moon, the planets and a few bright asteroids are right now.

Stars and deep-sky objects stay put, so they live in catalogue files; these
move, so their positions are worked out for a given time:

- Moon, planets and Pluto: astronomy-engine (MIT; VSOP87 / its own lunar
  and Pluto models, good to well under an arcminute).
- Ceres, Vesta, Pallas, Juno, Iris, Hebe: two-body orbits from the JPL
  elements in ``data/minor_planets.json`` (refresh with
  ``scripts/update_minor_planets.py``). Good to a few arcminutes within a
  year or so of the elements' epoch; plenty for push-to.

The Sun is never listed: nobody should push a telescope at it.

Positions are astrometric J2000 RA/Dec, the frame the plate solver and the
goto target use. Topocentric (from the observer's site) when a location is
known, which only matters for the Moon (up to ~1° of parallax).
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import astronomy

logger = logging.getLogger(__name__)

# Light travel time, days per AU.
_LIGHT_DAYS_PER_AU = 0.0057755183
# J2000 mean obliquity of the ecliptic.
_OBLIQUITY_RAD = math.radians(23.4392911)
# Closer than this to the Sun (degrees), a body is flagged as unsafe/unseeable.
NEAR_SUN_DEG = 15.0

_PLANETS = [
    # (body, id, name, kind)
    (astronomy.Body.Moon, "moon", "Moon", "moon"),
    (astronomy.Body.Mercury, "mercury", "Mercury", "planet"),
    (astronomy.Body.Venus, "venus", "Venus", "planet"),
    (astronomy.Body.Mars, "mars", "Mars", "planet"),
    (astronomy.Body.Jupiter, "jupiter", "Jupiter", "planet"),
    (astronomy.Body.Saturn, "saturn", "Saturn", "planet"),
    (astronomy.Body.Uranus, "uranus", "Uranus", "planet"),
    (astronomy.Body.Neptune, "neptune", "Neptune", "planet"),
    (astronomy.Body.Pluto, "pluto", "Pluto", "dwarf-planet"),
]


@dataclass(frozen=True)
class MinorPlanet:
    id: str
    name: str
    kind: str
    epoch_jd_tdb: float
    a_au: float
    e: float
    i_deg: float
    node_deg: float
    peri_deg: float
    mean_anomaly_deg: float
    mean_motion_deg_per_day: float
    H: float
    G: float


def load_minor_planets(path: Path) -> list[MinorPlanet]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return [MinorPlanet(**{k: b[k] for k in MinorPlanet.__dataclass_fields__})
                for b in data["bodies"]]
    except FileNotFoundError:
        logger.warning("No minor-planet elements at %s; asteroids won't be listed", path)
    except Exception as exc:
        logger.warning("Couldn't read minor-planet elements %s: %s", path, exc)
    return []


def _ra_dec(v: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = v
    dist = math.sqrt(x * x + y * y + z * z)
    ra = math.degrees(math.atan2(y, x)) % 360.0
    dec = math.degrees(math.asin(max(-1.0, min(1.0, z / dist))))
    return ra, dec, dist


def _angle(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    dot = sum(p * q for p, q in zip(a, b))
    na = math.sqrt(sum(p * p for p in a))
    nb = math.sqrt(sum(q * q for q in b))
    return math.degrees(math.acos(max(-1.0, min(1.0, dot / (na * nb)))))


def _helio_eqj(mp: MinorPlanet, jd_tdb: float) -> tuple[float, float, float]:
    """Heliocentric J2000 equatorial position (AU) from the two-body orbit."""
    m = math.radians((mp.mean_anomaly_deg + mp.mean_motion_deg_per_day
                      * (jd_tdb - mp.epoch_jd_tdb)) % 360.0)
    e = mp.e
    ea = m if e < 0.8 else math.pi
    for _ in range(30):
        d = (ea - e * math.sin(ea) - m) / (1 - e * math.cos(ea))
        ea -= d
        if abs(d) < 1e-12:
            break
    xv = mp.a_au * (math.cos(ea) - e)
    yv = mp.a_au * math.sqrt(1 - e * e) * math.sin(ea)
    nu = math.atan2(yv, xv)
    r = math.hypot(xv, yv)
    node, peri, inc = (math.radians(mp.node_deg), math.radians(mp.peri_deg),
                       math.radians(mp.i_deg))
    u = nu + peri
    # Ecliptic J2000
    xe = r * (math.cos(node) * math.cos(u) - math.sin(node) * math.sin(u) * math.cos(inc))
    ye = r * (math.sin(node) * math.cos(u) + math.cos(node) * math.sin(u) * math.cos(inc))
    ze = r * math.sin(u) * math.sin(inc)
    # -> equatorial J2000
    c, s = math.cos(_OBLIQUITY_RAD), math.sin(_OBLIQUITY_RAD)
    return (xe, ye * c - ze * s, ye * s + ze * c)


def _hg_magnitude(h: float, g: float, r: float, delta: float, phase_deg: float) -> float:
    t = math.tan(math.radians(phase_deg) / 2)
    phi1 = math.exp(-3.33 * t ** 0.63)
    phi2 = math.exp(-1.87 * t ** 1.22)
    return h + 5 * math.log10(r * delta) - 2.5 * math.log10((1 - g) * phi1 + g * phi2)


def _constellation(ra_deg: float, dec_deg: float) -> str:
    try:
        return astronomy.Constellation(ra_deg / 15.0, dec_deg).name
    except Exception:
        return ""


def _vec(v) -> tuple[float, float, float]:
    return (v.x, v.y, v.z)


def positions(when: datetime | float, latitude: float | None = None,
              longitude: float | None = None,
              minor_planets: list[MinorPlanet] | None = None) -> list[dict]:
    """Every listed body at ``when`` (UTC datetime or unix seconds)."""
    if not isinstance(when, datetime):
        when = datetime.fromtimestamp(float(when), timezone.utc)
    t = astronomy.Time.Make(when.year, when.month, when.day, when.hour, when.minute,
                            when.second + when.microsecond / 1e6)
    observer = (astronomy.Observer(latitude, longitude, 0.0)
                if latitude is not None and longitude is not None else None)
    sun_geo = _vec(astronomy.GeoVector(astronomy.Body.Sun, t, True))
    out: list[dict] = []

    for body, ident, name, kind in _PLANETS:
        try:
            if observer is not None:
                eq = astronomy.Equator(body, t, observer, False, True)
                ra, dec, dist = eq.ra * 15.0, eq.dec, eq.dist
                geo = _vec(eq.vec)
            else:
                geo = _vec(astronomy.GeoVector(body, t, True))
                ra, dec, dist = _ra_dec(geo)
            ill = astronomy.Illumination(body, t)
            out.append({
                "id": ident, "name": name, "kind": kind,
                "ra_j2000_deg": round(ra, 5), "dec_j2000_deg": round(dec, 5),
                "magnitude": round(ill.mag, 1),
                "distance_au": round(dist, 5),
                "phase_fraction": round(ill.phase_fraction, 3),
                "elongation_deg": round(_angle(sun_geo, geo), 1),
                "constellation": _constellation(ra, dec),
            })
        except Exception as exc:
            logger.warning("Couldn't compute %s: %s", name, exc)

    if minor_planets:
        earth = _vec(astronomy.HelioVector(astronomy.Body.Earth, t))
        jd = t.tt + 2451545.0
        for mp in minor_planets:
            try:
                helio = _helio_eqj(mp, jd)
                for _ in range(2):  # light time
                    geo = tuple(h - e for h, e in zip(helio, earth))
                    delta = math.sqrt(sum(c * c for c in geo))
                    helio = _helio_eqj(mp, jd - delta * _LIGHT_DAYS_PER_AU)
                geo = tuple(h - e for h, e in zip(helio, earth))
                ra, dec, delta = _ra_dec(geo)
                r = math.sqrt(sum(c * c for c in helio))
                phase = _angle(tuple(-c for c in helio), tuple(-c for c in geo))
                out.append({
                    "id": mp.id, "name": mp.name, "kind": mp.kind,
                    "ra_j2000_deg": round(ra, 5), "dec_j2000_deg": round(dec, 5),
                    "magnitude": round(_hg_magnitude(mp.H, mp.G, r, delta, phase), 1),
                    "distance_au": round(delta, 5),
                    "phase_fraction": None,
                    "elongation_deg": round(_angle(sun_geo, geo), 1),
                    "constellation": _constellation(ra, dec),
                })
            except Exception as exc:
                logger.warning("Couldn't compute %s: %s", mp.name, exc)

    for b in out:
        b["near_sun"] = b["elongation_deg"] < NEAR_SUN_DEG
    return out
