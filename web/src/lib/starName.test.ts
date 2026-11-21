import { describe, expect, it } from "vitest";
import stars from "@/data/hyg-bright.json";
import type { StarEntry } from "./catalogTypes";
import { starName, starNameAt } from "./starName";

const catalogue = stars as Omit<StarEntry, "source">[];
const star = (id: string, aliases: string[]) => ({
  id, aliases, ra_deg: 0, dec_deg: 0, mag: 1, spectral: null, constellation: null,
});

describe("starName", () => {
  it("prefers the proper name, keeping the Bayer designation", () => {
    expect(starName(star("Vega", ["Vega", "α Lyr", "3 Lyr", "HIP 91262"]))).toEqual({
      name: "Vega", designation: "α Lyr",
    });
  });
  it("uses Bayer, then Flamsteed, when there is no proper name", () => {
    expect(starName(star("τ Phe", ["τ Phe", "HIP 88"]))).toEqual({ name: "τ Phe", designation: null });
    expect(starName(star("31 Ori", ["31 Ori", "HIP 25737"]))).toEqual({ name: "31 Ori", designation: null });
  });
  it("gives no name for catalogue numbers only", () => {
    expect(starName(star("HIP 26199", ["HIP 26199", "HD 36960", "HR 1887"]))).toBeNull();
    expect(starName(star("Gl 194B", ["Gl 194B"]))).toBeNull();
  });
});

describe("starNameAt", () => {
  // Positions as the plate solver (Gaia) reports them for the sample images.
  it("names solved stars a few arcseconds from the catalogue position", () => {
    expect(starNameAt(279.2346, 38.7837, catalogue)?.name).toBe("Vega");
    const alnilam = catalogue.find((s) => s.id === "Alnilam")!;
    expect(starNameAt(alnilam.ra_deg + 0.002, alnilam.dec_deg - 0.001, catalogue)).toEqual({
      name: "Alnilam", designation: "ε Ori",
    });
  });
  it("names nothing well away from any catalogue star", () => {
    const vega = catalogue.find((s) => s.id === "Vega")!;
    expect(starNameAt(vega.ra_deg, vega.dec_deg + 0.1, catalogue)?.name).not.toBe("Vega");
  });
});
