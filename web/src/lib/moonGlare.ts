import { altAzFromRaDec } from "@/lib/astronomy";
import { angularSepDeg } from "@/lib/nearest";
import type { SolarBody } from "@/lib/solarSystem";

/** A bright Moon this close to the target floods the finder camera. */
export const MOON_GLARE_DEG = 15;
/** Below this lit fraction the Moon is no worse than a bright star. */
export const MOON_GLARE_MIN_LIT = 0.6;

export type MoonGlare =
  | { kind: "is-moon" }
  | { kind: "near"; sepDeg: number; litPct: number };

/**
 * Whether moonlight will make plate solving hard for a target at (ra, dec):
 * the Moon itself (it overexposes the frame), or a target within
 * MOON_GLARE_DEG of a Moon that is at least 60% lit and above the horizon.
 */
export function moonGlare(
  target: { ra_deg: number; dec_deg: number; isMoon?: boolean },
  bodies: SolarBody[],
  location: { latitude: number; longitude: number } | null,
  at: Date,
): MoonGlare | null {
  if (target.isMoon) return { kind: "is-moon" };
  const moon = bodies.find((b) => b.kind === "moon");
  if (!moon || moon.phase_fraction === null || moon.phase_fraction < MOON_GLARE_MIN_LIT) return null;
  if (location) {
    const { altDeg } = altAzFromRaDec({
      raHours: moon.ra_j2000_deg / 15,
      decDeg: moon.dec_j2000_deg,
      latDeg: location.latitude,
      lonDeg: location.longitude,
      date: at,
    });
    if (altDeg < 0) return null;
  }
  const sepDeg = angularSepDeg(target.ra_deg, target.dec_deg, moon.ra_j2000_deg, moon.dec_j2000_deg);
  if (sepDeg >= MOON_GLARE_DEG) return null;
  return { kind: "near", sepDeg, litPct: Math.round(moon.phase_fraction * 100) };
}

export function moonGlareText(g: MoonGlare, name: string): string {
  if (g.kind === "is-moon") {
    return "The Moon overexposes the finder camera, so the Starlock usually can't solve with it in view. Use the directions to get close, then finish by eye in the finder.";
  }
  return `${name} is ${Math.round(g.sepDeg)}° from the Moon (${g.litPct}% lit). Moonlight can wash out the camera near it, so solving may fail. Lower the exposure, or pick a target farther from the Moon.`;
}
