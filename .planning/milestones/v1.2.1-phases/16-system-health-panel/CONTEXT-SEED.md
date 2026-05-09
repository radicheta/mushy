# Phase 16: System health panel (seed note)

**Filed:** 2026-04-17 (split out from Phase 14 discussion)
**Milestone:** v1.2.1 or v1.3 — TBD
**Status:** Seed only — proper planning via `/gsd:discuss-phase 16` later

## Origin

During Phase 14's discussion the farm team asked for "a panel with
green lights" on Mission Control. That scope was too big for a
weekend hotfix, so Phase 14 was kept narrow (two lights in the
camera panel only) and the broader ask was filed here.

## Goal (one-liner)

A dashboard-style health surface on Mission Control showing
green/yellow/red for every subsystem the farmer depends on:
camera feed, sensors (temp/humidity/CO2 each individually),
actuators (humidifier, fan, light), bridge↔Pi connection,
Pi reachability, disk space, 4G signal.

## Constraints carried forward

- **Gap over noise** (`feedback_gap_over_noise.md`) — a subsystem
  that can't report must show "unknown" (yellow/grey), not a
  false-positive green.
- **Sensor health must be impossible to miss** (per Phase 999.11
  farmer-app notes) — the SHT30-offline-for-40-minutes incident
  drove this.
- **Reusable primitives** — Phase 14's two lights should be the
  same component multiplied up, not a bespoke one-off.

## Data sources (inherited from earlier phases)

- Bridge `/health` — camera.subscribed, camera.last_frame_age_sec
  (added in Phase 14), DB reachability
- fc_core nodes — sensor publishes (age + validity), actuator
  state topics, warming-up flag (added in Phase 15)
- Pi-level — Tailscale status, disk, maybe 4G signal via modem-manager

## Scope questions for planning (do NOT answer here — save for discuss)

- Exact subsystem list and thresholds
- Mission Control widget vs standalone page
- Click-through to history / details or glance-only
- Mobile rendering (pairs with Phase 999.11 farmer app)
- Whether alerts (999.3 Signal bot) share the same health model
