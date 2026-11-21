import { altAzFromRaDec } from "@/lib/astronomy";
import type { CatalogObject } from "@/lib/catalogTypes";
import { angularSepDeg } from "@/lib/nearest";
import type { CatalogFilterState } from "./filterState";
import { buddyItem, typeLabel, type Location, type TargetItem } from "./items";

export const ALT_THRESHOLD_DEG = 20;

export type SortKey = "type" | "mag" | "alt" | "near";

/** Where the scope points, J2000 degrees. */
export interface SkyPoint {
  ra_deg: number;
  dec_deg: number;
}

export interface TonightRow {
  item: TargetItem;
  altDeg: number;
  azDeg: number;
  obj: CatalogObject;
  /** Distance from the scope; set only when sorting by "near" with a pointing. */
  sepDeg: number | null;
}

/**
 * Objects passing the filters and above the altitude threshold, sorted.
 * "near" sorts by distance from `scope`; without a pointing it falls back
 * to highest first.
 */
export function tonightRows(
  objects: CatalogObject[],
  filters: CatalogFilterState,
  location: Location,
  evalAt: Date,
  sortKey: SortKey,
  scope: SkyPoint | null = null,
): TonightRow[] {
  const near = sortKey === "near" && scope !== null;
  const rows: TonightRow[] = [];
  for (const obj of objects) {
    if (!filters.equipment.has(obj.minEquipment)) continue;
    if (!filters.lp.has(obj.lpTolerance)) continue;
    if (!filters.reward.has(obj.visualReward)) continue;
    const item = buddyItem(obj);
    if (!item) continue;
    const { altDeg, azDeg } = altAzFromRaDec({
      raHours: item.ra_deg / 15,
      decDeg: item.dec_deg,
      latDeg: location.latitude,
      lonDeg: location.longitude,
      date: evalAt,
    });
    if (altDeg < ALT_THRESHOLD_DEG) continue;
    const sepDeg = near
      ? angularSepDeg(scope.ra_deg, scope.dec_deg, item.ra_deg, item.dec_deg)
      : null;
    rows.push({ item, altDeg, azDeg, obj, sepDeg });
  }
  rows.sort((a, b) => {
    switch (sortKey) {
      case "near":
        if (a.sepDeg !== null && b.sepDeg !== null) return a.sepDeg - b.sepDeg;
        return b.altDeg - a.altDeg;
      case "type":
        return typeLabel(a.obj).localeCompare(typeLabel(b.obj)) ||
          a.obj.name.localeCompare(b.obj.name);
      case "mag":
        return (a.obj.magnitude ?? Infinity) - (b.obj.magnitude ?? Infinity);
      case "alt":
        return b.altDeg - a.altDeg;
    }
  });
  return rows;
}
