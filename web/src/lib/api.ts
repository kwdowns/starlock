import type {
  Eyepiece,
  Finder,
  MountMode,
  ObservingCurrent,
  ObservingKind,
  ObservingSite,
  Telescope,
} from "@/lib/types";

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
  /** A downscaled camera frame was kept with the entry (may be trimmed later). */
  has_frame?: boolean;
  /** Names of the site and equipment in use when the entry opened (older engines: missing). */
  site_name?: string | null;
  telescope?: string | null;
  eyepiece?: string | null;
  finder?: string | null;
  magnification?: number | null;
}

export interface ObservationList {
  enabled: boolean;
  clock: "system" | "client";
  entries: ObservationEntry[];
}

export interface CloudStatus {
  /** False when the engine has no cloud link support running. */
  available: boolean;
  linked: boolean;
  device_id?: string;
  name?: string | null;
  base_url?: string;
  paired_at?: number;
  error?: string | null;
  default_base_url?: string | null;
  last_pointing_at?: number | null;
  pointing_error?: string | null;
  last_upload_at?: number | null;
  upload_error?: string | null;
}

async function cloudCall(path: string, init?: RequestInit): Promise<CloudStatus> {
  const resp = await fetch(path, init);
  if (resp.status >= 400) throw new Error((await resp.text()) || `HTTP ${resp.status}`);
  return await resp.json();
}

/** An item as sent to the engine: everything but the id (a site's horizon is optional on create). */
export type ObservingItemBody<K extends ObservingKind> = K extends "sites"
  ? Omit<ObservingSite, "id" | "horizon"> & { horizon?: number[] }
  : K extends "telescopes"
    ? Omit<Telescope, "id">
    : K extends "eyepieces"
      ? Omit<Eyepiece, "id">
      : Omit<Finder, "id">;

/** The engine's short reason for a refusal ("aperture_mm must be 10–2000"), kept to one line. */
function shortReason(text: string, status: number): string {
  const line = text.trim().split(/\r?\n/)[0].slice(0, 160);
  return line || `HTTP ${status}`;
}

async function send(method: string, path: string, body?: unknown): Promise<Response> {
  const init: RequestInit = { method };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const resp = await fetch(path, init);
  if (resp.status >= 400) throw new Error(shortReason(await resp.text(), resp.status));
  return resp;
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
  /** The target is centred in the eyepiece: re-aim the alignment on it. */
  recenter: async (): Promise<{ shift_deg: number }> => {
    const resp = await fetch("/api/sync/recenter", { method: "POST" });
    if (resp.status >= 400) throw new Error(await resp.text());
    return await resp.json();
  },
  /** `size_deg`: apparent size (major axis), so big objects count as on target over more of their extent. */
  setGoto: (ra_deg: number, dec_deg: number, name?: string, size_deg?: number) =>
    post("/api/goto/set", {
      ra_deg,
      dec_deg,
      ...(name ? { name } : {}),
      ...(size_deg ? { size_deg } : {}),
    }),
  /** Tell the engine this device's clock (for a Pi whose own clock is wrong). Sent on every (re)connect. */
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
  cloudStatus: () => cloudCall("/api/cloud"),
  cloudPair: (code: string, base_url?: string) =>
    cloudCall("/api/cloud/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(base_url ? { code, base_url } : { code }),
    }),
  cloudUnlink: async () => {
    const resp = await fetch("/api/cloud", { method: "DELETE" });
    if (resp.status >= 400) throw new Error((await resp.text()) || `HTTP ${resp.status}`);
  },
  setSettings: (s: {
    audio_enabled?: boolean;
    cpu_cap?: boolean;
    mount_mode?: MountMode;
    location?: { latitude: number; longitude: number } | null;
    lx200_epoch?: "jnow" | "j2000";
    /** Address of the computer running Stellarium; "" = the connected one. */
    stellarium_rc_host?: string;
    observation_log_enabled?: boolean;
    /** 16 per-sector bitmasks of hidden 10° bands; null = back to the default (below 20° hidden). */
    horizon?: { obscured: number[] } | null;
  }) => post("/api/settings", s),
  /** Saved sites and equipment. Errors carry the engine's short reason as their message. */
  observing: {
    create: async <K extends ObservingKind>(kind: K, item: ObservingItemBody<K>): Promise<{ id: string }> =>
      await (await send("POST", `/api/observing/${kind}`, item)).json(),
    update: async <K extends ObservingKind>(kind: K, id: string, item: ObservingItemBody<K>) => {
      await send("PUT", `/api/observing/${kind}/${encodeURIComponent(id)}`, item);
    },
    remove: async (kind: ObservingKind, id: string) => {
      await send("DELETE", `/api/observing/${kind}/${encodeURIComponent(id)}`);
    },
    /** A missing key leaves that slot; null clears it. */
    setCurrent: async (current: Partial<ObservingCurrent>) => {
      await send("POST", "/api/observing/current", current);
    },
  },
  /** Forget the mount model's samples and start learning again. */
  resetMountModel: () => post("/api/mount/model/reset"),
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
