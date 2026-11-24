// Horizon mask: which parts of the sky trees or buildings hide.
// specs/start/SPEC_HORIZON_MOUNT_MODEL.md §1 — iOS and Android implement the same maths.

/** Direction sectors, each 22.5° wide and centred on `s × 22.5°`. */
export const SECTOR_COUNT = 16;
/** Altitude bands of 10°; band 8 is 80–90°. */
export const BAND_COUNT = 9;
export const SECTOR_NAMES = [
  "N", "NNE", "NE", "ENE",
  "E", "ESE", "SE", "SSE",
  "S", "SSW", "SW", "WSW",
  "W", "WNW", "NW", "NNW",
] as const;

/** 16 ints, one per sector; bit b set = altitude band b (10b to 10b + 10°) is hidden. */
export type HorizonMask = readonly number[];

/** Everything below 20° hidden (bands 0 and 1), the old fixed cut of the Tonight list. */
export const DEFAULT_HORIZON: HorizonMask = Object.freeze(Array<number>(SECTOR_COUNT).fill(3));
export const CLEAR_HORIZON: HorizonMask = Object.freeze(Array<number>(SECTOR_COUNT).fill(0));

/** Sector (0–15) of an azimuth, any range of degrees. */
export function sectorOf(azDeg: number): number {
  return Math.floor(((((azDeg + 11.25) % 360) + 360) % 360) / 22.5) % SECTOR_COUNT;
}

/** Band (0–8) of a non-negative altitude. */
export function bandOf(altDeg: number): number {
  return Math.min(BAND_COUNT - 1, Math.floor(altDeg / 10));
}

/** Above the horizon and not behind a hidden cell. Below 0° is never visible. */
export function isVisible(altDeg: number, azDeg: number, obscured: HorizonMask): boolean {
  if (!(altDeg >= 0)) return false;
  return ((obscured[sectorOf(azDeg)] >> bandOf(altDeg)) & 1) === 0;
}

export function isHidden(mask: HorizonMask, sector: number, band: number): boolean {
  return ((mask[sector] >> band) & 1) === 1;
}

/** A copy of `mask` with one cell set hidden or clear. */
export function withCell(mask: HorizonMask, sector: number, band: number, hidden: boolean): number[] {
  const next = [...mask];
  next[sector] = hidden ? next[sector] | (1 << band) : next[sector] & ~(1 << band);
  return next;
}

/** The engine's mask when it sent a valid one, else the default (older engines send none). */
export function horizonFrom(obscured: unknown): HorizonMask {
  if (
    Array.isArray(obscured) &&
    obscured.length === SECTOR_COUNT &&
    obscured.every((v) => Number.isInteger(v) && v >= 0 && v <= 511)
  ) {
    return obscured as number[];
  }
  return DEFAULT_HORIZON;
}

export function sameMask(a: HorizonMask, b: HorizonMask): boolean {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}
