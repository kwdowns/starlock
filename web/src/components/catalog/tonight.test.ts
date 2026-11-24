import { describe, expect, it } from "vitest";
import objectsData from "@/data/objects.json";
import type { CatalogObject } from "@/lib/catalogTypes";
import { CLEAR_HORIZON, DEFAULT_HORIZON, SECTOR_COUNT, sectorOf } from "@/lib/horizon";
import { defaultFilters } from "./filterState";
import { tonightRows } from "./tonight";

const objects = objectsData as CatalogObject[];
// Chennai on a dark night, so plenty is up.
const CHENNAI = { latitude: 13.0878, longitude: 80.2785 };
const NIGHT = new Date("2026-10-10T16:00:00Z");

function rows(horizon: readonly number[]) {
  return tonightRows(objects, defaultFilters(), CHENNAI, NIGHT, "alt", null, horizon);
}

describe("tonightRows horizon mask", () => {
  it("defaults to hiding everything below 20°", () => {
    const def = tonightRows(objects, defaultFilters(), CHENNAI, NIGHT, "alt");
    expect(def.length).toBeGreaterThan(5);
    expect(def.every((r) => r.altDeg >= 20)).toBe(true);
    expect(rows(DEFAULT_HORIZON)).toEqual(def);
  });

  it("with nothing hidden, lists objects down to 0° but never below", () => {
    const clear = rows(CLEAR_HORIZON);
    expect(clear.length).toBeGreaterThan(rows(DEFAULT_HORIZON).length);
    expect(clear.some((r) => r.altDeg < 20)).toBe(true);
    expect(clear.every((r) => r.altDeg >= 0)).toBe(true);
  });

  it("skips objects behind a hidden sector", () => {
    const clear = rows(CLEAR_HORIZON);
    const sector = sectorOf(clear[0].azDeg);
    const mask = Array<number>(SECTOR_COUNT).fill(0);
    mask[sector] = 511;
    const masked = rows(mask);
    expect(masked.some((r) => sectorOf(r.azDeg) === sector)).toBe(false);
    expect(masked.length).toBe(clear.filter((r) => sectorOf(r.azDeg) !== sector).length);
  });

  it("hides everything when every cell is hidden", () => {
    expect(rows(Array<number>(SECTOR_COUNT).fill(511))).toEqual([]);
  });
});
