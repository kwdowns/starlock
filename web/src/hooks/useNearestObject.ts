import { useEffect, useMemo, useState } from "react";
import { findNearest, type NearestPlace, type SkyPlace } from "@/lib/nearest";
import { SOLAR_KIND_LABELS, useSolarSystem } from "@/lib/solarSystem";

let cache: SkyPlace[] | null = null;
let loading: Promise<SkyPlace[]> | null = null;

function loadPlaces(): Promise<SkyPlace[]> {
  loading ??= import("@/components/catalog/nearestPlaces").then((m) => {
    cache = m.nearestPlaces;
    return cache;
  });
  return loading;
}

/**
 * The named object closest to where the scope points (J2000 degrees), or
 * null while there is no pointing or the catalogue is still loading.
 */
export function useNearestObject(
  raDeg: number | null,
  decDeg: number | null,
): NearestPlace | null {
  const [places, setPlaces] = useState<SkyPlace[] | null>(cache);
  const wanted = raDeg !== null && decDeg !== null;
  useEffect(() => {
    if (!wanted || places) return;
    let live = true;
    loadPlaces()
      .then((p) => { if (live) setPlaces(p); })
      .catch(console.error);
    return () => { live = false; };
  }, [wanted, places]);

  // The Moon and planets move: positions from the engine, refreshed each minute.
  const [minute, setMinute] = useState(() => Math.floor(Date.now() / 60_000));
  useEffect(() => {
    if (!wanted) return;
    const id = window.setInterval(() => setMinute(Math.floor(Date.now() / 60_000)), 15_000);
    return () => window.clearInterval(id);
  }, [wanted]);
  const bodies = useSolarSystem(wanted ? new Date(minute * 60_000) : null);
  const all = useMemo(() => {
    if (!places) return null;
    const solar: SkyPlace[] = bodies.map((b) => ({
      name: b.name, kind: SOLAR_KIND_LABELS[b.kind], ra_deg: b.ra_j2000_deg, dec_deg: b.dec_j2000_deg,
    }));
    // Solar-system bodies first, so they win a tie with a background star.
    return [...solar, ...places];
  }, [places, bodies]);

  // Solves jitter by arcseconds; 0.01 degree steps avoid a search per frame.
  const ra = raDeg === null ? null : Math.round(raDeg * 100) / 100;
  const dec = decDeg === null ? null : Math.round(decDeg * 100) / 100;
  return useMemo(
    () => (all && ra !== null && dec !== null ? findNearest(ra, dec, all) : null),
    [all, ra, dec],
  );
}
