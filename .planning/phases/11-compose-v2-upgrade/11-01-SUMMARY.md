---
phase: 11-compose-v2-upgrade
plan: 01
subsystem: infra
tags: [docker, docker-compose, compose-v2, elder-plops, mission-control]

# Dependency graph
requires: []
provides:
  - "Compose files stripped of deprecated version field (compose v2 compatible)"
  - "CLAUDE.md updated to docker compose v2 command syntax"
  - "docs/OPERATIONS.md updated with hyphen container names (mushy-bridge-1, mushy-openmct-1)"
  - "docs/pi-setup/tailscale-setup.md updated with v2 container name and command syntax"
  - "docker compose v2 (2.40.3) installed on elder-plops; docker-compose v1 purged"
  - "Mission Control stack (bridge, openmct, timescale) running under v2 with hyphen-named containers"
  - "Live telemetry confirmed flowing end-to-end in Mission Control after cutover"
affects: [12-camera-daily-report, 13-farmos-telemetry]

# Tech tracking
tech-stack:
  added: [docker-compose-v2 2.40.3 (jammy-updates)]
  patterns: ["docker compose (space syntax) for all compose commands", "hyphen container names: mushy-{service}-1"]

key-files:
  created: []
  modified:
    - docker-compose.yml
    - docker-compose.override.yml
    - CLAUDE.md
    - docs/OPERATIONS.md
    - docs/pi-setup/tailscale-setup.md

key-decisions:
  - "Remove version field from compose files — v2 requires no top-level version key"
  - "Container name format: mushy-{service}-1 (compose v2 hyphen naming vs v1 underscore)"
  - "Update tailscale bridge reconnect command to include --build flag per CLAUDE.md guidance"
  - "Install via apt docker-compose-v2 from jammy-updates — standard signed repo, no PPA needed"

patterns-established:
  - "docker compose (space syntax) is the v2 command — replace all docker-compose (hyphen) references in docs"
  - "Container names use hyphens: mushy-bridge-1, mushy-openmct-1, mushy-timescale-1"

requirements-completed: [INFRA-01, INFRA-02, INFRA-03]

# Metrics
duration: ~45min (across two sessions including human-action checkpoint for sudo tasks)
completed: 2026-04-12
---

# Phase 11 Plan 01: Compose v2 Upgrade Summary

**docker-compose v1 purged and replaced with compose v2 plugin (2.40.3) on elder-plops; all 3 Mission Control services running with hyphen-named containers and live telemetry confirmed flowing**

## Performance

- **Duration:** ~45 min (across two sessions; Task 2 required human operator action for sudo)
- **Started:** 2026-04-12T23:30:00Z
- **Completed:** 2026-04-12 (Task 3 human-verify complete)
- **Tasks:** 3 of 3
- **Files modified:** 5

## Accomplishments

- Removed `version: '3.8'` from both compose files — v2 plugin requires no top-level version field
- Updated CLAUDE.md Running Services section from `docker-compose` to `docker compose` (v2 space syntax)
- Updated docs/OPERATIONS.md container names from `mushy_openmct_1` / `mushy_bridge_1` to `mushy-openmct-1` / `mushy-bridge-1`
- Updated docs/pi-setup/tailscale-setup.md bridge exec reference and reconnect command to v2 syntax
- Installed docker-compose-v2 2.40.3 from jammy-updates on elder-plops
- Purged docker-compose v1 1.29.2 — binary no longer on PATH
- Recreated Mission Control stack under compose v2: mushy-bridge-1, mushy-openmct-1, mushy-timescale-1 all running
- TimescaleDB data survived container recreation (named volume preserved)
- OpenMCT confirmed accessible at :8080 (curl returns 200)
- Operator confirmed "MC is up" — Mission Control displaying live telemetry

## Task Commits

1. **Task 1: Remove deprecated version field and update docs for compose v2** - `bdd5107` (chore)
2. **Task 2: Install compose v2, purge v1, recreate stack** - host-level operations only; no code changes to commit
3. **Task 3: Verify live telemetry flows end-to-end** - visual verification; no code changes

**Plan metadata:** (this SUMMARY commit)

## Files Created/Modified

- `docker-compose.yml` - Removed `version: '3.8'` top-level field; file now starts with `services:`
- `docker-compose.override.yml` - Removed `version: '3.8'` top-level field; file now starts with comment
- `CLAUDE.md` - Updated Running Services commands to `docker compose` (space); updated Integration Testing line
- `docs/OPERATIONS.md` - Updated architecture diagram and recovery procedure 5.4 with hyphen container names
- `docs/pi-setup/tailscale-setup.md` - Updated bridge container name in exec command; updated bridge reconnect command to use `docker compose rm -sf` + `docker compose up -d --build`

## Decisions Made

- Updated tailscale-setup.md line 62 to include `--build` flag in the reconnect command, matching CLAUDE.md guidance that bridge rebuilds require `--build`.
- `docker-compose.yml` filename references in CLAUDE.md (e.g., "Live compose is `/docker-compose.yml`") left as-is — these are filename references, not commands.
- Used `apt install docker-compose-v2` from jammy-updates (standard Ubuntu signed repo) rather than downloading binary directly — cleaner package management, signed provenance.

## Deviations from Plan

None — all three tasks executed exactly as written. Task 2 required operator to provide sudo credentials (expected auth gate; documented in checkpoint).

## Issues Encountered

**Task 2: sudo auth gate (handled via human-action checkpoint)**

Task 2 required `sudo apt install docker-compose-v2` and `sudo apt purge docker-compose`. The agent cannot provide sudo credentials interactively. A human-action checkpoint was issued; the operator ran all required commands successfully:

- docker-compose-v2 2.40.3 installed from jammy-updates
- docker-compose v1 purged (confirmed "PASS: v1 removed")
- Stack recreated: mushy-bridge-1, mushy-openmct-1, mushy-timescale-1 all running
- curl localhost:8080 returns 200
- Bridge logs show healthy startup, client connections, camera snapshot timer running
- TimescaleDB bound to 127.0.0.1:5432 (data intact)

**Task 3: Mission Control confirmed "MC is up"**

Operator confirmed Mission Control is accessible and displaying data.

## Known Stubs

None — all changes are complete and the runtime stack has been verified.

## Threat Flags

None — no new network endpoints, authentication surfaces, or data processing paths introduced. Existing controls preserved (TimescaleDB bound to 127.0.0.1, CycloneDDS over Tailscale, TIMESCALE_PASSWORD from .env).

## Next Phase Readiness

- Phase 11 complete: compose v2 is the sole compose tool on elder-plops
- All Mission Control services running with v2 hyphen container names
- Docs and CLAUDE.md are accurate and consistent with runtime state
- Phases 12 (camera daily report) and 13 (FarmOS telemetry) can proceed — they inherit the v2 naming conventions

---
*Phase: 11-compose-v2-upgrade*
*Completed: 2026-04-12*
