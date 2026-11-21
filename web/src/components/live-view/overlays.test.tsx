import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AxesOverlay } from "./AxesOverlay";
import { NavOverlay } from "./NavOverlay";
import { payload } from "@/lib/testPayload";
import type { EnginePayload, NavData } from "@/lib/types";

const tracking = (over: Partial<EnginePayload> = {}) =>
  payload({
    state: "TRACKING",
    pointing: { ...payload().pointing, valid: true },
    ...over,
  });

function labelPos(container: HTMLElement, text: string) {
  const el = [...container.querySelectorAll("text")].find((t) => t.textContent === text);
  if (!el) throw new Error(`no label ${text}`);
  return { x: Number(el.getAttribute("x")), y: Number(el.getAttribute("y")) };
}

function renderSvg(node: React.ReactNode) {
  return render(<svg>{node}</svg>).container;
}

describe("AxesOverlay", () => {
  it("puts UP above and RIGHT right of the origin for an upright camera", () => {
    const c = renderSvg(<AxesOverlay state={tracking({ finder_rotation: 0 })} />);
    expect(labelPos(c, "UP").y).toBeLessThan(360);
    expect(labelPos(c, "UP").x).toBeCloseTo(640);
    expect(labelPos(c, "RIGHT").x).toBeGreaterThan(640);
    expect(labelPos(c, "LEFT").x).toBeLessThan(640);
    expect(labelPos(c, "DOWN").y).toBeGreaterThan(360);
  });

  it("follows a calibrated rotation (mount-up at image-right)", () => {
    const c = renderSvg(<AxesOverlay state={tracking({ finder_rotation: 90 })} />);
    expect(labelPos(c, "UP").x).toBeGreaterThan(640);
    expect(labelPos(c, "RIGHT").y).toBeGreaterThan(360); // clockwise from up
  });

  it("uses solve-derived axes, with compass letters in equatorial mode", () => {
    const c = renderSvg(
      <AxesOverlay
        state={tracking({
          mount: { mode: "eq", needs_location: false, axes: { axis1_angle_deg: 270, axis2_angle_deg: 0 } },
        })}
      />,
    );
    expect(labelPos(c, "N").y).toBeLessThan(360);
    expect(labelPos(c, "E").x).toBeLessThan(640); // east on the left, as seen
  });
});

describe("NavOverlay mount arrows", () => {
  const nav: NavData = {
    active: true, target_name: null, target_ra_deg: 0, target_dec_deg: 0,
    separation_deg: 5, direction_text: "", in_fov: false, pixel_x: null, pixel_y: null,
    camera_angle_deg: null, edge_x: 1200, edge_y: 360, edge_angle_deg: 90,
    mount: {
      axis1_deg: -12, axis2_deg: 3, axis1_angle_deg: 90, axis2_angle_deg: 0,
      near_pole: false, pointing_alt_deg: 40, target_alt_deg: 43,
    },
  };

  it("draws one labelled arrow per axis, pointing the way to push", () => {
    const c = renderSvg(<NavOverlay state={tracking({ nav })} />);
    const turn = labelPos(c, "Turn left 12.0°");
    const raise = labelPos(c, "Raise 3.0°");
    // axis1 + is image-right, and the move is negative → arrow goes left.
    expect(turn.x).toBeLessThan(640);
    // axis2 + is image-up, and the move is positive → arrow goes up.
    expect(raise.y).toBeLessThan(360);
  });

  it("drops an axis that is already lined up", () => {
    const c = renderSvg(
      <NavOverlay state={tracking({ nav: { ...nav, mount: { ...nav.mount!, axis2_deg: 0.01 } } })} />,
    );
    expect(c.textContent).toContain("Turn left");
    expect(c.textContent).not.toContain("Raise");
  });
});
