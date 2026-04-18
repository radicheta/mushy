---
phase: 17-alert-engine-signal
plan: "01"
subsystem: infra
tags: [jest, node, docker, signal, alerter, scaffolding, networking]

requires:
  - phase: 16-system-health-panel
    provides: sensor_health WS broadcast shape + bridge /health endpoint (consumed by alerter fixtures)

provides:
  - src/agents/alerter/ Node 20 project skeleton (package.json, jest.config.js, Dockerfile, .dockerignore, README.md)
  - Bridge message fixtures (9 canned WS shapes: humidity, humidifier, sensor_health, /health payload)
  - fake-signal-server test helper (POST /v2/send, GET /v1/receive, GET /v1/accounts on ephemeral port)
  - Jest smoke test passing (2/2) — Wave 0 scaffold validated
  - Networking topology probe result: PASS — extra_hosts strategy validated on mushy_default

affects: [17-02, 17-03, 17-04, 17-05]

tech-stack:
  added: [jest@29.7.0, ws@8.16.0, pg@8.20.0]
  patterns:
    - "src/agents/ top-level dir for all elder-plops autonomous services (D-08)"
    - "fake-signal-server uses Node http built-ins only — no external test deps"
    - "TDD RED->GREEN flow: smoke test committed failing, then fixtures + helper implemented"

key-files:
  created:
    - src/agents/alerter/package.json
    - src/agents/alerter/jest.config.js
    - src/agents/alerter/Dockerfile
    - src/agents/alerter/.dockerignore
    - src/agents/alerter/README.md
    - src/agents/alerter/test/smoke.test.js
    - src/agents/alerter/test/fixtures/bridge-messages.js
    - src/agents/alerter/test/helpers/fake-signal-server.js
  modified:
    - .gitignore (added src/agents/*/node_modules/ and package-lock.json exclusions)

key-decisions:
  - "Used Node built-ins only (http module) for fake-signal-server — no external test deps, consistent with D-10 no-shared-code principle"
  - "fake-signal-server binds to 127.0.0.1 explicitly per threat T-17-05 (not 0.0.0.0)"
  - "Networking topology probe (Task 3): PASS — extra_hosts + mushy_default is the locked topology for plans 03/05"

requirements-completed: [ALRT-01]

duration: ~30min
completed: 2026-04-18
---

# Phase 17 Plan 01: Alert Engine — Wave 0 Scaffold Summary

**Node 20 alerter project skeleton + jest 2/2 passing + bridge-message/signal-cli test fixtures committed; networking topology probe PASSED — host-gateway topology locked**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-04-18
- **Completed:** 2026-04-18
- **Tasks:** 3 of 3 complete
- **Files modified:** 9

## Accomplishments

- Created `src/agents/alerter/` from scratch: package.json, Dockerfile (node:20-alpine), jest config, .dockerignore, README
- 9 bridge-message fixtures matching live bridge broadcast shapes verbatim (cross-referenced with `bridge/src/index.js` lines 347-433)
- fake-signal-server helper: ephemeral HTTP mock, POST /v2/send pushes into `sent[]`, GET /v1/receive drains `received[]`, GET /v1/accounts
- Jest smoke test: 2/2 green — fixture shapes validated + fake-signal-server send/receive cycle verified
- .gitignore updated: `src/agents/*/node_modules/` and `src/agents/*/package-lock.json` excluded
- Networking probe PASS: container on `mushy_default` reaches host-mode bridge at `host.docker.internal:8081` — extra_hosts strategy confirmed

## Task Commits

Each task was committed atomically:

1. **Task 1: Scaffold src/agents/alerter skeleton** - `4055440` (chore)
2. **Task 2 RED: Failing smoke test** - `9da3e67` (test)
3. **Task 2 GREEN: Bridge fixtures + fake-signal-server** - `1aa563c` (feat)
4. **Task 3: Networking probe PASS — README updated** - (docs)

## Files Created/Modified

- `src/agents/alerter/package.json` - mushy-alerter 0.1.0, jest/ws/pg deps
- `src/agents/alerter/jest.config.js` - node env, testMatch **/test/**/*.test.js
- `src/agents/alerter/Dockerfile` - FROM node:20-alpine, npm ci --omit=dev
- `src/agents/alerter/.dockerignore` - excludes node_modules, test, README
- `src/agents/alerter/README.md` - registration runbook, deploy, snooze grammar, two-places warning, env-var table, networking topology (validated)
- `src/agents/alerter/test/smoke.test.js` - 2-test Wave 0 smoke suite
- `src/agents/alerter/test/fixtures/bridge-messages.js` - 9 canned bridge WS shapes
- `src/agents/alerter/test/helpers/fake-signal-server.js` - minimal Node http mock server
- `.gitignore` - agent node_modules exclusion rules

## Decisions Made

- Used Node `http` built-ins only for fake-signal-server (no express, no extra deps) — consistent with D-10 no-shared-code and keeps test harness dependency-free
- fake-signal-server binds `127.0.0.1` explicitly per threat T-17-05 mitigation
- `pg` declared in dependencies per D-09 (unused in Phase 17 runtime; seeded for future Timescale promotion)
- **Networking topology locked (Task 3 PASS):** alerter uses `extra_hosts: [host.docker.internal:host-gateway]` on `mushy_default` network; host-mode fallback is not needed

## Deviations from Plan

None — plan executed exactly as written.

## Task 3: Networking Topology Probe — PASS

**Type:** checkpoint:human-verify
**Status:** COMPLETE — PASS

Probe run 2026-04-18 on elder-plops. The bridge runs `network_mode: host` on port 8081. The alerter container joined `mushy_default` with `--add-host=host.docker.internal:host-gateway` and successfully reached the bridge `/health` endpoint.

### Probe Command

```bash
docker run --rm \
  --add-host=host.docker.internal:host-gateway \
  --network=mushy_default \
  alpine:3.19 sh -c 'apk add --no-cache curl >/dev/null && curl -sf http://host.docker.internal:8081/health | head -c 200'
```

### Probe Output (PASS)

```json
{"status":"ok","db":true,"ros":{"connected":true},"camera":{"lastFrame":...},"humidifier":{"last_msg_ts":...}}
```

### Locked Topology (Plans 03/05)

Plans 02-05 proceed with:
- `extra_hosts: ["host.docker.internal:host-gateway"]` on alerter compose service
- `BRIDGE_WS_URL=ws://host.docker.internal:8081`
- `SIGNAL_API_URL=http://signal-cli:8080` (internal compose network)

Host-mode fallback path is **not needed** — do not implement it.

## Issues Encountered

None

## Threat Model Compliance

- T-17-03: README uses `+1XXXXXXXXXX` placeholder — no real phone numbers committed
- T-17-04: Dockerfile uses `node:20-alpine` (pinned, not `:latest`); `npm ci --omit=dev` (jest excluded from image)
- T-17-05: fake-signal-server binds `127.0.0.1` only

## Next Phase Readiness

- Wave 0 scaffold complete and green — Plans 02–05 can proceed (networking topology locked)
- No blockers

---
*Phase: 17-alert-engine-signal*
*Completed: 2026-04-18*
