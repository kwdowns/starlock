import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { payload } from "@/lib/testPayload";
import type { NavData } from "@/lib/types";
import { TrackingPanel } from "./TrackingPanel";

const nav = (sep: number): NavData => ({
  active: true, mount: null, target_name: "Andromeda Galaxy", target_ra_deg: 10.68,
  target_dec_deg: 41.27, separation_deg: sep, direction_text: "", in_fov: true,
  pixel_x: 640, pixel_y: 360, camera_angle_deg: 0, edge_x: null, edge_y: null,
  edge_angle_deg: null, on_target: true, on_target_deg: 0.95,
});
const tracking = (sep: number) => payload({
  state: "TRACKING",
  pointing: { valid: true, ra_deg: 10.6, dec_deg: 41.0, roll_deg: 0, matches: 30, prob: 1e-9, solve_age_s: 0.2 },
  nav: nav(sep),
});

afterEach(() => vi.restoreAllMocks());

describe("Recenter on target", () => {
  it("asks first, then re-aims the alignment", async () => {
    const recenter = vi.spyOn(api, "recenter").mockResolvedValue({ shift_deg: 0.33 });
    render(<TrackingPanel state={tracking(0.33)} />);
    fireEvent.click(screen.getByRole("button", { name: /recenter on target/i }));
    expect(screen.getByText(/Is Andromeda Galaxy centred in the eyepiece/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /it's centred/i }));
    await waitFor(() => expect(recenter).toHaveBeenCalledOnce());
    expect(await screen.findByText(/alignment moved 0.33°/)).toBeInTheDocument();
  });

  it("shows the engine's reason when it refuses", async () => {
    vi.spyOn(api, "recenter").mockRejectedValue(new Error("Waiting for a solve. Try again in a moment."));
    render(<TrackingPanel state={tracking(0.33)} />);
    fireEvent.click(screen.getByRole("button", { name: /recenter on target/i }));
    fireEvent.click(screen.getByRole("button", { name: /it's centred/i }));
    expect(await screen.findByText(/Waiting for a solve/)).toBeInTheDocument();
  });

  it("isn't offered when the target is far away", () => {
    render(<TrackingPanel state={tracking(12)} />);
    expect(screen.queryByRole("button", { name: /recenter on target/i })).toBeNull();
  });
});
