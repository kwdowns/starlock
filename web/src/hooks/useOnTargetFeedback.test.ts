import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { payload } from "@/lib/testPayload";
import type { NavData } from "@/lib/types";
import { onTargetSoundEnabled, setOnTargetSound, useOnTargetFeedback } from "./useOnTargetFeedback";

const nav = (on: boolean, ra = 10): NavData => ({
  active: true, mount: null, target_name: "M31", target_ra_deg: ra, target_dec_deg: 41,
  separation_deg: on ? 0.1 : 3, direction_text: "", in_fov: true, pixel_x: 0, pixel_y: 0,
  camera_angle_deg: 0, edge_x: null, edge_y: null, edge_angle_deg: null, on_target: on,
});
const state = (on: boolean, ra = 10) => payload({
  state: "TRACKING",
  pointing: { valid: true, ra_deg: 10, dec_deg: 41, roll_deg: 0, matches: 20, prob: 1e-9, solve_age_s: 0.1 },
  nav: nav(on, ra),
});

afterEach(() => vi.restoreAllMocks());

describe("useOnTargetFeedback", () => {
  it("buzzes once on arrival, not while staying on, and again for a new target", () => {
    const vibrate = vi.fn();
    Object.defineProperty(navigator, "vibrate", { value: vibrate, configurable: true });
    const { rerender } = renderHook(({ s }) => useOnTargetFeedback(s), { initialProps: { s: state(false) } });
    expect(vibrate).not.toHaveBeenCalled();
    rerender({ s: state(true) });
    rerender({ s: state(true) });
    expect(vibrate).toHaveBeenCalledTimes(1);
    rerender({ s: state(false) });
    rerender({ s: state(true) });
    expect(vibrate).toHaveBeenCalledTimes(2);
    rerender({ s: state(true, 50) });
    expect(vibrate).toHaveBeenCalledTimes(3);
  });

  it("remembers the sound setting", () => {
    setOnTargetSound(false);
    expect(onTargetSoundEnabled()).toBe(false);
    setOnTargetSound(true);
    expect(onTargetSoundEnabled()).toBe(true);
  });
});
