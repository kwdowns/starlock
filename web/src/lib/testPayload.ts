// Shared engine payloads for component tests and the ?gallery demos. Not imported by the app.
import type { EnginePayload, ObservingBlock } from "@/lib/types";

export const basePayload: EnginePayload = {
  state: "SETUP",
  failures: 0,
  pointing: { valid: false, ra_deg: 0, dec_deg: 0, roll_deg: 0, matches: 0, prob: 1, solve_age_s: null },
  nav: null,
  origin_x: 640, origin_y: 360, image_w: 1280, image_h: 720,
  finder_rotation: 0, fov_h_deg: 8.86,
  has_calibration: false, image_size: null,
  mount: { mode: "altaz", needs_location: true, axes: null },
  controls: [],
  sync: { in_progress: false, candidates: [], selected_idx: null, error: null },
  stellarium: { active: false, address: null },
  lx200: { active: false, address: null },
  webserver: { url: null },
  audio_enabled: true,
  power: { available: false, cpu_cap: false, max_freq_mhz: null },
  camera: { connected: true, frame_id: null, all_centroids: null, matched_centroids: null },
  location: { latitude: null, longitude: null, source: null },
  dev_mode: false, min_matches: 8, max_prob: 0.2, sample_active: null,
};

export function payload(over: Partial<EnginePayload> = {}): EnginePayload {
  return { ...basePayload, ...over };
}

/** A Pi with saved sites and equipment: the back yard, an 8" Dob, a 25 mm eyepiece and a Telrad in use. */
export const sampleObserving: ObservingBlock = {
  sites: [
    { id: "s1", name: "Back yard", latitude: 40.0149, longitude: -105.2705, horizon: Array(16).fill(3) },
    { id: "s2", name: "Dark site", latitude: 39.4321, longitude: -105.8123, horizon: Array(16).fill(1) },
  ],
  telescopes: [
    { id: "t1", name: '8" Dob', aperture_mm: 203, focal_length_mm: 1200 },
    { id: "t2", name: "80 mm refractor", aperture_mm: 80, focal_length_mm: 480 },
  ],
  eyepieces: [
    { id: "e1", name: "25 mm Plössl", focal_length_mm: 25, afov_deg: 52 },
    { id: "e2", name: "10 mm wide", focal_length_mm: 10, afov_deg: 68 },
  ],
  finders: [
    { id: "f1", name: "Telrad", kind: "reflex", rings_deg: [0.5, 2, 4] },
    { id: "f2", name: "8x50 RACI", kind: "optical", field_deg: 6 },
  ],
  current: { site_id: "s1", telescope_id: "t1", eyepiece_id: "e1", finder_id: "f1" },
  optics: { magnification: 48, true_field_deg: 1.08, exit_pupil_mm: 4.23, finder_rings_deg: [0.5, 2, 4] },
};
