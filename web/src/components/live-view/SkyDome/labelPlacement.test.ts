import { describe, expect, it } from "vitest";
import { placeLabels, segmentHitsRect } from "./labelPlacement";

const B = { w: 400, h: 300 };
const target = { id: "target", x: 200, y: 150, radius: 8, w: 90, h: 12 };
const scope = { id: "scope", x: 200, y: 150, radius: 5, w: 36, h: 12 };

describe("placeLabels", () => {
  it("puts a lone marker label above its dot", () => {
    const r = placeLabels([target], [], B);
    expect(r.target.visible).toBe(true);
    expect(r.target.dx).toBe(0);
    expect(r.target.dy).toBeLessThan(0);
  });

  it("drops the scope label when the markers merge", () => {
    const r = placeLabels([target, { ...scope, x: 204, y: 152 }], [], B);
    expect(r.target.visible).toBe(true);
    expect(r.scope.visible).toBe(false);
  });

  it("moves the scope label away from the target label", () => {
    const r = placeLabels([target, { ...scope, y: 175 }], [], B);
    expect(r.target.dy).toBeLessThan(0);
    expect(r.scope.visible).toBe(true);
    expect(r.scope.dy).toBeGreaterThan(0);
  });

  it("goes below when above would leave the canvas", () => {
    const r = placeLabels([{ ...target, y: 10 }], [], B);
    expect(r.target.dy).toBeGreaterThan(0);
  });

  it("goes right when above and below leave the canvas", () => {
    const r = placeLabels([{ ...target, w: 60, x: 40, y: 10 }], [], { w: 400, h: 20 });
    expect(r.target.dx).toBeGreaterThan(0);
    expect(r.target.dy).toBe(0);
  });

  it("goes left when above, below and right are blocked", () => {
    const r = placeLabels([{ ...target, w: 60, x: 370, y: 10 }], [], { w: 400, h: 20 });
    expect(r.target.dx).toBeLessThan(0);
    expect(r.target.dy).toBe(0);
  });

  it("keeps a marker label off its own shaft", () => {
    // Scope dot at the top of a shaft running straight down; the target's
    // label already takes the spot above, so below would sit on the shaft.
    const shaft = { x1: 200, y1: 175, x2: 200, y2: 290 };
    const r = placeLabels([target, { ...scope, y: 175 }], [], B, [shaft]);
    expect(r.scope.visible).toBe(true);
    expect(r.scope.dx).not.toBe(0);
  });

  it("never hides a marker label, even when nothing fits", () => {
    const r = placeLabels([{ ...target, w: 500 }], [], { w: 100, h: 20 });
    expect(r.target.visible).toBe(true);
  });

  it("hides a compass label under a marker label or dot", () => {
    const r = placeLabels(
      [target],
      [
        { id: "Z", x: 200, y: 128, w: 8, h: 12 },
        { id: "N", x: 202, y: 152, w: 10, h: 12 },
      ],
      B,
    );
    expect(r.Z.visible).toBe(false);
    expect(r.N.visible).toBe(false);
  });

  it("hides a compass label outside the canvas", () => {
    expect(placeLabels([], [{ id: "N", x: 2, y: 100, w: 10, h: 12 }], B).N.visible).toBe(false);
  });

  it("keeps a clear compass label", () => {
    expect(placeLabels([target], [{ id: "N", x: 50, y: 250, w: 10, h: 12 }], B).N.visible).toBe(true);
  });

  it("hides a compass label sitting on a line segment", () => {
    const seg = [{ x1: 0, y1: 0, x2: 400, y2: 300 }];
    const on = { id: "SE", x: 200, y: 150, w: 16, h: 12 };
    expect(placeLabels([], [on], B, seg).SE.visible).toBe(false);
    expect(placeLabels([], [{ ...on, y: 250 }], B, seg).SE.visible).toBe(true);
  });
});

describe("segmentHitsRect", () => {
  const r = { l: 10, t: 10, r: 20, b: 20 };
  it("detects crossing, inside and miss", () => {
    expect(segmentHitsRect({ x1: 0, y1: 15, x2: 30, y2: 15 }, r)).toBe(true);
    expect(segmentHitsRect({ x1: 12, y1: 12, x2: 14, y2: 14 }, r)).toBe(true);
    expect(segmentHitsRect({ x1: 0, y1: 0, x2: 30, y2: 5 }, r)).toBe(false);
    expect(segmentHitsRect({ x1: 0, y1: 25, x2: 9, y2: 0 }, r)).toBe(false);
  });
});
