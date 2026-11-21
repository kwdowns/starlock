import { useEffect, useMemo, useState } from "react";
import type { StarEntry } from "@/lib/catalogTypes";
import { starNameAt, type StarName } from "@/lib/starName";

type Star = Omit<StarEntry, "source">;

let cache: Star[] | null = null;
let loading: Promise<Star[]> | null = null;

function loadStars(): Promise<Star[]> {
  // The star file is large; only pulled in when the sync step needs it.
  loading ??= import("@/data/hyg-bright.json").then((m) => {
    cache = m.default as Star[];
    return cache;
  });
  return loading;
}

/**
 * Catalogue names for a list of positions (J2000 degrees), index-aligned.
 * Entries are null while the catalogue loads or for unnamed stars.
 */
export function useStarNames(
  positions: readonly { ra_deg: number; dec_deg: number }[],
): (StarName | null)[] {
  const [stars, setStars] = useState<Star[] | null>(cache);
  const wanted = positions.length > 0;
  useEffect(() => {
    if (!wanted || stars) return;
    let live = true;
    loadStars()
      .then((s) => { if (live) setStars(s); })
      .catch(console.error);
    return () => { live = false; };
  }, [wanted, stars]);

  const key = positions.map((p) => `${p.ra_deg},${p.dec_deg}`).join(";");
  return useMemo(
    () => positions.map((p) => (stars ? starNameAt(p.ra_deg, p.dec_deg, stars) : null)),
    // `key` stands in for `positions`, which is a new array on every payload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [stars, key],
  );
}
