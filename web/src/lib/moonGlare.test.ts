import { describe, expect, it } from "vitest";
import { moonGlare, moonGlareText } from "./moonGlare";
import type { SolarBody } from "./solarSystem";

const moon = (lit: number): SolarBody => ({
  id: "moon", name: "Moon", kind: "moon", ra_j2000_deg: 50, dec_j2000_deg: 20,
  magnitude: -11, distance_au: 0.0026, phase_fraction: lit, elongation_deg: 120,
  constellation: "Taurus", near_sun: false,
});
const at = new Date("2026-11-22T06:00:00Z");

describe("moonGlare", () => {
  it("warns near a bright Moon", () => {
    const g = moonGlare({ ra_deg: 56.75, dec_deg: 24.1 }, [moon(0.8)], null, at);
    expect(g).toMatchObject({ kind: "near", litPct: 80 });
    expect(moonGlareText(g!, "Pleiades")).toMatch(/^Pleiades is 7° from the Moon \(80% lit\)/);
  });

  it("stays quiet when far, dim, or for an unknown Moon", () => {
    expect(moonGlare({ ra_deg: 120, dec_deg: 20 }, [moon(0.9)], null, at)).toBeNull();
    expect(moonGlare({ ra_deg: 56.75, dec_deg: 24.1 }, [moon(0.3)], null, at)).toBeNull();
    expect(moonGlare({ ra_deg: 56.75, dec_deg: 24.1 }, [], null, at)).toBeNull();
  });

  it("explains that the Moon itself is hard to solve on", () => {
    expect(moonGlare({ ra_deg: 50, dec_deg: 20, isMoon: true }, [], null, at)).toEqual({ kind: "is-moon" });
  });
});
