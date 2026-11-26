// Saved sites and equipment: text and maths shared by the Equipment sheet,
// the live-frame circles and the logbook. specs/start/SPEC_EQUIPMENT_SITES.md
// — iOS and Android format the same way.

import type { Eyepiece, Finder, ObservingSite, Optics, Telescope } from "@/lib/types";

/** A number as people write it: at most 2 decimals, no trailing zeros (6, 0.5, 1.25). */
export function plainNumber(n: number): string {
  return String(Math.round(n * 100) / 100);
}

/** "48×": magnification with no decimals. */
export function formatMagnification(m: number): string {
  return `${Math.round(m)}×`;
}

/** True field: 2 decimals under 1°, else 1 ("1.08°", "0.52°", "2.6°"). */
export function formatField(deg: number): string {
  return `${deg < 1 ? deg.toFixed(2) : deg.toFixed(1)}°`;
}

/** "48× · 1.08° field · 4.2 mm exit pupil", or null without a magnification. */
export function opticsLine(optics: Optics | null | undefined): string | null {
  if (!optics || optics.magnification == null) return null;
  const parts = [formatMagnification(optics.magnification)];
  if (optics.true_field_deg != null) parts.push(`${formatField(optics.true_field_deg)} field`);
  if (optics.exit_pupil_mm != null) parts.push(`${optics.exit_pupil_mm.toFixed(1)} mm exit pupil`);
  return parts.join(" · ");
}

export function telescopeSummary(t: Pick<Telescope, "aperture_mm" | "focal_length_mm">): string {
  return `${plainNumber(t.aperture_mm)} mm aperture, ${plainNumber(t.focal_length_mm)} mm focal length`;
}

export function eyepieceSummary(e: Pick<Eyepiece, "focal_length_mm" | "afov_deg">): string {
  return `${plainNumber(e.focal_length_mm)} mm, ${plainNumber(e.afov_deg)}° field`;
}

/** "0.5°, 2°, 4°" */
export function ringsText(rings: readonly number[]): string {
  return rings.map((r) => `${plainNumber(r)}°`).join(", ");
}

/** "Optical, 6° field" or "Reflex: 0.5°, 2°, 4°". */
export function finderSummary(f: Pick<Finder, "kind" | "field_deg" | "rings_deg">): string {
  if (f.kind === "reflex") return `Reflex: ${ringsText(f.rings_deg ?? [])}`;
  return f.field_deg != null ? `Optical, ${plainNumber(f.field_deg)}° field` : "Optical";
}

/** "40.01, -105.27" */
export function siteCoords(s: Pick<ObservingSite, "latitude" | "longitude">): string {
  return `${s.latitude.toFixed(2)}, ${s.longitude.toFixed(2)}`;
}

/**
 * Radius in image pixels of a circle `deg` across, on a frame `imageW`
 * pixels wide that spans `fovHDeg`: (deg / 2) × image_w / fov_h_deg.
 * Null when the field of view isn't known.
 */
export function circleRadiusPx(deg: number, imageW: number, fovHDeg: number): number | null {
  if (!(fovHDeg > 0) || !(imageW > 0) || !(deg > 0)) return null;
  return ((deg / 2) * imageW) / fovHDeg;
}

/** What a logbook entry recorded about where and with what it was seen. */
export interface EquipmentNames {
  site_name?: string | null;
  telescope?: string | null;
  eyepiece?: string | null;
  finder?: string | null;
  magnification?: number | null;
}

/**
 * "Back yard · 8" Dob · 25 mm Plössl (48×) · Telrad" with the missing parts
 * left out; null when nothing is known.
 */
export function equipmentLine(e: EquipmentNames): string | null {
  const eyepiece = e.eyepiece
    ? e.magnification != null
      ? `${e.eyepiece} (${formatMagnification(e.magnification)})`
      : e.eyepiece
    : null;
  const parts = [e.site_name, e.telescope, eyepiece, e.finder].filter(
    (p): p is string => !!p && p.trim() !== "",
  );
  return parts.length > 0 ? parts.join(" · ") : null;
}

// ------------------------------------------------------------ form input

/** Same limits as the engine (spec §1); the engine has the last word. */
export const LIMITS = {
  name: { max: 60 },
  aperture_mm: { min: 10, max: 2000 },
  focal_length_mm: { min: 50, max: 20000 },
  eyepiece_focal_length_mm: { min: 1, max: 100 },
  afov_deg: { min: 20, max: 120 },
  field_deg: { min: 0.5, max: 20 },
  ring_deg: { min: 0.1, max: 10 },
  rings: { max: 4 },
} as const;

export const DEFAULT_AFOV_DEG = 52;
export const DEFAULT_RINGS = "0.5, 2, 4";

/** A number typed into a field; accepts a typographic minus. NaN when empty or not a number. */
export function parseNumber(s: string): number {
  const t = s.trim().replace(/[−–]/g, "-");
  return t === "" ? NaN : Number(t);
}

/** A stored number as the text a form field starts with ("" when missing). */
export function numText(n: number | null | undefined): string {
  return n == null ? "" : String(n);
}

export type Parsed<T> = { ok: true; value: T } | { ok: false; error: string };

export function parseName(s: string): Parsed<string> {
  const t = s.trim();
  if (t.length === 0) return { ok: false, error: "Give it a name." };
  if (t.length > LIMITS.name.max) return { ok: false, error: `At most ${LIMITS.name.max} characters.` };
  return { ok: true, value: t };
}

export function parseInRange(s: string, min: number, max: number): Parsed<number> {
  const n = parseNumber(s);
  if (!Number.isFinite(n) || n < min || n > max) {
    return { ok: false, error: `Between ${plainNumber(min)} and ${plainNumber(max)}.` };
  }
  return { ok: true, value: n };
}

/** "0.5, 2, 4" → [0.5, 2, 4]: 1–4 values, each 0.1–10°, smallest first. */
export function parseRings(s: string): Parsed<number[]> {
  const bits = s
    .split(/[,;\s]+/)
    .map((b) => b.replace(/°$/, ""))
    .filter((b) => b !== "");
  const rings = bits.map(parseNumber);
  const { min, max } = LIMITS.ring_deg;
  if (
    rings.length < 1 ||
    rings.length > LIMITS.rings.max ||
    rings.some((r) => !Number.isFinite(r) || r < min || r > max)
  ) {
    return { ok: false, error: `1 to ${LIMITS.rings.max} sizes, each ${min} to ${max}°, with commas.` };
  }
  if (rings.some((r, i) => i > 0 && r <= rings[i - 1])) {
    return { ok: false, error: "Smallest first, each bigger than the one before." };
  }
  return { ok: true, value: rings };
}
