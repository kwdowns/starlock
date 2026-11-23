// Mirror of webserver/_build_payload — keep in sync by hand.

export type EngineState =
  | "SETUP"
  | "SYNC"
  | "SYNC_CONFIRM"
  | "CALIBRATE"
  | "WARMING_UP"
  | "TRACKING"
  | "RECONNECTING"
  | "ERROR";

export interface PointingData {
  valid: boolean;
  ra_deg: number;
  dec_deg: number;
  roll_deg: number;
  matches: number;
  prob: number;
  solve_age_s: number | null;
}

export type MountMode = "altaz" | "eq";

/**
 * Moves along the mount's own axes. axis1: alt-az base turn (+ = right /
 * clockwise from above) or equatorial RA (+ = east). axis2: alt-az tube
 * (+ = raise) or Dec (+ = north). Angles are image directions, clockwise
 * from up, that the view moves for a + move.
 */
export interface MountNav {
  axis1_deg: number;
  axis2_deg: number;
  axis1_angle_deg: number;
  axis2_angle_deg: number;
  /** Alt-az: near the zenith. Equatorial: near the celestial pole. */
  near_pole: boolean;
  pointing_alt_deg: number | null;
  target_alt_deg: number | null;
}

export interface NavData {
  active: boolean;
  /** Null without a solve, or in alt-az mode without a location. */
  mount: MountNav | null;
  target_name: string | null;
  target_ra_deg: number;
  target_dec_deg: number;
  /** Apparent size sent with the target, degrees (older engines: missing). */
  target_size_deg?: number | null;
  /** On target within this of the centre; grows with the target's size. */
  on_target_deg?: number;
  separation_deg: number | null;
  direction_text: string;
  in_fov: boolean;
  pixel_x: number | null;
  pixel_y: number | null;
  camera_angle_deg: number | null;
  edge_x: number | null;
  edge_y: number | null;
  edge_angle_deg: number | null;
}

export interface ControlDescriptor {
  id?: string;     // server uses "id"
  name?: string;   // some payloads use "name"
  label: string;
  min: number;
  max: number;
  step: number;
  cur: number;     // current value — DPG protocol uses "cur"
  value?: number;  // legacy alias kept for back-compat
  unit?: string;
  type?: string;
  // Multiplier from the reported exposure to the real one (e.g. 2 for the
  // Innomaker U20CAM, whose firmware under-reports exposure). Default 1.
  display_scale?: number;
}

export interface SyncCandidate {
  idx: number;
  name: string;
  ra_deg: number;
  dec_deg: number;
  magnitude: number;
  pixel_x: number;
  pixel_y: number;
}

export interface SyncBlock {
  in_progress: boolean;
  candidates: SyncCandidate[];
  selected_idx: number | null;
  error: string | null;
}

export interface ObserverLocation {
  name?: string;
  country?: string;
  latitude?: number;
  longitude?: number;
}

export interface ActivityLine {
  active: boolean;
  address: string | null;
  status?: unknown;
  object?: { name?: string; "localized-name"?: string } | null;
  location?: ObserverLocation | null;
  /** LX200 only: reported coordinate epoch ("jnow" default, "j2000" for Stellarium Mobile PLUS). */
  epoch?: "jnow" | "j2000";
}

export interface CameraBlock {
  connected: boolean;
  /** Changes with every new camera frame; LiveView fetches /frame.jpg on change. */
  frame_id: number | null;
  all_centroids: number[][] | null;     // [[y, x], ...]
  matched_centroids: number[][] | null; // [[y, x], ...]
}

/** The Pi's own Wi-Fi client link, smoothed over ~20 s. */
export interface WifiInfo {
  interface: string;
  level_dbm: number;
  avg_dbm: number;
  quality: "good" | "fair" | "weak" | "poor";
  /** Weak for long enough to tell the user (with hysteresis). */
  warn: boolean;
}

export interface EnginePayload {
  state: EngineState;
  failures: number;
  pointing: PointingData;
  nav: NavData | null;
  origin_x: number;
  origin_y: number;
  image_w: number;
  image_h: number;
  finder_rotation: number;
  fov_h_deg: number;
  has_calibration: boolean;
  mount: {
    mode: MountMode;
    /** Alt-az mode with no observer location: falls back to the calibrated arrow. */
    needs_location: boolean;
    axes: { axis1_angle_deg: number; axis2_angle_deg: number } | null;
  };
  image_size: [number, number] | null;
  controls: ControlDescriptor[];
  sync: SyncBlock;
  stellarium: ActivityLine;
  lx200: ActivityLine;
  webserver: { url: string | null };
  audio_enabled: boolean;
  /** Headless Pi CPU clock cap; `available` is false off the Pi. */
  power: {
    available: boolean;
    cpu_cap: boolean;
    max_freq_mhz: number | null;
  };
  camera: CameraBlock;
  location: {
    latitude: number | null;
    longitude: number | null;
    source: "stellarium" | "manual" | null;
  };
  dev_mode: boolean;
  min_matches: number;
  max_prob: number;
  sample_active: string | null;
  /** Null on Ethernet, in hotspot mode, or off the Pi; missing from older engines. */
  wifi?: WifiInfo | null;
}
