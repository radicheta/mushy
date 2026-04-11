---
phase: 05-production-deployment
plan: "02"
subsystem: infra
tags: [deploy, systemd, tailscale, soak-test, production]

requires:
  - phase: 05-production-deployment/01
    provides: Production config (target_humidity 0.80), OPERATIONS.md, grower checklist
  - phase: 04-observability-integration
    provides: OpenMCT dashboard, actuator state publisher, end-to-end hardware validation
provides:
  - Production deployment of fc-core on FC-1 Pi at the farm
  - 24-hour soak test validation (PENDING — human checkpoint)
  - MVP declaration (PENDING — awaiting soak results)
affects: [phase-7-historical-data, phase-8-farmos]

tech-stack:
  added: []
  patterns: [tailscale-remote-deploy]

key-files:
  created: []
  modified:
    - scripts/pi-deploy/deploy.sh

key-decisions:
  - "Deploy via Tailscale (100.96.239.75) — Pi is at the farm, not on LAN"
  - "fc1/prod branch fast-forwarded to milestone/fc1-humidity-mvp HEAD before deploy — picked up fc1/ namespace, 180s dwell, OpenMCT fixes"

patterns-established:
  - "Remote deploy via Tailscale: PI_HOST=100.96.239.75 ./scripts/pi-deploy/deploy.sh"

requirements-completed: []  # DEPL-01 pending 24h soak test

duration: 10min
completed: pending
status: checkpoint-waiting
checkpoint: human-verify (24h soak test started 2026-04-06T17:45:00-03:00)
---

# Phase 05 Plan 02: Deploy to FC-1 and Production Soak Test

**Production config deployed to FC-1 at the farm via Tailscale — 24h soak test in progress**

## Performance

- **Duration:** ~10 min (Task 1 complete, Task 2 awaiting 24h elapsed time)
- **Started:** 2026-04-06T17:35:00-03:00
- **Completed:** pending (soak test in progress)
- **Tasks:** 1/2 complete
- **Files modified:** 0 (deploy only, no code changes)

## Accomplishments
- fc1/prod branch synced with milestone/fc1-humidity-mvp (6 commits: fc1/ namespace, 180s dwell, OpenMCT fixes, timezone, git-deploy)
- Deployed to FC-1 via Tailscale (Pi at the farm, LAN unreachable)
- Verified: target_humidity 0.80, service active+enabled, NRestarts=0
- Live readings confirmed: 20.5C, 78.9% humidity, 462ppm CO2 — within target band

## Task Commits

1. **Task 1: Deploy updated config to FC-1 and verify** — no commit (deploy-only, no code changes)
2. **Task 2: 24-hour soak test and production declaration** — PENDING (human checkpoint)

## Deployment Verification

| Check | Result |
|-------|--------|
| target_humidity on Pi | 0.80 |
| systemctl is-active | active |
| systemctl is-enabled | enabled |
| NRestarts | 0 |
| Sensor readings | 20.5C, 78.9%, 462ppm |
| Humidity in band | Yes (75-85%) |

## Decisions Made
- Deployed via Tailscale IP (100.96.239.75) since Pi is at the farm, not on LAN (10.68.155.53 unreachable)
- Fast-forwarded fc1/prod to include all milestone changes before deploy

## Deviations from Plan
- Used `PI_HOST=100.96.239.75` instead of default fc1 hostname — Pi at farm, only reachable via Tailscale

## Issues Encountered
- Initial deploy failed: `ssh fc1` resolved to LAN IP 10.68.155.53 which returned "No route to host"
- Fixed by deploying via Tailscale IP: `PI_HOST=100.96.239.75 ./scripts/pi-deploy/deploy.sh`

## Next Phase Readiness
- BLOCKED on 24h soak test completion (started 2026-04-06 ~20:40 UYT)
- After soak passes: declare MVP complete, mark DEPL-01 satisfied
- Phase 7 (historical data) and Phase 8 (FarmOS) can proceed after MVP declaration

---
*Phase: 05-production-deployment*
*Deploy completed: 2026-04-06*
*Soak test: in progress*
