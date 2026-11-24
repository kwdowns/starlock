import { describe, expect, it } from "vitest";
import {
  CLEAR_HORIZON,
  DEFAULT_HORIZON,
  bandOf,
  horizonFrom,
  isVisible,
  sectorOf,
  withCell,
} from "./horizon";

describe("sectorOf", () => {
  it("centres sector 0 on north, spanning ±11.25°", () => {
    expect(sectorOf(0)).toBe(0);
    expect(sectorOf(11.249)).toBe(0);
    expect(sectorOf(11.25)).toBe(1);
    expect(sectorOf(-11.25)).toBe(0);
    expect(sectorOf(348.75)).toBe(0);
    expect(sectorOf(348.74)).toBe(15);
    expect(sectorOf(359.9)).toBe(0);
  });

  it("names the cardinal points and wraps any range of degrees", () => {
    expect(sectorOf(90)).toBe(4);
    expect(sectorOf(180)).toBe(8);
    expect(sectorOf(270)).toBe(12);
    expect(sectorOf(720 + 22.5)).toBe(1);
    expect(sectorOf(-90)).toBe(12);
  });
});

describe("bandOf", () => {
  it("is 10° per band, with 80–90° (and 90° itself) in band 8", () => {
    expect(bandOf(0)).toBe(0);
    expect(bandOf(9.99)).toBe(0);
    expect(bandOf(10)).toBe(1);
    expect(bandOf(79.99)).toBe(7);
    expect(bandOf(80)).toBe(8);
    expect(bandOf(90)).toBe(8);
  });
});

describe("isVisible", () => {
  it("the default hides everything below 20°", () => {
    expect(isVisible(19.9, 45, DEFAULT_HORIZON)).toBe(false);
    expect(isVisible(20, 45, DEFAULT_HORIZON)).toBe(true);
    expect(isVisible(90, 0, DEFAULT_HORIZON)).toBe(true);
  });

  it("never shows anything below 0°, even with nothing hidden", () => {
    expect(isVisible(-0.1, 0, CLEAR_HORIZON)).toBe(false);
    expect(isVisible(0, 0, CLEAR_HORIZON)).toBe(true);
    expect(isVisible(NaN, 0, CLEAR_HORIZON)).toBe(false);
  });

  it("hides only the painted cell, with sector edges at ±11.25°", () => {
    const mask = withCell(CLEAR_HORIZON, 1, 3, true); // NNE, 30–40°
    expect(isVisible(35, 22.5, mask)).toBe(false);
    expect(isVisible(35, 11.25, mask)).toBe(false);
    expect(isVisible(35, 11.2, mask)).toBe(true);
    expect(isVisible(35, 33.74, mask)).toBe(false);
    expect(isVisible(35, 33.75, mask)).toBe(true);
    expect(isVisible(29.9, 22.5, mask)).toBe(true);
    expect(isVisible(40, 22.5, mask)).toBe(true);
  });

  it("band 8 covers the zenith", () => {
    const mask = withCell(CLEAR_HORIZON, 0, 8, true);
    expect(isVisible(90, 0, mask)).toBe(false);
    expect(isVisible(85, 5, mask)).toBe(false);
    expect(isVisible(85, 90, mask)).toBe(true);
  });

  it("wraps sector 0 across north", () => {
    const mask = withCell(CLEAR_HORIZON, 0, 0, true);
    expect(isVisible(5, 355, mask)).toBe(false);
    expect(isVisible(5, 5, mask)).toBe(false);
    expect(isVisible(5, 348.7, mask)).toBe(true);
  });
});

describe("withCell / horizonFrom", () => {
  it("sets and clears one bit without touching the others", () => {
    const hidden = withCell(DEFAULT_HORIZON, 4, 8, true);
    expect(hidden[4]).toBe(3 | 256);
    expect(withCell(hidden, 4, 0, false)[4]).toBe(2 | 256);
    expect(DEFAULT_HORIZON[4]).toBe(3);
  });

  it("falls back to the default for a missing or malformed mask", () => {
    expect(horizonFrom(undefined)).toBe(DEFAULT_HORIZON);
    expect(horizonFrom([1, 2, 3])).toBe(DEFAULT_HORIZON);
    expect(horizonFrom(Array(16).fill(512))).toBe(DEFAULT_HORIZON);
    const ok = Array(16).fill(7);
    expect(horizonFrom(ok)).toBe(ok);
  });
});
