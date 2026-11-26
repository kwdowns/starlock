import { useSyncExternalStore } from "react";
import { readStored, writeStored } from "@/components/catalog/storage";

// Eyepiece and finder field circles on the live frame: shown or not, per
// device (spec SPEC_EQUIPMENT_SITES §5.3). Eyepiece on by default, finder off.

export type FieldCircle = "eyepiece" | "finder";

const KEYS: Record<FieldCircle, string> = {
  eyepiece: "starlock.circles.eyepiece",
  finder: "starlock.circles.finder",
};
const DEFAULTS: Record<FieldCircle, boolean> = { eyepiece: true, finder: false };

const listeners = new Set<() => void>();

export function fieldCircleShown(which: FieldCircle): boolean {
  const v = readStored(KEYS[which]);
  return v === null ? DEFAULTS[which] : v === "on";
}

export function setFieldCircleShown(which: FieldCircle, on: boolean): void {
  writeStored(KEYS[which], on === DEFAULTS[which] ? null : on ? "on" : "off");
  listeners.forEach((l) => l());
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

/** One circle's switch, shared by the camera settings panel and the live frame. */
export function useFieldCircle(which: FieldCircle): [boolean, (on: boolean) => void] {
  const on = useSyncExternalStore(
    subscribe,
    () => fieldCircleShown(which),
    () => DEFAULTS[which],
  );
  return [on, (v) => setFieldCircleShown(which, v)];
}
