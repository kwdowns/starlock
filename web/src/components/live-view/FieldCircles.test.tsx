import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { CameraSettings } from "@/components/controls/CameraSettings";
import { payload, sampleObserving } from "@/lib/testPayload";
import type { EnginePayload } from "@/lib/types";
import { FieldCircles } from "./FieldCircles";
import { LiveView } from "./LiveView";

// 1280 px across 8°: 160 px per degree.
const tracking = (over: Partial<EnginePayload> = {}) =>
  payload({
    state: "TRACKING",
    pointing: { ...payload().pointing, valid: true },
    fov_h_deg: 8,
    origin_x: 600,
    origin_y: 380,
    observing: sampleObserving,
    ...over,
  });

function renderSvg(node: React.ReactNode) {
  return render(<svg>{node}</svg>).container;
}

beforeEach(() => localStorage.clear());
afterEach(cleanup);

describe("FieldCircles", () => {
  it("draws the eyepiece field solid around the scope's aim, labelled with the magnification", () => {
    const c = renderSvg(<FieldCircles state={tracking()} eyepiece finder={false} />);
    const circle = c.querySelector("circle[data-eyepiece]")!;
    expect(circle.getAttribute("cx")).toBe("600");
    expect(circle.getAttribute("cy")).toBe("380");
    // 1.08° field → 0.54° radius × 160 px/°.
    expect(Number(circle.getAttribute("r"))).toBeCloseTo(86.4);
    expect(circle.getAttribute("stroke-width")).toBe("1.5");
    expect(circle.getAttribute("stroke-opacity")).toBe("0.7");
    expect(circle.getAttribute("stroke-dasharray")).toBeNull();
    expect(c.querySelectorAll("circle[data-ring]")).toHaveLength(0);
    const label = c.querySelector("text")!;
    expect(label.textContent).toBe("48×");
    // Upper right of the circle.
    expect(Number(label.getAttribute("x"))).toBeGreaterThan(600);
    expect(Number(label.getAttribute("y"))).toBeLessThan(380);
  });

  it("draws one dashed circle per finder ring", () => {
    const c = renderSvg(<FieldCircles state={tracking()} eyepiece={false} finder />);
    const rings = [...c.querySelectorAll("circle[data-ring]")];
    expect(rings.map((r) => Number(r.getAttribute("r")))).toEqual([40, 160, 320]);
    for (const r of rings) {
      expect(r.getAttribute("stroke-dasharray")).not.toBeNull();
      expect(r.getAttribute("stroke-opacity")).toBe("0.45");
      expect(r.getAttribute("stroke-width")).toBe("1");
    }
    expect(c.querySelector("circle[data-eyepiece]")).toBeNull();
  });

  it("keeps the label inside the frame when the circle is bigger than it", () => {
    const big = tracking({
      observing: { ...sampleObserving, optics: { ...sampleObserving.optics, true_field_deg: 12 } },
    });
    const c = renderSvg(<FieldCircles state={big} eyepiece finder={false} />);
    const label = c.querySelector("text")!;
    expect(Number(label.getAttribute("x"))).toBeLessThan(1280);
    expect(Number(label.getAttribute("y"))).toBeGreaterThan(0);
  });

  it("draws nothing before sync, without optics, or from an older engine", () => {
    expect(renderSvg(<FieldCircles state={tracking({ state: "SETUP" })} eyepiece finder />).querySelector("circle")).toBeNull();
    expect(renderSvg(<FieldCircles state={tracking({ observing: undefined })} eyepiece finder />).querySelector("circle")).toBeNull();
    const none = tracking({
      observing: {
        ...sampleObserving,
        optics: { magnification: null, true_field_deg: null, exit_pupil_mm: null, finder_rings_deg: null },
      },
    });
    expect(renderSvg(<FieldCircles state={none} eyepiece finder />).querySelector("circle")).toBeNull();
  });
});

describe("Field circle switches", () => {
  it("default to eyepiece on, finder off, and the frame follows them", () => {
    const state = tracking();
    const { container } = render(
      <>
        <LiveView state={state} showStars={false} />
        <CameraSettings state={state} />
      </>,
    );
    const eyepiece = screen.getByRole("switch", { name: /Eyepiece field/ });
    const finder = screen.getByRole("switch", { name: /Finder field/ });
    expect(eyepiece).toBeChecked();
    expect(finder).not.toBeChecked();
    expect(container.querySelector("circle[data-eyepiece]")).not.toBeNull();
    expect(container.querySelectorAll("circle[data-ring]")).toHaveLength(0);

    fireEvent.click(finder);
    fireEvent.click(eyepiece);
    expect(container.querySelectorAll("circle[data-ring]")).toHaveLength(3);
    expect(container.querySelector("circle[data-eyepiece]")).toBeNull();
    // Saved on this device.
    expect(localStorage.getItem("starlock.circles.finder")).toBe("on");
    expect(localStorage.getItem("starlock.circles.eyepiece")).toBe("off");
  });

  it("each shows only when the engine sends that field", () => {
    const onlyFinder = tracking({
      observing: {
        ...sampleObserving,
        optics: { magnification: null, true_field_deg: null, exit_pupil_mm: null, finder_rings_deg: [6] },
      },
    });
    render(<CameraSettings state={onlyFinder} />);
    expect(screen.queryByRole("switch", { name: /Eyepiece field/ })).not.toBeInTheDocument();
    expect(screen.getByRole("switch", { name: /Finder field/ })).toBeInTheDocument();
    expect(screen.getByText("The finder's 6° view.")).toBeInTheDocument();
    cleanup();

    render(<CameraSettings state={tracking({ observing: undefined })} />);
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });
});
