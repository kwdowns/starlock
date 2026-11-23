import type { NavData } from "@/lib/types";
import { isActiveTarget } from "./items";
import { readStored, writeStored } from "./storage";

// The engine doesn't carry a target's magnitude, so this device remembers the
// one it sent with the goto, keyed by position. Targets from elsewhere
// (SkySafari, Stellarium, another phone) simply have no magnitude.
const KEY = "starlock.target_mag";

type Remembered = { ra_deg: number; dec_deg: number; mag: number };

let cache: Remembered | null | undefined;

function load(): Remembered | null {
  if (cache !== undefined) return cache;
  cache = null;
  const raw = readStored(KEY);
  if (raw !== null) {
    try {
      const v = JSON.parse(raw) as Partial<Remembered>;
      if (
        typeof v.ra_deg === "number" && typeof v.dec_deg === "number" && typeof v.mag === "number"
      ) {
        cache = { ra_deg: v.ra_deg, dec_deg: v.dec_deg, mag: v.mag };
      }
    } catch {
      // corrupt entry: no magnitude
    }
  }
  return cache;
}

/** Remember the magnitude of the target being sent; `undefined` forgets it. */
export function rememberTargetMagnitude(ra_deg: number, dec_deg: number, mag: number | undefined) {
  cache = mag === undefined || !Number.isFinite(mag) ? null : { ra_deg, dec_deg, mag };
  writeStored(KEY, cache ? JSON.stringify(cache) : null);
}

/** Magnitude of the engine's active target, when this device sent it. */
export function targetMagnitude(nav: NavData | null | undefined): number | null {
  const m = load();
  return m && isActiveTarget(nav, m.ra_deg, m.dec_deg) ? m.mag : null;
}
