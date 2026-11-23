"""Build web/src/data/object_sizes.json: apparent size of the curated objects.

Push-to counts as "on target" within a radius that grows with the target's
size, so a 3°-wide cluster isn't held to the same 0.15° as a small galaxy.
Sizes are the major axis in arcminutes: from OpenNGC (CC-BY-SA 4.0) when
the object has a Messier / NGC / IC designation there, else from the table
below (asterisms and big clusters OpenNGC doesn't list, rounded published
extents). Single and double stars have no size.

    uv run python scripts/build_object_sizes.py
"""

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OBJECTS = ROOT / "web" / "src" / "data" / "objects.json"
NGC_CSV = ROOT / "data" / "catalogs" / "openngc" / "NGC.csv"
OUT = ROOT / "web" / "src" / "data" / "object_sizes.json"

# id in objects.json -> major axis, arcmin. Asterism extents are the span of
# the pattern; anything over a few degrees is capped by the on-target rule.
MANUAL = {
    "alpha-persei-cluster": 185,
    "c41-hyades": 330,
    "m45-pleiades": 110,
    "cr256-coma-star-cluster": 275,
    "cr399-coathanger": 60,
    "st2-stock-2": 60,
    "c80-omega-centauri": 36,
    "c106-47-tucanae": 31,
    "c63-helix-nebula": 16,
    "c92-carina-nebula": 120,
    "c99-coalsack-nebula": 420,
    "abell39-abell-39": 3,
    "sh2-71": 2,
    "b142-barnard-142-and-143": 60,
    "b72-barnard-72": 30,
    "b86": 5,
    "crux": 360,
    "diamond-of-virgo": 3000,
    "false-cross": 480,
    "great-square-of-pegasus": 900,
    "jobs-coffin": 180,
    "northern-cross": 1200,
    "orions-belt": 180,
    "orions-sword": 90,
    "sagittarius-teapot": 900,
    "summer-triangle": 2100,
    "winter-hexagon": 3000,
}

DESIGNATION = re.compile(r"^(?:(M)\s*(\d+)|(NGC|IC)\s*(\d+)\s*([A-Z]?))$", re.I)


def ngc_sizes() -> dict[str, float]:
    sizes: dict[str, float] = {}
    with open(NGC_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter=";"):
            try:
                maj = float(row.get("MajAx") or "")
            except ValueError:
                continue
            sizes[row["Name"]] = maj
            if row.get("M"):
                sizes[f"M{int(row['M'])}"] = maj
    return sizes


def key(designation: str) -> str | None:
    m = DESIGNATION.match(designation.strip())
    if not m:
        return None
    if m.group(1):
        return f"M{int(m.group(2))}"
    return f"{m.group(3).upper()}{int(m.group(4)):04d}{m.group(5).upper()}"


def main() -> None:
    objects = json.loads(OBJECTS.read_text(encoding="utf-8"))
    ngc = ngc_sizes()
    out: dict[str, float] = {}
    for obj in objects:
        oid = obj["id"]
        if oid in MANUAL:
            out[oid] = MANUAL[oid]
            continue
        k = key(obj.get("designation") or "")
        if not (k and k in ngc):
            # Caldwell objects: "c10-ngc-663" -> NGC 663
            m = re.search(r"(?:^|-)(ngc|ic)-(\d+)", oid)
            k = f"{m.group(1).upper()}{int(m.group(2)):04d}" if m else None
        if k and k in ngc:
            out[oid] = round(ngc[k], 1)
    unknown = [o["id"] for o in objects if o["id"] not in out and o["type"] != "star"]
    OUT.write_text(json.dumps(dict(sorted(out.items())), separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{len(out)} sizes -> {OUT}")
    if unknown:
        print("No size (point-like or missing):", ", ".join(unknown))


if __name__ == "__main__":
    main()
