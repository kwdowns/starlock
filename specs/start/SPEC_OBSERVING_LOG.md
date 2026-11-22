# Observing log (sessions, sightings, observations)

Status: **design proposal**, written 2026-11-22 (decisions below). Replaces the "dwell log +
CSV" model of `evf/engine/observation_log.py` with a logbook good enough
for observing-program certification. Spans the Pi (this repo), the iOS app,
Starlock Cloud and a new web app. The private repos implement from this
document; they don't copy code from here.

## Decisions (2026-11-22)

| Topic | Decision |
|---|---|
| Sign-in | **Microsoft Entra External ID** (§6). Prod data is only test data, so it's a clean switch. |
| Frames on the Pi | **Every sighting keeps its camera frame** (built: `observation_log.frames`, downscaled to 1024 px, about 60–100 kB). Frames are trimmed **oldest first** past a local quota (`frame_quota_mb`, default 2 GB on the Pi 4) or when free disk falls under `min_free_mb` (default 1 GB); the entries themselves stay. So a note added later can still pick up a picture. |
| Frames in the cloud | Only frames **attached** to an observation or note upload. The log sheet has an **"Upload finder capture with log"** box, ticked by default; untick to keep the frame local only. |
| Observing programs | Not now. |
| Images | Only Starlock camera frames. No sketching, user photos or scans for now. |

## 1. Goals

A log entry must be able to carry what certifying programs (Astronomical
League, RASC and similar) ask for:

- **Object:** name, catalogue id, constellation.
- **Date and time:** UT, also shown in local time.
- **Location:** latitude and longitude, or a named site.
- **Sky conditions:** seeing and transparency ratings.
- **Equipment:** instrument, magnification, filters.
- **Description:** what was seen (shape, brightness, structure, field),
  not just "found it".

Plus:

- **Equipment:** a saved gear library, with one-tap changes mid-session.
- **Quick notes**, many per observation, added at the eyepiece or later.
- **Editable everything,** because auto-identification and remembered
  equipment are sometimes wrong. History is kept, not overwritten.
- **Exports:** JSON, a printable PDF, OAL, AAVSO visual, CSV.
- **Same features everywhere:** the Pi's web UI (browser-only users), the
  apps and the web app at `my.starlock.app` (name not final).
- **Accounts are optional.** Everything works without one; the cloud
  account adds sync between devices and a backup.

Not now (maybe later, if users ask): sketching, user-uploaded photos or
scanned sketches. The only image source is a frame from the Starlock camera.

## 2. Entities

All ids are UUIDv7 (time-ordered, made on whichever device creates the
record, so nothing needs a server to create). Times are UTC with
milliseconds.

| Entity | Fields (main ones) | Made by |
|---|---|---|
| **Logbook** | id, owner (local owner or cloud user), name | One per owner |
| **Site** | id, name, lat, lon, elevation, Bortle (optional) | Saved by the user; a session's site defaults to the nearest saved one within 1 km, else a new unnamed one |
| **Equipment** | id, kind (`telescope`, `eyepiece`, `barlow`, `reducer`, `filter`, `binoculars`, `finder`, `camera`), name, and per kind: aperture mm, focal length mm, type (Dob, refractor, SCT…); eyepiece focal length mm and apparent field °; Barlow/reducer factor; filter type (UHC, OIII, H-beta, colour…); binocular magnification × aperture; retired flag | User's gear library |
| **Session** | id, start, end, site, observers (free text), notes | Starts at the first log action of the night (or by hand); ends after 4 h of inactivity or by hand. Can be renamed, merged and split |
| **Setup change** | id, session, at, telescope, eyepiece, Barlows/reducers, filters | One tap on the session's equipment chip. Magnification = telescope focal length × Barlow factors ÷ eyepiece focal length; true field = apparent field ÷ magnification |
| **Conditions** | id, session, at, seeing 1–5 (Antoniadi-style, 1 = best, with words), transparency 1–5, limiting magnitude (optional), temperature/humidity/wind (optional) | Set at the start of the night and changed whenever. Moon phase and altitude, sun altitude (twilight) are **computed** at export, not stored |
| **Sighting** | id, session, object (auto-identified), start, end, mean pointing RA/Dec, separation | Automatic, from the engine's dwell tracker (today's log entries). The raw trail |
| **Observation** | id, session, object (§2.1), start, end (optional), seen (`yes`, `no`, `uncertain`), description, rating (optional), program tags, equipment and conditions (resolved from the setup and conditions in force at `start`, overridable per observation), sightings linked, frames | Deliberate: **Log** while on target, promote a sighting, or add by hand (naked eye, binoculars, or when the Pi wasn't used) |
| **Note** | id, session, observation (optional), at, text, frame (optional) | The Note button, dictation, the Watch. Attaches to the **open** observation if there is one |
| **Measurement** | id, observation, kind `variable-star` (star, estimated magnitude, comparison stars, chart id, flags, AAVSO fields) | A kind of observation detail; more kinds later (double-star separation, meteor counts) |
| **Frame** | id, at, JPEG (max 1024 px long side, about 60–100 kB), plate-solve centre and field | Kept by the Pi with every sighting (rolling local quota); attached to an observation or note with the "Upload finder capture with log" box (ticked by default) |

### 2.1 Object identity

`object = {catalog, id, name, constellation, raJ2000, decJ2000}`, for
example `{"catalog": "M", "id": "42", "name": "Orion Nebula",
"constellation": "Ori"}`. Auto-identified from the target or the nearest
catalogue object to the pointing; the user can pick another object (the
Trapezium instead of M42) or type a free-text one (comet, planet). The
constellation is computed from RA/Dec. Planets, the Moon and comets are
free-text in phase 1.

### 2.2 Open observation

At most one observation is **open** per session. **Log** opens a new one
(closing the previous). Notes go to the open observation. Moving off target
does **not** close it; the sighting trail just shows a gap. It closes when
you log the next one, tap Done, or the session ends.

## 3. Storage and sync

### 3.1 Edits are events

Every change is an append-only **event**:
`{id, entity, entityId, op (create|set|delete|link|unlink), field, value, at (hybrid logical clock), author (device + user), source (auto|user)}`.

- Current state = fold of the events; the latest `at` wins per field.
- **Edit history comes free:** "auto-identified as M42 → changed to
  Trapezium 23:14 by Kyle's iPhone" is just two events. Exports can include
  it; certifiers like seeing corrections rather than silent rewrites.
- **Sync = swap missing events** (by id). No conflicts beyond "latest per
  field", deletes are tombstones. Works offline, merges cleanly.
- Hybrid logical clocks (wall time + counter + device) keep order sane when
  a device clock is off (the Pi often has no RTC; it already uses the
  client's time, `observation_log.Clock`).

### 3.2 Who stores what

| Store | Holds | Notes |
|---|---|---|
| **Pi** (SQLite next to config.json) | Its owner's logbook (events + frames), plus sightings | Serves the web UI and the apps over the LAN: `GET /api/logbook/events?after=…`, `POST /api/logbook/events`, `GET /api/frames/{id}.jpg`. Owner-only once owner tokens exist (SPEC_FIRST_RUN §7.2) |
| **App** (on the phone) | The user's logbook | Works with no Pi and no account. Syncs with the Pi when it's the Pi's owner, and with the cloud when signed in |
| **Cloud** | The user's logbook | Per user (partition key = user id). Synced by the app, the web app, and the Pi (with its device credential, on behalf of the account that linked it) |
| **Web app** | Nothing durable | Reads and writes the cloud |

Shared telescope: a **guest's** app logs to the guest's own logbook and only
reads sightings and frames from the Pi. The owner's logbook never reaches
a guest.

### 3.3 Today's data

The existing `observations` table becomes **sightings** (same dwell rules:
1° for 30 s). Already-synced cloud entries migrate to sightings. The CSV
export stays (sightings, or observations, chosen in the dialog).

## 4. Images and the free tier

- Only Starlock camera frames, re-encoded on the Pi (1024 px, quality 80),
  so no user files, no EXIF and no GPS metadata from phones.
- **Quota per account:** 100 MB when the account is created, plus 100 MB
  per month of account age, up to 1 GB. Counted on frames only; text events
  are tiny but limited separately (below). When full: new frames stay on
  the Pi/phone and aren't uploaded; the app says so.
- **Uploads** go straight to blob storage through a short-lived, size-capped
  upload URL (SAS, 2 MB max, `image/jpeg`); the cloud checks the JPEG and
  counts it, and rejects anything else.
- **Rate limits:** per account (e.g. 5,000 events and 500 frames a day),
  per device credential, per IP (already exists), plus a daily cost alarm.
- **App Attest** (iOS) / Play Integrity (Android) on app requests; the Pi
  uses its device credential; the web app relies on account limits.
- Frames are deleted with the observation or note that owns them; account
  deletion deletes everything.

Rough cost: 1,000 active users × 100 MB a year ≈ 100 GB of hot blob
storage, a few dollars a month. Downloads cost more than storage; cache
frames on devices.

## 5. Exports

| Format | Content |
|---|---|
| **JSON** | Lossless: `{schema: "starlock-logbook/1", sites, equipment, sessions: [{setups, conditions, observations, notes, sightings}], history (optional)}`. A JSON Schema is published with the spec. |
| **PDF** | Printable log: a header per session (date, site, lat/lon, conditions, moon, equipment), one block per observation (object, UT and local time, instrument, magnification, filters, seeing/transparency, description, notes, frame thumbnail if any). Optional program filter ("Messier only") and "include edit history". Letter and A4. |
| **OAL** | OpenAstronomyLog 2.x XML (sessions, observations, sites, scopes, eyepieces, lenses, filters), for other logging tools. |
| **AAVSO** | Visual-estimate file format for variable-star measurements. |
| **CSV** | One row per observation or sighting, for spreadsheets. |

Exports are made on the device (Pi, app or web app) from the logbook; the
cloud never needs to render PDFs.

## 6. Sign-in (decided: Entra External ID)

Needs: Pi web page (plain HTTP on a LAN address), the iOS app, Android
later, and the web app.

**Considered first, not chosen:** keep Starlock Cloud's own token service (already built:
access + rotating refresh tokens) and add providers to it:

- **Apple** (native on iOS, Sign in with Apple JS on the web, which needs an
  Apple Services ID), **Google** (native on Android, Google Identity
  Services on the web and iOS), later **email codes** or passkeys. Each
  provider proves the user to `POST /v1/auth/{provider}`; the cloud issues
  its own tokens. A signed-in user can add more providers to one account
  (no automatic merging by email: Apple hides it).
- **The Pi's web page** can't take part in OAuth redirects (providers won't
  redirect to `http://192.168.x.x`), so it uses a **device code flow**: the
  page shows "Go to my.starlock.app/link and enter BCDF-GHJK"; you sign in
  there with any provider and approve; the Pi gets its device credential.
  The same flow lets the Pi page link to an account without the app.
- On the web app, the session is an httpOnly cookie held by the cloud (no
  tokens in browser storage).

**Chosen:** Microsoft Entra External ID (Azure AD B2C's successor;
first 50,000 monthly active users free; Google, Facebook, Apple, email and
password, MFA, hosted sign-in pages). Picked because those needs will come and it's
cheapest to start on it. The Pi's web page still links with the Pi-initiated
code flow above, which is the cloud's own and independent of the provider. Costs: browser-sheet sign-in in
the apps instead of the native Apple button, hosted pages to brand, and a
migration of today's Apple users. Duende IdentityServer is not recommended
(licence for a commercial product, and we'd run it ourselves).

## 7. User interface

- **iOS** (iOS 18 `TabView`, sidebar on iPad): **Scope** (with Note and
  Log buttons), **Targets** (plus program lists and progress), **Session**
  (tonight's timeline, conditions and equipment chips), **Logbook** (past
  sessions, by object, programs, exports, gear library; also from the
  connect screen with no Pi). Watch: dictated note, "Log". Live Activity:
  Log button (App Intent).
- **Pi web UI:** the same features (browser-only users get the full
  logbook): a Session panel under the step area and a Logbook page.
- **Web app:** Logbook and gear library, editing, exports.

## 8. Phases

| # | Work | Repos |
|---|---|---|
| 1 | Event log store + entities + migration of today's log to sightings; LAN API; frames | pushnav |
| 2 | Pi web UI: gear library, session panel (setup/conditions chips, Log, Note), observation editor, logbook, JSON/PDF/CSV export | pushnav |
| 3 | iOS: tabs (started 2026-11-22), local logbook store, Session and Logbook tabs, editors, exports, Pi sync | starlock-ios |
| 4 | Cloud: events API, frames via blob + quota, rate limits, App Attest; app and Pi sync | starlock-cloud, all |
| 5 | Sign-in providers + device code flow; web app (my.starlock.app) | starlock-cloud, new web repo |
| 6 | OAL and AAVSO exports, program lists and progress, Watch and Live Activity actions | all |

## 9. Open questions

1. How much of the logbook the apps rebuild vs. hand to the web app (an
   "Open my logbook" button to `my.starlock.app`, or to the Pi's own page
   for users without an account).
2. Web app name: `my.starlock.app`, `app.starlock.app` or `log.starlock.app`.
