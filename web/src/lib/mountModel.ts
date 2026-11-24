// Texts for the clock-sync line and the experimental mount model block in
// Settings (specs/start/SPEC_HORIZON_MOUNT_MODEL.md §2.2, §3.6). iOS and
// Android show the same sentences.

import { azimuthCompass } from "@/lib/catalogTypes";
import type { EnginePayload, MountMode, MountModel } from "@/lib/types";

/** `N s` under a minute, `N min` under an hour, `N h M min` under a day, else `N d H h`. */
export function formatClockOffset(seconds: number): string {
  const t = Math.round(Math.abs(seconds));
  if (t < 60) return `${t} s`;
  if (t < 3600) return `${Math.floor(t / 60)} min`;
  if (t < 86400) return `${Math.floor(t / 3600)} h ${Math.floor((t % 3600) / 60)} min`;
  return `${Math.floor(t / 86400)} d ${Math.floor((t % 86400) / 3600)} h`;
}

/** The muted line under the location; null when the engine sends no clock (older engines). */
export function clockLine(clock: EnginePayload["clock"]): string | null {
  if (!clock) return null;
  if (clock.source === "system") return "Pi clock is correct.";
  const dir = clock.offset_s > 0 ? "behind" : "ahead";
  return `Pi clock set from this device (it was ${formatClockOffset(clock.offset_s)} ${dir}).`;
}

const HINTS: Record<MountMode, Record<"turn" | "tilt", string>> = {
  altaz: {
    turn: "Next, turn the base to a new direction.",
    tilt: "Next, raise or lower the tube.",
  },
  eq: {
    turn: "Next, swing to a new right ascension.",
    tilt: "Next, move to a new declination.",
  },
};

const CORRECTS = "Guidance corrects for it.";

/** One or two sentences describing what the mount model knows so far. */
export function mountModelLines(model: MountModel, mode: MountMode): string[] {
  switch (model.state) {
    case "off":
      return ["Set your location so Starlock can learn how your mount sits."];
    case "collecting": {
      const done = Math.min(model.samples, model.needed);
      return [
        `Learning your mount: ${done} of ${model.needed} positions.`,
        model.hint ? HINTS[mode][model.hint] : "Keep pointing at different heights and directions.",
      ];
    }
    case "ready": {
      if (mode === "altaz") {
        const tilt = model.tilt_deg ?? 0;
        if (tilt < 0.2) return ["The base is level (within 0.2°)."];
        return [
          `The base tilts ${tilt.toFixed(1)}°, low side ${azimuthCompass(model.low_side_az_deg ?? 0)}. ${CORRECTS}`,
        ];
      }
      const alt = model.polar_alt_error_deg ?? 0;
      const az = model.polar_az_error_deg ?? 0;
      const parts: string[] = [];
      if (Math.abs(alt) >= 0.1) parts.push(`${Math.abs(alt).toFixed(1)}° ${alt > 0 ? "too high" : "too low"}`);
      if (Math.abs(az) >= 0.1) parts.push(`${Math.abs(az).toFixed(1)}° ${az > 0 ? "east" : "west"} of the pole`);
      if (parts.length === 0) return ["The polar axis is on the pole (within 0.1°)."];
      return [`The polar axis is ${parts.join(" and ")}. ${CORRECTS}`];
    }
  }
}
