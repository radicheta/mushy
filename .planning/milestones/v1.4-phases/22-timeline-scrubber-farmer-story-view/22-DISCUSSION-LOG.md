# Phase 22: Timeline scrubber + farmer story view — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-19
**Phase:** 22-timeline-scrubber-farmer-story-view
**Areas discussed:** Delivery surface, Frame delivery path, Joined data shape, Burn-in pipeline

---

## Delivery surface

User was shown (multi-select gray-area picker):
- Delivery surface
- Frame delivery path
- Scrub interaction
- Sensor overlay treatment

User selected all four. Before Claude asked the scoped delivery-surface
question, user volunteered:

> "i think this belongs in the farmer app, on zoy side on the farmos project.
> maybe mushy serves the data but others consume it"

**Captured decision:** Farmer UI delegated to farmOS/Zoy-side. Mushy =
data surface only. Consistent with Phase 18 D-01. The **Scrub interaction**
and **Sensor overlay treatment** gray areas dropped from mushy's CONTEXT
(they become farmOS-side decisions).

---

## Frame delivery path

| Option | Description | Selected |
|--------|-------------|----------|
| GET /camera/frame?at=<iso>&camera_id=fc1 | Bridge resolves closest snapshot row, streams JPEG with proper headers. Single URL per frame. Hides /data/snapshots layout. | ✓ |
| Expose /data/snapshots as static | Simpler, but leaks filesystem layout into the API contract. | |
| Base64 thumbnails inside /camera/history | No round-trips, but blows up JSON size. | |

**User's choice:** `GET /camera/frame?at=<iso>&camera_id=fc1`.

---

## Joined data (snapshots + sensors)

Claude asked: server-side join vs separate endpoints vs `?include=sensors` flag.

User response:

> "can be separate, but i do think saved snapshots should have all info
> burnt in RH, CO2 Temp Hum state etc"

**Captured decisions:**
1. Keep endpoints separate — farmOS composes client-side (D-04).
2. Additionally: persisted snapshots should have sensor values burnt
   into the image pixels ("burn-in"). This was a new gray area the user
   surfaced organically. Pivoted the rest of the conversation to it.

---

## Burn-in content

| Option | Description | Selected |
|--------|-------------|----------|
| Bottom bar: timestamp · RH · T · CO2 · humidifier | One-line dark strip across the bottom. Security-cam idiom. | ✓ |
| Top-left HUD chip | Less intrusive but harder to read on a phone. | |
| Two-line bottom bar (adds sensor_health line 2) | More info density; risks clutter. | |

**User's choice:** Bottom bar with timestamp · RH · T · CO2 · humidifier.

---

## Burn site (Pi-side vs bridge-side)

User asked (mid-discussion):

> "what if burn-ins are on the pi side, and come already baked in on the stream?"

Claude surfaced Phase 24 ML concern: Pi-side burn poisons raw pixels for
ComfyUI/SAM2 training. Presented four options:

| Option | Description | Selected |
|--------|-------------|----------|
| Pi-side in fc_camera — stream burnt end-to-end | Consistent live+history. Compromises Phase 24 ML. New sensor subs on Pi. Pi deploys to iterate. | |
| Bridge-side sidecar (raw + burnt in parallel) | Two files per frame; burnt path served to farmer, raw preserved for ML. ~55 MB/year extra. | ✓ |
| Bridge-side in-place (only burnt persisted) | Simplest; loses raw forever. | |
| Pi-side separate burnt topic | Two ROS topics; extra Pi CPU + bandwidth. | |

**User's choice:** Bridge-side sidecar. Pi-side captured as D-05 rejection
so the reasoning survives into future phases.

---

## Claude's Discretion

Delegated to planner/executor:
- JPEG library pick (`sharp` vs `jimp` vs `@napi-rs/canvas`).
- Exact bottom-bar rendering (font, padding, opacity, bar height %).
- Tolerance window for "closest frame at-or-before `at`" in `/camera/frame`.
- Whether `/camera/frame` accepts a `file_path` pass-through (path-traversal
  concern) or strictly `at=<iso>`.
- Prune-job coverage of the burnt tree (same pass vs second pass).
- Optional "burnt-pipeline healthy" bool on `/health`.
- `?raw=true` access control posture.

---

## Deferred Ideas

- Server-side join endpoint `/camera/story?from=&to=` — premature on 4G
  until profiling shows it's needed.
- Retroactive burn-in of pre-phase snapshots.
- Overlay on live `/camera/mjpeg` stream.
- Pi-side burn-in (rejected with reasoning in D-05, not lost).
- `/camera/frame` thumbnail / resized variants (`?w=...`).
- Alerter-side usage of burnt frames in Signal contamination alerts
  (belongs to Phase 24).

---

*Audit-only. See 22-CONTEXT.md for the canonical decisions.*
