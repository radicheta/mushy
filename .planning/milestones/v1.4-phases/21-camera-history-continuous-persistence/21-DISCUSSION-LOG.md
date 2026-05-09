# Phase 21: Camera history continuous persistence - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or
> execution agents. Decisions are captured in CONTEXT.md — this log
> preserves the alternatives considered.

**Date:** 2026-04-19
**Phase:** 21-camera-history-continuous-persistence
**Areas discussed:** Persister architecture, Idle rate + bandwidth,
Schema + retention + storage, Active vs idle + demo artifact

---

## Gray area selection

| Option | Description | Selected |
|--------|-------------|----------|
| Persister architecture | Who captures idle frames | ✓ |
| Idle rate + bandwidth budget | Cadence during no-viewers | ✓ |
| Schema + retention + storage | Timescale snapshots table shape, retention | ✓ |
| Active vs idle + demo artifact | Decoupling + v1.4 demo requirement | ✓ |

---

## Persister architecture

| Option | Description | Selected |
|--------|-------------|----------|
| Bridge trickle-subscribe | Bridge keeps low-rate sub alive at 0 viewers. Simplest. ~0.8 MB/day extra at 1/hr. | ✓ |
| Pi-side ring buffer | fc_camera writes local history, syncs to elder-plops. Composes with 999.1. | |
| Archivist subscriber on elder-plops | Separate container subscribes independently. Clean decoupling. | |

**Rationale:** one-process model, reuses existing `saveSnapshot()` and
`pool`, keeps 4G cost negligible.

---

## Idle rate + bandwidth

| Option | Description | Selected |
|--------|-------------|----------|
| 1/5min | ~9 MB/day, 288 points/day. Good granularity for event debugging. | ✓ |
| 1/15min | ~3 MB/day, matches current SNAPSHOT_INTERVAL_MIN. | |
| 1/hr | ~0.8 MB/day, 24 points/day — too sparse. | |
| Configurable param, default TBD | Expose as env var. | |

**Rationale:** 3× cheaper than pre-Phase-12 workaround, dense enough
for scrubber to catch 30-min events.

---

## Schema + storage

**User question mid-discussion:** "is other info like RH, CO2 already
included?" — Answered: yes, `telemetry` hypertable already has it,
scrubber joins by time. No denormalization needed.

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal index (captured_at, camera_id, file_path, bytes) | Fastest to ship. | |
| Index + source tag + fps | Lets scrubber / time-lapse filter by source. | ✓ |
| Index + source + sha256 | Dedupe for future stall protection. | |

**Rationale:** small cost, avoids a future migration when Phase 23
time-lapse wants to filter "idle only" or "viewer only".

---

## Retention

| Option | Description | Selected |
|--------|-------------|----------|
| 90 days then prune | ~1.5–3 GB. | |
| 30 days then prune | ~500 MB – 1 GB. | |
| Forever until disk pressure | No scheduled prune. | |
| 1 year then prune (user free-text) | Full mushroom season + review. | ✓ |

**User's choice:** "one year then prune" — captured as D-04.

---

## Viewer-connected cadence

| Option | Description | Selected |
|--------|-------------|----------|
| Decouple — same 5-min cadence always | Uniform scrubber. | ✓ |
| Persist every Nth viewer frame | Dense "watching" regions, sparse elsewhere. | |
| Persist every viewer frame | Full 1 fps archive. | |

**Rationale:** farmer's stated preference (see
`feedback_no_sparklines.md`) for uniform/annotated timelines over
dense-where-watched mosaics.

---

## Demo artifact

| Option | Description | Selected |
|--------|-------------|----------|
| Health chip: frames_last_24h + oldest_frame | Farmer-visible regression signal. | |
| Read-only API endpoint GET /camera/history | Plumbing for Phase 22. | |
| Both — endpoint + health chip | | ✓ |

**Rationale:** endpoint unblocks Phase 22, chip gives farmer/operator a
trust signal. Stronger acceptance bar.

---

## Claude's Discretion

- Exact prune cadence (daily vs hourly, in-process vs cron)
- Health chip UI styling in the Phase 16 panel
- Backfill of pre-phase `/data/snapshots/` files (vs ship-from-now)
- Response pagination on `/camera/history`

---

## Deferred Ideas

- Pi-side ring buffer / 999.1 edge-buffering composition
- Dedicated archivist subscriber on elder-plops
- sha256 dedupe
- Multi-chamber camera_id wiring (999.6)
- BLOB-in-DB (rejected)
