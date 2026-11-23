import { describe, expect, it } from "vitest";
import { placeLabels } from "./labelPlacement";

const target = { id: "target", x: 100, y: 100, w: 90, h: 12 };
const scope = { id: "scope", x: 100, y: 100, w: 36, h: 12 };

describe("placeLabels", () => {
  it("puts a lone marker label above its dot", () => {
    expect(placeLabels([target], [])).toEqual({ target: { visible: true, side: "above" } });
  });

  it("hides the scope label when it is on the target", () => {
    const r = placeLabels([target, { ...scope, x: 104, y: 103 }], []);
    expect(r.target.visible).toBe(true);
    expect(r.scope.visible).toBe(false);
  });

  it("moves the scope label below when the dots are close but distinct", () => {
    const r = placeLabels([target, { ...scope, x: 100, y: 120 }], []);
    expect(r.target).toEqual({ visible: true, side: "above" });
    expect(r.scope).toEqual({ visible: true, side: "below" });
  });

  it("keeps both above when they are far apart", () => {
    const r = placeLabels([target, { ...scope, x: 300, y: 100 }], []);
    expect(r.scope.side).toBe("above");
    expect(r.scope.visible).toBe(true);
  });

  it("hides a label that fits neither above nor below", () => {
    const blocker = { id: "a", x: 100, y: 100, w: 200, h: 12 };
    // Scope dot 15px below: its above-box hits the dot/label, its below-box
    // lands on a third marker's label.
    const third = { id: "c", x: 100, y: 150, w: 200, h: 12 };
    const r = placeLabels([blocker, third, { ...scope, id: "b", x: 100, y: 118 }], []);
    expect(r.b.visible).toBe(false);
  });

  it("hides the zenith label under a marker label", () => {
    const r = placeLabels([target], [{ id: "Z", x: 100, y: 82, w: 8, h: 12 }]);
    expect(r.Z.visible).toBe(false);
  });

  it("hides a compass label under a marker dot", () => {
    const r = placeLabels([target], [{ id: "N", x: 102, y: 104, w: 10, h: 12 }]);
    expect(r.N.visible).toBe(false);
  });

  it("keeps compass labels that are clear", () => {
    const r = placeLabels([target], [{ id: "N", x: 300, y: 300, w: 10, h: 12 }]);
    expect(r.N.visible).toBe(true);
  });
});
