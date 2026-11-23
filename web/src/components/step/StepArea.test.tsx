import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { rememberTargetMagnitude } from "@/components/catalog/targetMagnitude";
import { StepArea } from "./StepArea";
import { payload } from "@/lib/testPayload";
import type { ControlDescriptor } from "@/lib/types";

const controls: ControlDescriptor[] = [
  { id: "exposure", label: "Exposure", min: 1, max: 5000, step: 1, cur: 1000, unit: "100us" },
  { id: "gain", label: "Gain", min: 0, max: 100, step: 1, cur: 40 },
];

function section(container: HTMLElement) {
  return container.querySelector("[data-section]")?.getAttribute("data-section");
}

describe("StepArea", () => {
  it("SETUP: progress and a Next action; the sliders live with the frame", () => {
    const { container } = render(<StepArea state={payload({ controls })} />);
    expect(section(container)).toBe("setup");
    expect(screen.getByText(/Step 1 of 4/)).toBeInTheDocument();
    expect(screen.getByText(/small, sharp dots/i)).toBeInTheDocument();
    expect(screen.queryByText("Exposure")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^next$/i })).toBeEnabled();
  });

  it("SETUP without a camera: Next is disabled and a retry is offered", () => {
    render(<StepArea state={payload({ camera: { ...payload().camera, connected: false } })} />);
    expect(screen.getByRole("button", { name: /^next$/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("SYNC: Sync action, previous calibration when there is one", () => {
    render(<StepArea state={payload({ state: "SYNC", has_calibration: true })} />);
    expect(screen.getByText(/Pick any bright star/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^sync$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /use previous calibration/i })).toBeInTheDocument();
  });

  it("SYNC_CONFIRM: candidate rows, Confirm and Re-solve", () => {
    const sync = {
      in_progress: false,
      selected_idx: 4,
      error: null,
      candidates: [
        { idx: 4, name: "Vega", ra_deg: 279, dec_deg: 38, magnitude: 0, pixel_x: 1, pixel_y: 1 },
        { idx: 7, name: "Deneb", ra_deg: 310, dec_deg: 45, magnitude: 1.3, pixel_x: 2, pixel_y: 2 },
      ],
    };
    render(<StepArea state={payload({ state: "SYNC_CONFIRM", sync })} />);
    expect(screen.getByRole("button", { name: /Vega/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^confirm$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /re-solve/i })).toBeInTheDocument();
  });

  it("SYNC_CONFIRM: names catalogue stars, keeps numbers for unnamed ones", async () => {
    const sync = {
      in_progress: false,
      selected_idx: 0,
      error: null,
      candidates: [
        { idx: 0, name: "Star #1", ra_deg: 279.2346, dec_deg: 38.7837, magnitude: 0, pixel_x: 1, pixel_y: 1 },
        { idx: 1, name: "Star #2", ra_deg: 10.0, dec_deg: -89.5, magnitude: 6, pixel_x: 2, pixel_y: 2 },
      ],
    };
    render(<StepArea state={payload({ state: "SYNC_CONFIRM", sync })} />);
    expect(await screen.findByText("Vega")).toBeInTheDocument();
    expect(screen.getByText("α Lyr")).toBeInTheDocument();
    expect(screen.getByText("Star #2")).toBeInTheDocument();
  });

  it("TRACKING: target readout and an always-open sky view, no camera panel", () => {
    const nav = {
      active: true, target_name: "M 31", target_ra_deg: 10.68, target_dec_deg: 41.27,
      separation_deg: 3.21, direction_text: "Push up and left", in_fov: false,
      pixel_x: null, pixel_y: null, camera_angle_deg: null,
      edge_x: null, edge_y: null, edge_angle_deg: null, mount: null,
    };
    const { container } = render(
      <StepArea
        state={payload({
          state: "TRACKING",
          controls,
          nav,
          pointing: { ...payload().pointing, valid: true, ra_deg: 10, dec_deg: 40, solve_age_s: 0.2 },
        })}
      />,
    );
    expect(section(container)).toBe("tracking");
    expect(screen.getByText("M 31")).toBeInTheDocument();
    expect(screen.getByText("3.2°")).toBeInTheDocument();
    expect(screen.getByText("Push up and left")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /clear/i })).toBeInTheDocument();
    expect(screen.queryByText(/Step \d of 4/)).not.toBeInTheDocument();
    // The dome is shown, with no toggle; the sliders are not here.
    expect(screen.getByLabelText("Sky view")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /sky view/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /camera/i })).not.toBeInTheDocument();
    expect(screen.queryByText("Exposure")).not.toBeInTheDocument();
    expect(screen.queryByText("Matches")).not.toBeInTheDocument();
  });

  it("TRACKING: shows the magnitude this device sent with the target", () => {
    const nav = {
      active: true, target_name: "M 31", target_ra_deg: 10.68, target_dec_deg: 41.27,
      separation_deg: 3.21, direction_text: "", in_fov: false,
      pixel_x: null, pixel_y: null, camera_angle_deg: null,
      edge_x: null, edge_y: null, edge_angle_deg: null, mount: null,
    };
    const state = payload({ state: "TRACKING", nav });
    rememberTargetMagnitude(10.68, 41.27, 3.44);
    const { unmount } = render(<StepArea state={state} />);
    expect(screen.getByText("3.4")).toBeInTheDocument();
    unmount();
    // Another target (e.g. from SkySafari): no magnitude, nothing shown.
    rememberTargetMagnitude(100, 20, 5);
    render(<StepArea state={state} />);
    expect(screen.queryByText(/Magnitude/)).not.toBeInTheDocument();
    rememberTargetMagnitude(0, 0, undefined);
  });

  it("TRACKING without a target points at the list", () => {
    render(<StepArea state={payload({ state: "TRACKING" })} />);
    expect(screen.getByText("No target")).toBeInTheDocument();
  });

  it("ERROR: camera lost with a retry, no restart", () => {
    const { container } = render(<StepArea state={payload({ state: "ERROR" })} />);
    expect(section(container)).toBe("camera-trouble");
    expect(screen.getByText(/Camera lost/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
    expect(screen.queryByText(/restart/i)).not.toBeInTheDocument();
  });

  it("RECONNECTING: says so", () => {
    render(<StepArea state={payload({ state: "RECONNECTING" })} />);
    expect(screen.getByText(/Reconnecting to the camera/i)).toBeInTheDocument();
  });
});
