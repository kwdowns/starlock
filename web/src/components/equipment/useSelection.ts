import { useState } from "react";
import { api } from "@/lib/api";
import type { ObservingCurrent } from "@/lib/types";

export type Slot = keyof ObservingCurrent;

export const SLOT_NOUNS: Record<Slot, string> = {
  site_id: "site",
  telescope_id: "telescope",
  eyepiece_id: "eyepiece",
  finder_id: "finder",
};

export interface Selection {
  /** What is in use, with our own picks shown before the engine confirms them. */
  current: ObservingCurrent;
  select: (slot: Slot, id: string | null) => void;
  /** "Couldn't change the eyepiece", or null. */
  error: string | null;
}

/**
 * What's in use, picked optimistically: a choice shows at once and goes to
 * the engine; on an error it goes back to the engine's value with a short
 * message. Follows the engine (other devices, a deleted item) once nothing
 * of ours is in flight.
 */
export function useSelection(engine: ObservingCurrent): Selection {
  const [pending, setPending] = useState<Partial<ObservingCurrent>>({});
  const [inflight, setInflight] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const key = `${engine.site_id}|${engine.telescope_id}|${engine.eyepiece_id}|${engine.finder_id}`;
  const [seenKey, setSeenKey] = useState(key);
  if (seenKey !== key) {
    setSeenKey(key);
    if (inflight === 0) setPending({});
  }

  async function select(slot: Slot, id: string | null) {
    setPending((p) => ({ ...p, [slot]: id }));
    setError(null);
    setInflight((n) => n + 1);
    try {
      await api.observing.setCurrent({ [slot]: id });
    } catch (e) {
      console.error(e);
      setPending((p) => {
        const next = { ...p };
        delete next[slot];
        return next;
      });
      setError(`Couldn't change the ${SLOT_NOUNS[slot]}`);
    } finally {
      setInflight((n) => n - 1);
    }
  }

  return {
    current: { ...engine, ...pending },
    select: (slot, id) => void select(slot, id),
    error,
  };
}
