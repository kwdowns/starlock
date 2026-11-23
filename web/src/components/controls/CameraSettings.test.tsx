import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { LiveView } from "@/components/live-view/LiveView";
import { payload } from "@/lib/testPayload";
import type { ControlDescriptor, EnginePayload } from "@/lib/types";
import { CameraSettings } from "./CameraSettings";

const controls: ControlDescriptor[] = [
  { id: "exposure", label: "Exposure", min: 1, max: 5000, step: 1, cur: 1000, unit: "100us" },
  { id: "gain", label: "Gain", min: 0, max: 100, step: 1, cur: 40 },
];

function Frame({ state }: { state: EnginePayload }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <LiveView
        state={state}
        showStars={false}
        editOpen={open}
        onToggleEdit={() => setOpen((o) => !o)}
        editId="cam"
      />
      {open && <CameraSettings state={state} id="cam" />}
    </>
  );
}

describe("Camera settings", () => {
  it("the pencil on the frame toggles sliders and solve stats under it", () => {
    const state = payload({
      state: "TRACKING",
      controls,
      pointing: { valid: true, ra_deg: 10, dec_deg: 40, roll_deg: 0, matches: 31, prob: 1e-9, solve_age_s: 0.4 },
    });
    render(<Frame state={state} />);
    const pencil = screen.getByRole("button", { name: "Camera settings" });
    expect(pencil).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Exposure")).not.toBeInTheDocument();

    fireEvent.click(pencil);
    expect(pencil).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Exposure")).toBeInTheDocument();
    expect(screen.getByText("Gain")).toBeInTheDocument();
    expect(screen.getByText("100 ms")).toBeInTheDocument();
    expect(screen.getByText("Matches")).toBeInTheDocument();
    expect(screen.getByText("31")).toBeInTheDocument();
    expect(screen.getByText("Prob")).toBeInTheDocument();
    expect(screen.getByText("0.4 s")).toBeInTheDocument();

    fireEvent.click(pencil);
    expect(screen.queryByText("Exposure")).not.toBeInTheDocument();
  });
});
