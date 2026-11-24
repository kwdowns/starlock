# Horizon mask, clock sync and mount model (experimental)

Status: design, 2026-11-24. Three features that share one release:

1. **Horizon mask** — the observer marks which parts of the sky trees or
   buildings hide; Tonight skips objects behind them.
2. **Clock sync** — the phone's (or browser's) clock corrects the Pi's clock
   for *everything* the engine computes, not just the observation log.
3. **Mount model** — from solves at several heights and directions the engine
   learns how far an alt-az base is off level, or how far an equatorial polar
   axis is off the pole, shows it, and corrects the push-to guidance for it.

The engine owns all state; the web UI and the iOS and Android apps only show
it and send changes. All three apps implement the UI below the same way.

---

## 1. Horizon mask

### 1.1 Model

The sky is split into **16 direction sectors × 9 altitude bands = 144 cells**.

- Sector `s` (0–15) is centred on azimuth `s × 22.5°` and spans ±11.25°:
  `s = floor(((az + 11.25) mod 360) / 22.5)`.
  Names, in order: N, NNE, NE, ENE, E, ESE, SE, SSE, S, SSW, SW, WSW, W, WNW, NW, NNW.
- Band `b` (0–8) covers altitude `[10b, 10b + 10)`; `b = min(8, floor(alt / 10))`.
- A position is **visible** when `alt >= 0` and its cell is not obscured.
  Anything below 0° is never visible.

**Default:** bands 0 and 1 obscured in every sector (everything below 20°
hidden), which matches the old fixed 20° cut of the Tonight list.

### 1.2 Storage and wire format

Stored on the Pi in `config.json` as `horizon.obscured`: a list of **16
integers**, one per sector (index = sector), each a 9-bit mask (0–511) where
bit `b` (least significant = band 0, 0–10°) set means obscured.
Default `[3, 3, …, 3]` (16 × 3).

- `/ws` payload: `"horizon": {"obscured": [16 ints]}` — always present.
- Change: `POST /api/settings` with `{"horizon": {"obscured": [16 ints]}}`.
  Each must be an int in 0–511 and there must be exactly 16, else 400.
  `{"horizon": null}` resets to the default. 204 on success.

Helper (all three apps implement the same function):

```
isVisible(altDeg, azDeg, obscured):
  if altDeg < 0: return false
  s = floor(((azDeg + 11.25) mod 360 + 360) mod 360 / 22.5) mod 16
  b = min(8, floor(altDeg / 10))
  return (obscured[s] >> b) & 1 == 0
```

Until the first payload arrives (or with an older engine that sends no
`horizon`), clients use the default mask.

### 1.3 Where it applies

- **Tonight, deep-sky list:** replaces the fixed `alt >= 20°` test with
  `isVisible(alt, az)`. Empty state: "No objects above your horizon with these
  filters at this time. Widen the filters or move the time forward."
- **Tonight, solar-system list:** replaces the fixed `alt >= 5°` test with
  `isVisible(alt, az)`. Header: "Moon, planets and bright asteroids above your
  horizon".
- Search, Manual, the detail sheet and the sky dome are unchanged.

### 1.4 Editor UI ("Horizon" section of the Settings sheet)

Placed directly **after the Location panel** in the Settings sheet.

- Section title **Horizon**.
- Text: "Tap the parts of the sky that trees or buildings hide from you.
  Tonight's list skips objects behind them."
- **The chart:** the sky dome seen from above, like a map: north at the top,
  east on the **right**. A circle split into 16 wedges and 9 rings.
  - Outer edge = the horizon (band 0, 0–10°); rings go inwards in 10° steps;
    the innermost ring is band 8 (80–90°). The centre is a small empty disc
    (radius 20 % of the chart radius) marked with a dot, so the inner rings
    stay tappable. Every ring has the same width: `w = 0.8 R / 9`; band `b`
    spans radii `[R − (b+1)w, R − b·w]`.
  - Wedge `s` spans screen angles `s·22.5 ± 11.25°`, measured clockwise from
    up (so E is at the right, S at the bottom, W at the left).
  - Clear cells: transparent fill, thin grid lines (border colour).
    Obscured cells: filled with the primary (red) colour at about 45 %
    opacity, so the grid lines stay visible. Red only (night vision).
  - Direction labels outside the circle for all 16 sectors: N, E, S, W in the
    normal label style; NE, SE, SW, NW slightly smaller; the other 8 smallest
    and muted. The chart is square and as wide as the section allows, at most
    360 pt/dp/px.
  - Under the chart, a muted caption: "Outer ring: the horizon. Centre:
    straight up. Each ring is 10°."
- **Interaction:** tapping a cell toggles it. Dragging paints: the first cell
  touched decides the mode (it was clear → every cell the finger passes
  becomes obscured; it was obscured → they become clear). Dragging inside the
  chart must not scroll the sheet. The change is shown at once (optimistic)
  and sent as one `POST /api/settings` when the finger lifts; on an error the
  chart goes back to the engine's mask and a short error shows.
- **Buttons** in one row under the caption: "Reset" (back to the default:
  below 20° hidden everywhere, posts `{"horizon": null}`) and "Clear all"
  (all 16 zero).
- Accessibility: each cell is a button labelled e.g. "NNE, 10 to 20 degrees,
  hidden" / "… visible".

---

## 2. Clock sync

The Pi 3A+/4 has no real-time clock. Without internet (hotspot mode, a dark
site) it boots with the time it last saw, often hours or days wrong. Sidereal
time — and with it the zenith, alt/az and the mount model — then comes out
wrong.

### 2.1 Engine

- One engine-wide clock (`evf/engine/clock.py`, `Clock`) replaces the
  observation log's private one. Everything that needs wall time for astronomy
  uses it: mount guidance and the mount model, `/api/solar-system` and the
  observation log. (The LX200 `:GVD#` / `:GVT#` replies are firmware-date
  placeholders and stay on the host clock.)
- `POST /api/clock` with `{"unix_ms": <client now>}` (unchanged; now works
  even when the observation log is off). When the client's time differs from
  the Pi's by more than **2 s** (was 60 s), the offset is applied; within 2 s
  any earlier correction is dropped. Reply:
  `{"client_clock_used": bool, "offset_s": float}`.
- `/ws` payload: `"clock": {"source": "client" | "system", "offset_s": float}`,
  `offset_s` = client time − Pi time (positive: the Pi was behind).

### 2.2 Clients

- Every client POSTs `/api/clock` **on every (re)connect** (web, iOS and
  Android already do on connect; make sure reconnects count too).
- **Settings sheet, Location section:** one muted line under the location:
  - `source == "client"`: "Pi clock set from this device (it was 3 h 12 min
    behind)." — "behind" when `offset_s > 0`, else "ahead". Format the
    amount as `N s` under a minute, `N min` under an hour, `N h M min` under
    a day, else `N d H h`.
  - `source == "system"`: "Pi clock is correct."
  - Hidden when the payload has no `clock` (older engine).

---

## 3. Mount model (experimental)

### 3.1 Idea

On a two-axis mount, axis 1 (the alt-az base axis, or the equatorial polar
axis) is fixed to the ground, and axis 2 (altitude or declination axis) is
fixed to the tube, so also to the camera. Each plate solve gives the camera's
full orientation `R_i` (RA, Dec, roll → J2000 → of date → local
east-north-up, using the corrected clock and the location). For every solve
the axis-2 direction `R_i · b` is at right angles to `a`:

    a · (R_i b) = 0     for all i

with `a` the unknown ground-fixed axis 1 and `b` the unknown camera-fixed
axis 2. Both are found by alternating smallest-eigenvector solves:

- `b` = smallest eigenvector of `Σ (R_iᵀ a)(R_iᵀ a)ᵀ`
- `a` = smallest eigenvector of `Σ (R_i b)(R_i b)ᵀ`

starting from `a` = the zenith (alt-az) or the true pole (equatorial), until
`a` moves less than 1e-6 rad. Axis non-perpendicularity is not modelled.

`a` and the location/clock are inseparable: a wrong clock or latitude shows
up as tilt. For guidance that is harmless (the same clock and location are
used throughout); the readout is only meaningful with a correct clock and
location, which §2 provides.

### 3.2 Samples

- A sample is taken from a fresh successful solve when a location is known and
  the camera orientation differs from every kept sample by at least 3° (in
  pointing or in roll).
- At most the 40 most recent samples are kept.
- Samples are cleared when the mount mode or the location changes, on
  `POST /api/mount/model/reset`, and when the mount has moved: 3 samples in a
  row whose residual `asin|a · R_i b|` exceeds max(1°, 4 × the fit's rms)
  against a ready model (the last one starts the new set).
- Only steady solves count: two solves in a row less than 0.05° apart (the
  scope at rest), at most one sample per second.
- Not saved across restarts (the mount is set up again each session).

### 3.3 When it is ready

The model is **ready** when there are at least 8 samples and both spreads are
large enough:

- *turn* spread — the axis-2 directions `R_i b` must not all be nearly the
  same: the middle eigenvalue of `Σ (R_i b)(R_i b)ᵀ / N` ≥ 0.05 (about a 40°
  turn of axis 1 between the extremes);
- *tilt* spread — the axis-1 direction seen from the camera `R_iᵀ a` must
  vary: the middle eigenvalue of `Σ (R_iᵀ a)(R_iᵀ a)ᵀ / N` ≥ 0.02 (about
  20° on axis 2);

and the fit is good: rms of `asin(a · R_i b)` ≤ 0.5° (non-square axes, common on
Dobsonians, show up as residual) and the angle between
`a` and its nominal direction ≤ 15°.

### 3.4 Guidance

While ready, `a` replaces the zenith (alt-az) or the pole (equatorial) in the
guidance: the image directions of the axes are taken towards `a`, and the
per-axis moves are computed in the mount's own frame (pointing and target are
rotated by the smallest rotation that takes `a` to the nominal axis, then
converted to alt/az or HA/Dec as before). The near-zenith / near-pole warning
uses the same frame.

### 3.5 Wire format

`/ws` payload, inside `mount`:

```json
"model": {
  "state": "off" | "collecting" | "ready",
  "samples": 5,
  "needed": 8,
  "hint": "turn" | "tilt" | null,
  "tilt_deg": 1.21,
  "low_side_az_deg": 47.0,
  "polar_alt_error_deg": null,
  "polar_az_error_deg": null,
  "rms_deg": 0.04,
  "applied": true
}
```

- `off`: no location (the model needs one in both modes). Other fields 0/null.
- `collecting`: `hint` names the missing spread once there are at least 3
  samples (`turn` first if both are missing), else null. Numbers null.
- `ready`: alt-az fills `tilt_deg` (angle between `a` and the zenith) and
  `low_side_az_deg` (azimuth `a` leans towards — that side of the base is
  low); equatorial fills `polar_alt_error_deg` (altitude of `a` minus the
  pole's altitude; + = axis too high) and `polar_az_error_deg` (+ = east of
  the pole, in both hemispheres). `applied` is true.
- `POST /api/mount/model/reset` → 204, clears the samples.

### 3.6 UI (Settings sheet, Mount section, under the mount type control)

A small block titled **Mount model (experimental)**:

- `off`: "Set your location so Starlock can learn how your mount sits."
- `collecting`: "Learning your mount: 5 of 8 positions." plus a second line
  - alt-az hint `turn`: "Next, turn the base to a new direction."
  - alt-az hint `tilt`: "Next, raise or lower the tube."
  - eq hint `turn`: "Next, swing to a new right ascension."
  - eq hint `tilt`: "Next, move to a new declination."
  - no hint: "Keep pointing at different heights and directions."
- `ready`, alt-az: tilt < 0.2°: "The base is level (within 0.2°)." Else
  "The base tilts 1.2°, low side NE. Guidance corrects for it." (one decimal;
  16-point name of `low_side_az_deg`).
- `ready`, equatorial: both errors < 0.1°: "The polar axis is on the pole
  (within 0.1°)." Else "The polar axis is 0.8° too low and 0.5° west of the
  pole. Guidance corrects for it." (each part with its own sign word: too
  high/too low, east/west; a part under 0.1° is left out.)
- A text button **Reset** when `samples > 0`: posts
  `/api/mount/model/reset`.
- Hidden when the payload has no `mount.model` (older engine).
