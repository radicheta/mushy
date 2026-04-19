---
phase: 21-camera-history-continuous-persistence
plan: 01
subsystem: testing
tags: [jest, node20, smoke-test, bridge, docker-compose-v2]

requires:
  - phase: 18-farmer-dashboard-api
    provides: bridge Express endpoint conventions (/farmer/summary style)
provides:
  - jest 29.x test runner wired into the mission-control bridge
  - test/ directory scaffold ready for unit tests in Plans 02/03
  - scripts/verify/phase-21-smoke.sh — runtime-stack smoke for Phase 21 artifacts
affects: [21-02, 21-03, 21-04]

tech-stack:
  added: [jest@^29.7.0 (devDependency)]
  patterns:
    - "Bridge tests live under src/mission-control/bridge/test/*.test.js"
    - "Live-stack smokes under scripts/verify/ (compose v2, repo-root compose only)"

key-files:
  created:
    - src/mission-control/bridge/jest.config.js
    - src/mission-control/bridge/test/.gitkeep
    - src/mission-control/bridge/package-lock.json
    - scripts/verify/phase-21-smoke.sh
  modified:
    - src/mission-control/bridge/package.json

key-decisions:
  - "jest pinned to ^29.7.0 — Node 20 LTS compatible (Dockerfile line 12); jest 30 requires newer Node"
  - "npm install --ignore-scripts on host — rclnodejs native addon needs ROS sourced, which the host lacks; prod image still runs full install inside Dockerfile where ROS is present"
  - "Smoke script is pre-tolerant of missing /camera/history and snapshots table so it is safe to run after any of Plans 01–04"
  - "Docker compose v2 syntax (`docker compose`) per elder-plops memory — not v1 (`docker-compose`)"

patterns-established:
  - "Pattern: test/*.test.js path discovered by jest; .gitkeep preserves empty scaffold dir"
  - "Pattern: smoke scripts assert repo-root compose exists ([ -f docker-compose.yml ]) and refuse to run from src/"

requirements-completed: []

duration: ~3 min
completed: 2026-04-19
---

# Phase 21 Plan 01: Wave 0 test infrastructure Summary

**jest 29.x wired into the mission-control bridge with test/ scaffold and a runtime-compose smoke script — unblocks unit tests in Plans 02 and 03.**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-04-19T15:15:54Z
- **Completed:** 2026-04-19T15:18:19Z
- **Tasks:** 2
- **Files modified:** 5 (4 created + 1 modified)

## Accomplishments

- jest 29.7.x installed as devDependency with committed package-lock.json (install provenance for Docker build)
- `npm test` / `npx jest --passWithNoTests` exits 0 on the current empty suite
- Minimal `jest.config.js` (node test env, `test/**/*.test.js` pattern, verbose)
- `scripts/verify/phase-21-smoke.sh` — executable, bash -n clean, curls /health + /camera/history, probes snapshots table via docker compose v2

## Task Commits

1. **Task 1: Install jest 29.x and add test scaffold** — `ee2e558` (chore)
2. **Task 2: Create phase-21 live-stack smoke script** — `6fe8516` (chore)

## Files Created/Modified

- `src/mission-control/bridge/package.json` — added `"test": "jest"` script and `jest@^29.7.0` devDependency
- `src/mission-control/bridge/package-lock.json` — created (install provenance, locks jest + transitive tree)
- `src/mission-control/bridge/jest.config.js` — minimal node-env jest config
- `src/mission-control/bridge/test/.gitkeep` — preserves empty test/ dir for Plans 02/03 unit tests
- `scripts/verify/phase-21-smoke.sh` — live-stack smoke (executable, docker compose v2, port 8081)

## Decisions Made

- **`--ignore-scripts` on host install** — elder-plops host has no ROS installation, so `rclnodejs` post-install `node-gyp rebuild` fails. `--ignore-scripts` lets jest install cleanly without rebuilding native ROS bindings we do not exercise in jest tests. The prod Dockerfile still runs full `npm install --production` with ROS sourced, so runtime is unaffected.
- **jest major version locked to ^29.7.0** — Dockerfile line 12 installs Node 20 LTS. jest 30 requires Node 18.20+ but has breaking config changes; 29.7.0 is the last safe Node 20 release with the config shape used here.
- **Smoke script tolerant of partial Phase 21 state** — script exits 0 when `/camera/history` 404s or `snapshots` table is missing; it only fails on infrastructure errors (bridge unreachable, docker missing). This lets the same script be used at any point during Plans 01–04.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Used `--ignore-scripts` during jest devDependency install**
- **Found during:** Task 1 (`npm install --save-dev jest@^29.7.0`)
- **Issue:** Plan said to run `npm install --save-dev jest@^29.7.0` from the bridge dir. That triggers npm's default post-install hooks, which for `rclnodejs` run `node-gyp rebuild`. `node-gyp` calls `scripts/ros_distro.js` which requires ROS to be sourced (`AMENT_PREFIX_PATH`). elder-plops host has no ROS (ROS only lives inside the bridge container), so the install failed with `Unable to detect ROS`.
- **Fix:** Reran with `npm install --save-dev --ignore-scripts jest@^29.7.0`. Jest is pure JS — no build step needed. The prod Docker build still runs `npm install --production` with ROS sourced inside the container, so the rclnodejs native addon continues to build correctly at image-build time.
- **Files modified:** `src/mission-control/bridge/package.json`, `src/mission-control/bridge/package-lock.json`
- **Verification:** `cd src/mission-control/bridge && npx jest --passWithNoTests` exits 0. package-lock.json contains jest + transitive deps.
- **Committed in:** `ee2e558` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** No scope change. Dev-host install semantics only; prod image path unaffected.

## Issues Encountered

- None beyond the deviation above. Both tasks passed all automated verify checks on the first successful attempt.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `wave_0_complete` can flip to `true` in `.planning/phases/21-camera-history-continuous-persistence/21-VALIDATION.md` frontmatter (orchestrator owns that edit).
- Plan 02 can now author `test/snapshot.test.js`; Plan 03 can author `test/retention.test.js` and `test/history.test.js` — both will be picked up by the configured `testMatch`.
- Smoke script is ready but currently pre-Plan-02/03: running it today returns 404 for `/camera/history` and "snapshots table not yet created" (expected and non-fatal).

## Self-Check: PASSED

- FOUND: src/mission-control/bridge/package.json (modified, contains "jest" + "test": "jest")
- FOUND: src/mission-control/bridge/package-lock.json (4808 lines, jest locked)
- FOUND: src/mission-control/bridge/jest.config.js (5 lines, node env)
- FOUND: src/mission-control/bridge/test/.gitkeep (empty)
- FOUND: scripts/verify/phase-21-smoke.sh (executable, bash -n clean)
- FOUND: commit ee2e558 (Task 1)
- FOUND: commit 6fe8516 (Task 2)

---
*Phase: 21-camera-history-continuous-persistence*
*Completed: 2026-04-19*
