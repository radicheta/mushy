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
affects: [12-camera-daily-report, 13-farmos-telemetry]

# Tech tracking
tech-stack:
  added: [docker-compose-v2 (pending install)]
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

patterns-established:
  - "docker compose (space syntax) is the v2 command — replace all docker-compose (hyphen) references in docs"
  - "Container names use hyphens: mushy-bridge-1, mushy-openmct-1, mushy-timescale-1"

requirements-completed: []  # INFRA-01, INFRA-02, INFRA-03 are partially complete — runtime cutover (Task 2) blocked on sudo auth gate

# Metrics
duration: 15min
completed: 2026-04-12
---

# Phase 11 Plan 01: Compose v2 Upgrade Summary

**Compose files and all docs updated for docker compose v2 syntax and hyphen container names; runtime install/cutover blocked on sudo auth gate**

## Performance

- **Duration:** ~15 min (Task 1 complete; Task 2 blocked)
- **Started:** 2026-04-12T23:30:00Z
- **Completed:** 2026-04-12T23:43:54Z (partial — Task 1 only)
- **Tasks:** 1 of 3 (Task 2 auth-gated, Task 3 depends on Task 2)
- **Files modified:** 5

## Accomplishments

- Removed `version: '3.8'` from both compose files — v2 plugin requires no top-level version field
- Updated CLAUDE.md Running Services section from `docker-compose` to `docker compose` (v2 space syntax)
- Updated docs/OPERATIONS.md container names from `mushy_openmct_1` / `mushy_bridge_1` to `mushy-openmct-1` / `mushy-bridge-1`
- Updated docs/pi-setup/tailscale-setup.md bridge exec reference and reconnect command to v2 syntax

## Task Commits

1. **Task 1: Remove deprecated version field and update docs for compose v2** - `bdd5107` (chore)

## Files Created/Modified

- `docker-compose.yml` - Removed `version: '3.8'` top-level field; file now starts with `services:`
- `docker-compose.override.yml` - Removed `version: '3.8'` top-level field; file now starts with comment
- `CLAUDE.md` - Updated Running Services commands to `docker compose` (space); updated Integration Testing line
- `docs/OPERATIONS.md` - Updated architecture diagram and recovery procedure 5.4 with hyphen container names
- `docs/pi-setup/tailscale-setup.md` - Updated bridge container name in exec command; updated bridge reconnect command to use `docker compose rm -sf` + `docker compose up -d --build`

## Decisions Made

- Updated tailscale-setup.md line 62 to include `--build` flag in the reconnect command, matching CLAUDE.md guidance that bridge rebuilds require `--build`. The original plan spec said to add `--build bridge` and that was applied.
- `docker-compose.yml` filename references in CLAUDE.md (e.g., "Live compose is `/docker-compose.yml`") left as-is — these are filename references, not commands.

## Deviations from Plan

None — Task 1 executed exactly as written.

## Issues Encountered

**Task 2 blocked: sudo auth gate**

Task 2 requires `sudo apt install docker-compose-v2` and `sudo apt purge docker-compose` (v1 removal). The agent cannot provide a sudo password in this non-interactive environment. `sudo -n` fails with "a password is required".

- `docker-compose v1 version`: 1.29.2 (confirmed running)
- `docker-compose-v2` apt candidate: 2.40.3+ds1-0ubuntu1~22.04.1 (confirmed available)
- Current containers: mushy_bridge_1, mushy_timescale_1, mushy_openmct_1 (v1 underscore names)
- Named volume: mushy_timescale-data (confirmed exists, data safe)
- No system-level docker-compose references in /etc/systemd/ or shell profiles

**To complete Task 2, operator must run:**
```bash
cd /mnt/slime-kingdom/opt/mushy
sudo apt install -y docker-compose-v2
docker compose version    # verify: Docker Compose version v2.40.x
sudo apt purge -y docker-compose
which docker-compose && echo "FAIL: v1 still on PATH" || echo "PASS: v1 removed"
docker compose down
docker compose up -d --build bridge
docker compose up -d --remove-orphans
docker rm mushy_bridge_1 mushy_openmct_1 mushy_timescale_1 2>/dev/null || true
docker compose ps
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080
docker compose logs --tail=20 bridge
```

## Known Stubs

None — documentation changes are complete and accurate. Runtime cutover is pending operator action (Task 2).

## Next Phase Readiness

- Task 1 complete: all docs and compose files are v2-ready (no version field, correct command syntax)
- Task 2 blocked: operator must install docker-compose-v2 and perform container recreation
- Task 3: human verification of live telemetry — depends on Task 2 completion
- Phases 12 and 13 can proceed once Task 2/3 confirm the stack is healthy under v2

---
*Phase: 11-compose-v2-upgrade*
*Completed: 2026-04-12 (partial — Task 1 only)*
