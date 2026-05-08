---
phase: 30-time-of-day-mode-scheduling
plan: 03
subsystem: infra
tags: [config-yaml, deploy, smoke, checkpoint, schedule_windows]

requires:
  - phase: 30-01
    provides: "fc_controller scheduler timer + validator + scheduler.py module"
  - phase: 30-02
    provides: "bridge allowlist accepts schedule_windows"
provides:
  - "fc_config.yaml documents schedule_windows: \"[]\" default under fc_controller.ros__parameters"
  - "[PENDING] live deploy to fc1 + Layer 1/Layer 2 smoke evidence"
  - "[PENDING] farmer attestation"
affects: [phase-31, mission-control, farmos]

tech-stack:
  added: []
  patterns: []

key-files:
  created:
    - .planning/phases/30-time-of-day-mode-scheduling/30-03-SUMMARY.md
  modified:
    - src/chambers/fc-core/config/fc_config.yaml

key-decisions:
  - "Tasks 2–4 (deploy + live smoke + farmer attestation) gated on operator availability — left as a human-action checkpoint per Plan 30-03 frontmatter (autonomous: false)."

patterns-established: []

requirements-completed: []

duration: ~5min (Task 1 only; Tasks 2–4 pending)
completed: 2026-05-08 (Task 1)
---

# Plan 30-03: Yaml + deploy + smoke + farmer attestation — SUMMARY

**Status: Task 1 complete; Tasks 2–4 await live fc1 deploy + farmer attestation.**

## Performance

- **Duration so far:** ~5 min (Task 1 yaml edit + verify)
- **Tasks:** 1/4 complete
- **Files modified:** 1 (`fc_config.yaml`)

## Accomplishments (Task 1)

- `fc_config.yaml` declares `schedule_windows: "[]"` under `fc_controller.ros__parameters`, immediately after `modes.pinning.t_target` and before the Phase 29 alerter block.
- Yaml parse verified: `yaml.safe_load(...)['fc_controller']['ros__parameters']['schedule_windows'] == '[]'`.
- Comment documents wraparound + half-open semantics for the farmer.

## Task Commits

1. **Task 1 — yaml default:** `8c09a6a`

## Pending — human-action / human-verify

The remaining tasks were authored to require live fc1 access + farmer feedback per Plan 30-03 frontmatter (`autonomous: false`). They are blocked on operator availability:

### Task 2 — Build + deploy to fc1 + verify scheduler is live (no schedule active)
- Local sanity build (`colcon build --packages-select fc_core --symlink-install`).
- `git push` to fc1/prod.
- Bridge rebuild on elder-plops (`docker compose up -d --build bridge`).
- fc1 preflight (tailscale, default route, fc-core unit), pull, `bash scripts/pi-deploy/deploy.sh`, restart fc-core, journalctl scan for tracebacks.
- Verify `ros2 param get /fc_controller schedule_windows` → `'[]'`.
- Verify `current_mode` topic still publishes baseline `fruiting / config_default`.

### Task 3 — End-to-end smoke (Layer 1 + Layer 2 + restart survival)
- Layer 1 hot apply: POST `schedule_windows` to bridge → observe `source='scheduler'` transition in `current_mode` topic + journalctl `[scheduler] transition` INFO line.
- Layer 2 persist: POST `/control/persist` → confirm `runtime_overrides.yaml` contains the JSON STRING verbatim → restart fc-core → param survives.
- Capture all evidence to `30-03-SMOKE.md`.
- Restore baseline `schedule_windows: "[]"` before completing.

### Task 4 — Farmer attestation (human-verify checkpoint, blocking)
- Present SMOKE.md evidence + rollback recipe (`schedule_windows: "[]"` via Layer 1 + Layer 2 curl pair).
- Acceptable replies: `"approved"` (ship, schedule stays disabled), `"approved with schedule"` (real schedule live), `"issues: ..."` (open follow-up).

## Rollback Recipe (for SMOKE.md / farmer attestation prompt)

```bash
# Layer 1 (hot, in-process):
curl -X POST -H 'content-type: application/json' \
  http://elder-plops:8080/control/param \
  -d '{"node":"fc_controller","param":"schedule_windows","value":"[]"}'

# Layer 2 (persisted):
curl -X POST -H 'content-type: application/json' \
  http://elder-plops:8080/control/persist \
  -d '{"node":"fc_controller","param":"schedule_windows","value":"[]"}'
```

## Self-Check: PARTIAL

- [x] Task 1 — yaml default (committed)
- [ ] Task 2 — live deploy to fc1
- [ ] Task 3 — Layer 1/2 smoke + 30-03-SMOKE.md
- [ ] Task 4 — farmer attestation

## Farmer Attestation

[pending — awaiting Tasks 2–4 + operator response]
