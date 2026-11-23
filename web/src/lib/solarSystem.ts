import { useEffect, useState } from "react";

/** One body from GET /api/solar-system (the engine computes the positions). */
export interface SolarBody {
  id: string;
  name: string;
  kind: "moon" | "planet" | "dwarf-planet" | "asteroid";
  ra_j2000_deg: number;
  dec_j2000_deg: number;
  magnitude: number;
  distance_au: number;
  /** Lit fraction of the disc (Moon and planets), else null. */
  phase_fraction: number | null;
  /** Angle from the Sun as seen from Earth. */
  elongation_deg: number;
  constellation: string;
  /** Within 15° of the Sun: not safe or not visible; never offered as a target. */
  near_sun: boolean;
}

export const SOLAR_KIND_LABELS: Record<SolarBody["kind"], string> = {
  moon: "Moon",
  planet: "Planet",
  "dwarf-planet": "Dwarf planet",
  asteroid: "Asteroid",
};

export async function fetchSolarSystem(at?: Date): Promise<SolarBody[]> {
  const q = at ? `?at=${encodeURIComponent(at.toISOString())}` : "";
  const resp = await fetch(`/api/solar-system${q}`);
  if (!resp.ok) throw new Error(`GET /api/solar-system → ${resp.status}`);
  return ((await resp.json()) as { bodies: SolarBody[] }).bodies;
}

/**
 * Bodies at `at`, refetched when the minute changes. Empty until loaded,
 * and when the engine is too old to have the endpoint.
 */
export function useSolarSystem(at: Date | null): SolarBody[] {
  const [bodies, setBodies] = useState<SolarBody[]>([]);
  const minute = at === null ? null : Math.floor(at.getTime() / 60_000);
  useEffect(() => {
    if (minute === null) return;
    let live = true;
    fetchSolarSystem(new Date(minute * 60_000))
      .then((b) => { if (live) setBodies(b); })
      .catch(() => { if (live) setBodies([]); });
    return () => { live = false; };
  }, [minute]);
  return bodies;
}
