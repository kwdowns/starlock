"""Refresh data/minor_planets.json from JPL's Small-Body Database.

Run before a release (the elements drift: two-body positions from them stay
within a few arcminutes for about a year either side of their epoch):

    uv run python scripts/update_minor_planets.py

Only the bright main-belt objects a backyard telescope can show. Pluto and
the planets come from astronomy-engine, not from here.
"""

import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BODIES = [
    # (sstr, id, display name, kind)
    ("1", "ceres", "Ceres", "dwarf-planet"),
    ("4", "vesta", "Vesta", "asteroid"),
    ("2", "pallas", "Pallas", "asteroid"),
    ("3", "juno", "Juno", "asteroid"),
    ("7", "iris", "Iris", "asteroid"),
    ("6", "hebe", "Hebe", "asteroid"),
]

API = "https://ssd-api.jpl.nasa.gov/sbdb.api?sstr={}&phys-par=1&full-prec=1"
OUT = Path(__file__).resolve().parent.parent / "data" / "minor_planets.json"


def fetch(sstr: str) -> dict:
    req = urllib.request.Request(API.format(sstr), headers={"User-Agent": "starlock-catalog-script"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main() -> int:
    bodies = []
    for sstr, ident, name, kind in BODIES:
        d = fetch(sstr)
        orbit = d["orbit"]
        el = {e["name"]: float(e["value"]) for e in orbit["elements"] if e.get("value") is not None}
        phys = {p["name"]: p["value"] for p in d.get("phys_par", [])}
        bodies.append({
            "id": ident,
            "name": name,
            "kind": kind,
            "epoch_jd_tdb": float(orbit["epoch"]),
            "a_au": el["a"],
            "e": el["e"],
            "i_deg": el["i"],
            "node_deg": el["om"],
            "peri_deg": el["w"],
            "mean_anomaly_deg": el["ma"],
            "mean_motion_deg_per_day": el["n"],
            "H": float(phys.get("H", 99)),
            "G": float(phys.get("G") or 0.15),
        })
        print(f"{name}: epoch JD {orbit['epoch']}, a {el['a']:.4f} AU, H {phys.get('H')}")
    OUT.write_text(json.dumps({
        "source": "JPL Small-Body Database (ssd-api.jpl.nasa.gov), heliocentric ecliptic J2000",
        "fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bodies": bodies,
    }, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
