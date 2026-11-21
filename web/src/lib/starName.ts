// Names for plate-solved stars, looked up by position in the bright-star
// catalogue (HYG). Used by the sync step so "Star 1" can read "Vega".
import type { StarEntry } from "@/lib/catalogTypes";
import { angularSepDeg } from "@/lib/nearest";

/** Solver and catalogue positions agree to a few arcseconds; anything else is a different star. */
export const STAR_MATCH_DEG = 1 / 60;

type Star = Omit<StarEntry, "source">;

export interface StarName {
  /** Proper name ("Vega"), else the Bayer / Flamsteed designation ("ε Ori", "31 Ori"). */
  name: string;
  /** The designation when `name` is a proper name. */
  designation: string | null;
}

const CATALOGUE_RE = /^(HIP|HD|HR|Gl|GJ|LHS|LTT|Wo|NN|BD|CD|SAO)\b/;
const GREEK_RE = /[α-ω]/;
const FLAMSTEED_RE = /^\d+ [A-Z][a-z]{2}$/;

function isDesignation(s: string): boolean {
  return GREEK_RE.test(s) || FLAMSTEED_RE.test(s);
}

/** How the star is known, or null when it only has catalogue numbers. */
export function starName(star: Star): StarName | null {
  const names = [star.id, ...star.aliases];
  const designation =
    names.find((s) => GREEK_RE.test(s)) ?? names.find((s) => FLAMSTEED_RE.test(s)) ?? null;
  const proper = names.find((s) => !CATALOGUE_RE.test(s) && !isDesignation(s)) ?? null;
  if (proper) return { name: proper, designation };
  if (designation) return { name: designation, designation: null };
  return null;
}

/** The named catalogue star at (ra, dec), J2000 degrees, if there is one. */
export function starNameAt(
  raDeg: number,
  decDeg: number,
  stars: readonly Star[],
): StarName | null {
  for (const star of stars) {
    // Cheap reject on declination before the trig.
    if (Math.abs(star.dec_deg - decDeg) > STAR_MATCH_DEG) continue;
    if (angularSepDeg(raDeg, decDeg, star.ra_deg, star.dec_deg) <= STAR_MATCH_DEG) {
      return starName(star);
    }
  }
  return null;
}
