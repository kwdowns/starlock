import { describe, expect, it } from "vitest";
import { solarItem } from "@/components/catalog/items";
import type { SolarBody } from "./solarSystem";

const jupiter: SolarBody = {
  id: "jupiter", name: "Jupiter", kind: "planet", ra_j2000_deg: 148.5, dec_j2000_deg: 13.6,
  magnitude: -2.2, distance_au: 5.1, phase_fraction: 0.99, elongation_deg: 94,
  constellation: "Leo", near_sun: false,
};

describe("solarItem", () => {
  it("makes a target row", () => {
    const item = solarItem(jupiter);
    expect(item.key).toBe("solar:jupiter");
    expect(item.title).toBe("Jupiter");
    expect(item.subtitle).toBe("Planet · mag -2.2 · Leo");
    expect([item.ra_deg, item.dec_deg]).toEqual([148.5, 13.6]);
  });

  it("warns near the Sun", () => {
    expect(solarItem({ ...jupiter, near_sun: true }).subtitle).toContain("too close to the Sun");
  });
});
