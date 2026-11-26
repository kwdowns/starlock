# Equipment and observing sites; Logbook page

Status: design, 2026-11-25. Builds a small part of `SPEC_OBSERVING_LOG.md`
(the gear library and sites of §2) without its event store: the library is
plain state on the Pi, like the horizon mask. The event store can absorb it
later.

The engine owns all state; the web UI and the iOS and Android apps show it
and send changes. All three apps implement the UI below the same way.

1. **Equipment page** — saved observing sites, telescopes, eyepieces and
   finders, and which of each is in use now.
2. **Site = location + horizon.** Picking a site sets the Pi's location and
   its horizon mask; the Location panel and the Horizon editor move from
   Settings to this page and edit the site in use.
3. **Optics** — with a telescope and an eyepiece in use the engine computes
   magnification, true field and exit pupil, uses the true field for "on
   target", and the apps can draw the eyepiece and finder fields on the
   live frame.
4. **Logbook page** — the apps' Session and Logbook tabs become one
   Logbook tab. Log entries record the site and equipment in use.

---

## 1. Data on the Pi

Stored in `config.json` under `observing` (validated on load; a broken
entry is dropped with a warning, never fatal):

```json
"observing": {
  "sites": [
    {"id": "…", "name": "Back yard", "latitude": 40.01, "longitude": -105.27,
     "horizon": [3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3]}
  ],
  "telescopes": [{"id": "…", "name": "8\" Dob", "aperture_mm": 203, "focal_length_mm": 1200}],
  "eyepieces":  [{"id": "…", "name": "25 mm Plössl", "focal_length_mm": 25, "afov_deg": 52}],
  "finders":    [{"id": "…", "name": "Telrad", "kind": "reflex", "rings_deg": [0.5, 2, 4]},
                 {"id": "…", "name": "8x50 RACI", "kind": "optical", "field_deg": 6}],
  "current": {"site_id": "…", "telescope_id": "…", "eyepiece_id": null, "finder_id": null}
}
```

- **ids** are made by the engine on create: 32 lowercase hex chars (uuid4).
- **Validation** (else 400 with a short reason):
  - `name`: 1–60 chars after trimming. Names need not be unique.
  - site: `latitude` −90…90, `longitude` −180…180, `horizon` as
    `SPEC_HORIZON_MOUNT_MODEL.md` §1.2 (16 ints 0–511; default `[3]*16`
    when missing).
  - telescope: `aperture_mm` 10–2000, `focal_length_mm` 50–20000.
  - eyepiece: `focal_length_mm` 1–100, `afov_deg` 20–120 (default 52).
  - finder: `kind` `optical` or `reflex`. Optical: `field_deg` 0.5–20
    (true field). Reflex (Telrad, red dot): `rings_deg` 1–4 values each
    0.1–10, ascending (default `[0.5, 2, 4]`; a red dot is `[0.1]`).
  - At most 50 items per list.
- **The site in use and the Pi's location/horizon stay in step:**
  - The engine keeps using the existing `location` and `horizon` settings
    everywhere (alt/az, Tonight, mount model, Stellarium fallback).
  - Selecting a site copies its latitude, longitude and horizon into them.
  - While a site is in use, `POST /api/settings {"location": …}` and
    `{"horizon": …}` also write into that site (so old clients and the
    existing Location panel and Horizon editor keep working). Clearing the
    location (`{"location": null}`) also clears the site in use.
  - With no site in use, location and horizon are ad hoc, as today.
- **Migration** (on load, once): no `observing` key and a location set →
  one site "My site" from the location and the current horizon, in use.
  No location → empty lists, nothing in use.
- Deleting the item in use clears that slot of `current` (deleting the site
  in use keeps the location and horizon as ad-hoc values).

## 2. API

| Request | Body | Reply |
|---|---|---|
| `POST /api/observing/{kind}` | the item without `id` | 201 `{"id": "…"}` |
| `PUT /api/observing/{kind}/{id}` | the whole item without `id` | 204; 404 unknown id |
| `DELETE /api/observing/{kind}/{id}` | — | 204; 404 unknown id |
| `POST /api/observing/current` | any of `site_id`, `telescope_id`, `eyepiece_id`, `finder_id` (a missing key leaves that slot; `null` clears it) | 204; 404 unknown id |

`{kind}` is `sites`, `telescopes`, `eyepieces` or `finders`. Editing the
site in use (PUT) re-applies its location and horizon.

`/ws` payload — always present from this engine on (clients hide the
Equipment page and keep the old Settings sections when it's missing):

```json
"observing": {
  "sites": […], "telescopes": […], "eyepieces": […], "finders": […],
  "current": {"site_id": null, "telescope_id": null, "eyepiece_id": null, "finder_id": null},
  "optics": {
    "magnification": 48.0,
    "true_field_deg": 1.08,
    "exit_pupil_mm": 4.2,
    "finder_rings_deg": [0.5, 2, 4]
  }
}
```

- `magnification` = telescope focal length ÷ eyepiece focal length;
  `true_field_deg` = eyepiece `afov_deg` ÷ magnification; `exit_pupil_mm` =
  aperture ÷ magnification. All three null unless both a telescope and an
  eyepiece are in use. Rounded to 2 decimals.
- `finder_rings_deg`: the finder in use as circles: an optical finder's
  `[field_deg]`, a reflex finder's `rings_deg`; null with no finder.

## 3. On target

`navigation.on_target_radius_deg` gains the eyepiece's true field. With
`true_field_deg` known:

    radius = min(1.5, max(0.05, 0.35 × true_field_deg, 0.3 × object size))

(the object within the middle 70 % of the eyepiece field, or well inside a
big object). Without it, the current rule is unchanged. `on_target_deg` in
the payload reports the radius in force, so the apps' on-target ring and
sound follow automatically.

## 4. Observation log

New columns on `observations` (added on open, like the cloud columns):
`site_name`, `telescope`, `eyepiece`, `finder` (TEXT, the names in use when
the entry opened) and `magnification` (REAL). They appear in
`/api/observations` entries (`site_name`, `telescope`, `eyepiece`, `finder`,
`magnification`, null when unset), in the CSV (after `longitude`) and in the
cloud upload (extra fields; the cloud ignores unknown ones).

## 5. User interface

### 5.1 Navigation

- **iOS and Android:** the tabs become **Scope, Targets, Logbook,
  Equipment** (icons: scope; star; book; for Equipment a telescope-like
  symbol — iOS `binoculars`, Android `Icons.Outlined.Construction` or the
  closest telescope-like icon). In wide windows the Equipment tab is a
  `WidePanel`/wide pane like Logbook (Scope column on the left).
- **Web UI:** a new **Equipment** sheet, opened from a top-bar button left
  of the Settings gear (label "Equipment", telescope-like icon from the icon
  set already in use). The Settings sheet's observation log section is
  renamed **Logbook**.
- **Location and Horizon** move out of Settings into the Equipment page's
  site section (all three apps). With an older engine (no `observing` in the
  payload) Settings keeps them where they are and the Equipment page/button
  shows only "Update your Starlock to save sites and equipment."

### 5.2 Equipment page

Top to bottom:

1. **In use** card:
   - Four pickers, one row each: **Site**, **Telescope**, **Eyepiece**,
     **Finder**. Each shows the item in use or "None" and offers the saved
     items plus "None". Choosing posts `/api/observing/current` at once.
   - Under them, when `optics.magnification` is set, one line:
     "48× · 1.1° field · 4.2 mm exit pupil". Magnification with no
     decimals; field with 2 decimals under 1°, else 1 decimal; exit pupil 1
     decimal. Else, muted: "Pick a telescope and an eyepiece to see the
     magnification and field."
2. **Site** section ("Site", or "Location" when no site is in use):
   - The site in use: name (tap to rename), the existing Location panel
     (coordinates, "Use this device's location", manual entry) and the
     existing Horizon editor, both editing the site in use (they post the
     same `/api/settings` calls as today).
   - With no site in use: the Location panel and Horizon editor as ad-hoc
     values, plus a button **Save as a site** (asks for a name, posts the
     site with the current location and horizon, then selects it).
   - **Saved sites** list: name and coordinates (2 decimals); tap a row to
     select it; swipe/long-press or an edit button for **Rename** and
     **Delete** (confirm: "Delete <name>? Its horizon is deleted too.").
     **Add site**: name + location (this device's location, or typed), new
     horizon default; then selected.
3. **Telescopes**, **Eyepieces**, **Finders** sections, each a list (name
   and a muted summary: telescope "203 mm aperture, 1200 mm focal length";
   eyepiece "25 mm, 52° field"; finder "Optical, 6° field" or
   "Reflex: 0.5°, 2°, 4°") with **Add**, edit (form with the fields of §1,
   numeric keyboards, units in the labels) and delete (confirm). A finder
   form has a kind switch (Optical / Reflex); reflex shows the rings as a
   comma-separated field prefilled "0.5, 2, 4".
- Empty lists show one muted line, e.g. "No eyepieces yet."
- Errors from the engine show inline under the form, short.

### 5.3 Live frame circles

- In the camera edit panel (the pencil on the frame), two switches, saved
  per device (default **Eyepiece field: on**, **Finder field: off**):
  - "Eyepiece field" — shown only when `optics.true_field_deg` is set.
  - "Finder field" — shown only when `optics.finder_rings_deg` is set.
- Drawn on the live frame overlay, centred on the telescope's pointing in
  the image (`origin_x`, `origin_y`), radius in pixels
  `(deg / 2) × image_w / fov_h_deg`:
  - eyepiece: one solid circle, 1.5 px (screen), red, 70 % opacity, with a
    small label "48×" at its upper right;
  - finder: one dashed circle per ring, 1 px, red, 45 % opacity.
  - Circles larger than the frame are simply clipped. Red only.
- Not drawn on the sky dome.

### 5.4 Logbook page (iOS and Android)

- One **Logbook** tab replaces Session and Logbook: the observation log with
  the range picker, **Tonight** selected by default (the old Session view),
  then the other ranges as today. The "coming soon" session card is
  dropped.
- Each entry row adds a muted line with the equipment when known:
  "Back yard · 8\" Dob · 25 mm Plössl (48×)" (omit missing parts; omit the
  line when all are missing).
- Web: the Settings sheet's log section is titled **Logbook**; entries (if
  listed) show the same line.
