import { Alert } from "@/components/ui";
import type { EnginePayload, WifiInfo } from "@/lib/types";

const QUALITY_LABELS: Record<WifiInfo["quality"], string> = {
  good: "good",
  fair: "fair",
  weak: "weak",
  poor: "poor",
};

export function wifiSummary(wifi: WifiInfo): string {
  return `${wifi.avg_dbm} dBm (${QUALITY_LABELS[wifi.quality]})`;
}

/**
 * Shown while the Pi's own Wi-Fi link has been weak for a while (the engine
 * smooths and debounces it), so a laggy live view has an explanation.
 */
export function WifiWarning({ state }: { state: EnginePayload }) {
  const wifi = state.wifi;
  if (!wifi?.warn) return null;
  return (
    <Alert variant="warning" title="Weak Wi-Fi at the scope">
      The Starlock hears your Wi-Fi at {wifi.avg_dbm} dBm, so the live view may lag or drop
      out. Move the scope or the router closer, add a Wi-Fi extender, or keep the Pi
      clear of the tube and mount, which block the signal.
    </Alert>
  );
}
