import { describe, expect, it } from "vitest";
import type { MountModel } from "./types";
import { clockLine, formatClockOffset, mountModelLines } from "./mountModel";

const BASE: MountModel = {
  state: "collecting",
  samples: 5,
  needed: 8,
  hint: null,
  tilt_deg: null,
  low_side_az_deg: null,
  polar_alt_error_deg: null,
  polar_az_error_deg: null,
  rms_deg: null,
  applied: false,
};

describe("clock line", () => {
  it("formats the offset by size", () => {
    expect(formatClockOffset(42.4)).toBe("42 s");
    expect(formatClockOffset(-150)).toBe("2 min");
    expect(formatClockOffset(3 * 3600 + 12 * 60 + 5)).toBe("3 h 12 min");
    expect(formatClockOffset(2 * 86400 + 5 * 3600 + 59)).toBe("2 d 5 h");
  });

  it("says behind for a positive offset, ahead otherwise", () => {
    expect(clockLine({ source: "client", offset_s: 11_520 })).toBe(
      "Pi clock set from this device (it was 3 h 12 min behind).",
    );
    expect(clockLine({ source: "client", offset_s: -30 })).toBe(
      "Pi clock set from this device (it was 30 s ahead).",
    );
    expect(clockLine({ source: "system", offset_s: 0 })).toBe("Pi clock is correct.");
    expect(clockLine(undefined)).toBeNull();
  });
});

describe("mount model lines", () => {
  it("off needs a location", () => {
    expect(mountModelLines({ ...BASE, state: "off", samples: 0 }, "altaz")).toEqual([
      "Set your location so Starlock can learn how your mount sits.",
    ]);
  });

  it("collecting gives progress and the hint for the mount type", () => {
    expect(mountModelLines(BASE, "altaz")).toEqual([
      "Learning your mount: 5 of 8 positions.",
      "Keep pointing at different heights and directions.",
    ]);
    expect(mountModelLines({ ...BASE, hint: "turn" }, "altaz")[1]).toBe("Next, turn the base to a new direction.");
    expect(mountModelLines({ ...BASE, hint: "tilt" }, "altaz")[1]).toBe("Next, raise or lower the tube.");
    expect(mountModelLines({ ...BASE, hint: "turn" }, "eq")[1]).toBe("Next, swing to a new right ascension.");
    expect(mountModelLines({ ...BASE, hint: "tilt" }, "eq")[1]).toBe("Next, move to a new declination.");
  });

  it("ready alt-az: level within 0.2°, else the tilt and its low side", () => {
    const ready = { ...BASE, state: "ready" as const, applied: true, samples: 12 };
    expect(mountModelLines({ ...ready, tilt_deg: 0.15, low_side_az_deg: 10 }, "altaz")).toEqual([
      "The base is level (within 0.2°).",
    ]);
    expect(mountModelLines({ ...ready, tilt_deg: 1.21, low_side_az_deg: 47 }, "altaz")).toEqual([
      "The base tilts 1.2°, low side NE. Guidance corrects for it.",
    ]);
  });

  it("ready equatorial: each error with its own sign word, small ones left out", () => {
    const ready = { ...BASE, state: "ready" as const, applied: true, samples: 12 };
    const eq = (alt: number, az: number) =>
      mountModelLines({ ...ready, polar_alt_error_deg: alt, polar_az_error_deg: az }, "eq")[0];
    expect(eq(-0.8, -0.5)).toBe(
      "The polar axis is 0.8° too low and 0.5° west of the pole. Guidance corrects for it.",
    );
    expect(eq(0.3, 0.05)).toBe("The polar axis is 0.3° too high. Guidance corrects for it.");
    expect(eq(0.02, 1.4)).toBe("The polar axis is 1.4° east of the pole. Guidance corrects for it.");
    expect(eq(0.05, -0.09)).toBe("The polar axis is on the pole (within 0.1°).");
  });
});
