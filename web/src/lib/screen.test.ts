import { describe, expect, it } from "vitest";
import {
  formatDec,
  formatDistance,
  formatMountMove,
  formatRa,
  hasNoStars,
  isSetupPhase,
  mountDeltas,
  statusBadgeFor,
  stepIndexFor,
} from "./screen";
import { payload } from "./testPayload";

describe("stepIndexFor", () => {
  it("maps engine states onto the four wizard steps", () => {
    expect(stepIndexFor("SETUP")).toBe(0);
    expect(stepIndexFor("SYNC")).toBe(1);
    expect(stepIndexFor("SYNC_CONFIRM")).toBe(1);
    expect(stepIndexFor("CALIBRATE")).toBe(2);
    expect(stepIndexFor("WARMING_UP")).toBe(3);
    expect(stepIndexFor("TRACKING")).toBe(3);
  });
  it("has no step for camera trouble", () => {
    expect(stepIndexFor("RECONNECTING")).toBeNull();
    expect(stepIndexFor("ERROR")).toBeNull();
  });
});

describe("isSetupPhase", () => {
  it("is true up to warming up, false once tracking or in trouble", () => {
    for (const s of ["SETUP", "SYNC", "SYNC_CONFIRM", "CALIBRATE", "WARMING_UP"] as const) {
      expect(isSetupPhase(s)).toBe(true);
    }
    for (const s of ["TRACKING", "RECONNECTING", "ERROR"] as const) {
      expect(isSetupPhase(s)).toBe(false);
    }
  });
});

describe("statusBadgeFor", () => {
  it("is solid only for a live lock", () => {
    const lock = statusBadgeFor(
      payload({ state: "TRACKING", pointing: { ...payload().pointing, valid: true } }),
    );
    expect(lock).toEqual({ label: "Locked", variant: "solid" });
    const lost = statusBadgeFor(payload({ state: "TRACKING" }));
    expect(lost.variant).toBe("outline");
    expect(lost.alert).toBe(true);
    for (const s of ["SETUP", "SYNC", "CALIBRATE", "WARMING_UP", "ERROR", "RECONNECTING"] as const) {
      expect(statusBadgeFor(payload({ state: s })).variant).not.toBe("solid");
    }
  });
  it("flags a missing camera during setup", () => {
    const b = statusBadgeFor(payload({ camera: { ...payload().camera, connected: false } }));
    expect(b.label).toBe("No camera");
    expect(b.alert).toBe(true);
  });
});

describe("hasNoStars", () => {
  it("needs a solving state and three failures", () => {
    expect(hasNoStars(payload({ state: "TRACKING", failures: 3 }))).toBe(true);
    expect(hasNoStars(payload({ state: "TRACKING", failures: 2 }))).toBe(false);
    expect(hasNoStars(payload({ state: "SETUP", failures: 9 }))).toBe(false);
  });
});

describe("formatting", () => {
  it("formats RA and Dec", () => {
    expect(formatRa(0)).toBe("0h 00m 00.0s");
    expect(formatRa(83.8221)).toBe("5h 35m 17.3s");
    expect(formatDec(-5.391)).toBe("−5° 23′ 28″");
    expect(formatDec(45.998)).toBe("+45° 59′ 53″");
  });
  it("carries rounding into the next unit", () => {
    expect(formatRa(359.99999)).toBe("0h 00m 00.0s");
    expect(formatDec(9.99999)).toBe("+10° 00′ 00″");
  });
  it("formats distance in degrees all the way down", () => {
    expect(formatDistance(null)).toBe("—");
    expect(formatDistance(12.34)).toBe("12.3°");
    expect(formatDistance(1.04)).toBe("1.0°");
    expect(formatDistance(0.99)).toBe("0.99°");
    expect(formatDistance(0.5)).toBe("0.50°");
    expect(formatDistance(0.123)).toBe("0.12°");
  });
  it("formats mount moves per mode", () => {
    const m = {
      axis1_deg: -12.04, axis2_deg: 0.5, axis1_angle_deg: 0, axis2_angle_deg: 0,
      near_pole: false, pointing_alt_deg: 40, target_alt_deg: 40.5,
    };
    expect(formatMountMove("altaz", m)).toBe("Turn left 12.0° · Raise 0.50°");
    expect(formatMountMove("eq", { ...m, axis1_deg: 3, axis2_deg: -2 })).toBe(
      "RA east 3.0° · Dec south 2.0°",
    );
  });
});

describe("mountDeltas", () => {
  const geom = { origin_x: 640, origin_y: 360, fov_h_deg: 10, image_w: 1280, finder_rotation: 0 };
  it("is right/up in image axes with no finder rotation", () => {
    const d = mountDeltas(geom, 740, 360);
    expect(d.right).toBeGreaterThan(0);
    expect(d.up).toBeCloseTo(0);
  });
  it("undoes a 90° finder rotation (mount-up is image-right)", () => {
    const d = mountDeltas({ ...geom, finder_rotation: 90 }, 740, 360);
    expect(d.right).toBeCloseTo(0);
    expect(d.up).toBeGreaterThan(0);
    // Image-down is then mount-right.
    const below = mountDeltas({ ...geom, finder_rotation: 90 }, 640, 460);
    expect(below.right).toBeGreaterThan(0);
    expect(below.up).toBeCloseTo(0);
  });
});
