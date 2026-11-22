import type { MountMode } from "@/lib/types";

async function post(path: string, body?: unknown): Promise<void> {
  const init: RequestInit = { method: "POST" };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const resp = await fetch(path, init);
  if (resp.status >= 400) {
    throw new Error(`POST ${path} → ${resp.status}: ${await resp.text()}`);
  }
}

export interface ObservationEntry {
  id: number;
  start_utc: string;
  end_utc: string;
  duration_s: number;
  open: boolean;
  ra_j2000_deg: number;
  dec_j2000_deg: number;
  alt_deg: number | null;
  az_deg: number | null;
  target_name: string | null;
  clock: "system" | "client";
}

export interface ObservationList {
  enabled: boolean;
  clock: "system" | "client";
  entries: ObservationEntry[];
}

function rangeQuery(startIso: string, endIso: string): string {
  return new URLSearchParams({ start: startIso, end: endIso }).toString();
}

export const api = {
  wizardAdvance: () => post("/api/wizard/advance"),
  syncRetry: () => post("/api/sync/retry"),
  syncSelect: (idx: number) => post("/api/sync/select", { idx }),
  useCalibration: () => post("/api/calibration/use-previous"),
  retryCamera: async (): Promise<{ connected: boolean }> => {
    const resp = await fetch("/api/camera/retry", { method: "POST" });
    if (resp.status >= 400) {
      throw new Error(`POST /api/camera/retry → ${resp.status}: ${await resp.text()}`);
    }
    return await resp.json();
  },
  setControl: (name: string, value: number) => post("/api/control", { name, value }),
  clearGoto: () => post("/api/goto/clear"),
  setGoto: (ra_deg: number, dec_deg: number, name?: string) =>
    post("/api/goto/set", name ? { ra_deg, dec_deg, name } : { ra_deg, dec_deg }),
  /** Tell the engine this device's clock (for a Pi whose own clock is wrong). */
  reportClock: () => post("/api/clock", { unix_ms: Date.now() }),
  observations: async (startIso: string, endIso: string): Promise<ObservationList> => {
    const resp = await fetch(`/api/observations?${rangeQuery(startIso, endIso)}&limit=200`);
    if (resp.status >= 400) {
      throw new Error(`GET /api/observations → ${resp.status}: ${await resp.text()}`);
    }
    return await resp.json();
  },
  observationsCsvUrl: (startIso: string, endIso: string) =>
    `/api/observations.csv?${rangeQuery(startIso, endIso)}`,
  setSettings: (s: {
    audio_enabled?: boolean;
    cpu_cap?: boolean;
    mount_mode?: MountMode;
    location?: { latitude: number; longitude: number } | null;
    lx200_epoch?: "jnow" | "j2000";
    observation_log_enabled?: boolean;
  }) => post("/api/settings", s),
  setAdvanced: (s: { min_matches?: number; max_prob?: number }) =>
    post("/api/settings", s),
  dev: {
    injectSample: (name: string | null) =>
      post("/api/dev/inject-sample", { name }),
    injectTarget: (ra_deg: number, dec_deg: number) =>
      post("/api/dev/inject-target", { ra_deg, dec_deg }),
    captureFrame: async (): Promise<{ path: string | null; error?: string }> => {
      const resp = await fetch("/api/dev/capture-frame", { method: "POST" });
      return await resp.json();
    },
  },
};
