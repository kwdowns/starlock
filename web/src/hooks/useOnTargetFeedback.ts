import { useEffect, useRef, useSyncExternalStore } from "react";
import { readStored, writeStored } from "@/components/catalog/storage";
import type { EnginePayload } from "@/lib/types";

// The engine plays its own sounds on the machine it runs on, which a
// headless Pi can't (no speaker). This plays the on-target cue in the
// browser instead: a short chime (Web Audio) and, where the browser can,
// a vibration (Android; iOS Safari has no vibrate API).

const KEY = "starlock.sound.onTarget";
const listeners = new Set<() => void>();

export function onTargetSoundEnabled(): boolean {
  return readStored(KEY) !== "off";
}

export function setOnTargetSound(on: boolean): void {
  writeStored(KEY, on ? null : "off");
  listeners.forEach((l) => l());
}

/** The browser's on-target sound setting, shared by the top bar and Settings. */
export function useOnTargetSound(): [boolean, (on: boolean) => void] {
  const on = useSyncExternalStore(
    (l) => { listeners.add(l); return () => { listeners.delete(l); }; },
    onTargetSoundEnabled,
    () => true,
  );
  return [on, setOnTargetSound];
}

let ctx: AudioContext | null = null;

function audio(): AudioContext | null {
  if (typeof window === "undefined" || !("AudioContext" in window)) return null;
  ctx ??= new AudioContext();
  return ctx;
}

// Browsers only start audio after a tap; unlock on the first one.
function unlockOnce() {
  const unlock = () => {
    void audio()?.resume();
    window.removeEventListener("pointerdown", unlock);
  };
  window.addEventListener("pointerdown", unlock);
}

/** Two soft rising notes, about half a second. */
export function playChime(): void {
  const ac = audio();
  if (!ac || ac.state !== "running") return;
  const t0 = ac.currentTime;
  for (const [i, freq] of [660, 990].entries()) {
    const osc = ac.createOscillator();
    const gain = ac.createGain();
    osc.type = "sine";
    osc.frequency.value = freq;
    const start = t0 + i * 0.16;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.25, start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.32);
    osc.connect(gain).connect(ac.destination);
    osc.start(start);
    osc.stop(start + 0.34);
  }
}

/** Chime and vibrate when the engine reports the scope arriving on target. */
export function useOnTargetFeedback(state: EnginePayload | null): void {
  const was = useRef(false);
  const target = useRef<string | null>(null);
  useEffect(unlockOnce, []);
  const nav = state?.nav;
  const key = nav?.active ? `${nav.target_ra_deg},${nav.target_dec_deg}` : null;
  const on = !!nav?.active && !!state?.pointing.valid && nav.on_target === true;
  useEffect(() => {
    const arrived = on && (!was.current || target.current !== key);
    was.current = on;
    target.current = key;
    if (!arrived) return;
    if (onTargetSoundEnabled()) playChime();
    navigator.vibrate?.([80, 60, 160]);
  }, [on, key]);
}
