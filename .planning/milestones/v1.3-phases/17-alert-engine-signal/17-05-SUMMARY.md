---
phase: 17-alert-engine-signal
plan: "05"
subsystem: deploy
tags: [docker, compose, signal-cli, alerter, deploy, signal, uat]

requires:
  - plan: 17-04
    provides: complete alerter Node 20 code (84/84 tests passing)

provides:
  - docker-compose.override.yml: alerter + signal-cli-rest-api services wired
  - .env.example: all alerter env vars documented with defaults and two-places warning
  - src/agents/alerter/README.md: Deployment + Registration section (Steps 1-5)
  - signal-cli container running on elder-plops (awaiting registration)
  - alerter image built; alerter ready to start once SIGNAL_SENDER/SIGNAL_RECIPIENT set

affects: []

tech-stack:
  added:
    - bbernhard/signal-cli-rest-api:0.200-dev (json-rpc-native mode)
  patterns:
    - "signal-cli internal-only on signal-net — not published to host (D-13)"
    - "alerter reaches bridge via extra_hosts host-gateway, not compose network"
    - "named volume signal-cli-data at /home/.local/share/signal-cli (Pitfall 9 avoidance)"
    - "alerter refuses to start without SIGNAL_SENDER/SIGNAL_RECIPIENT (config.js mustEnv)"

key-files:
  created:
    - .env.example
  modified:
    - docker-compose.override.yml
    - src/agents/alerter/README.md

decisions:
  - "alerter joins only signal-net (not mushy_default) — bridge reachable via extra_hosts host-gateway, no compose network needed"
  - "signal-cli port 8085 not published to host per D-13 (internal-only); registration curl goes through docker exec or signal-net container"
  - "alerter stopped (not removed) until SIGNAL_SENDER/SIGNAL_RECIPIENT added to .env after farmer Signal registration"

metrics:
  duration: ~25min
  completed: "2026-04-18"
  tasks: 3 of 3 (Task 3 UAT passed 2026-04-19 — farmer-attested)
  files: 3
---

# Phase 17 Plan 05: Deploy + Signal Registration Summary

**One-liner:** alerter + signal-cli-rest-api (0.200-dev, json-rpc-native) wired in docker-compose.override.yml and deployed on elder-plops; signal-cli up and healthy; alerter image built and validated; Task 3 (farmer Signal UAT) pending registration.

## Performance

- **Duration:** ~25 min
- **Started:** 2026-04-18
- **Completed:** 2026-04-18 (Tasks 1-2); Task 3 UAT passed 2026-04-19 (farmer-attested)
- **Tasks:** 3 of 3 complete
- **Files modified:** 3

## Accomplishments

### Task 1: Compose wiring + documentation

- `docker-compose.override.yml`: added `signal-cli` service (bbernhard/signal-cli-rest-api:0.200-dev, json-rpc-native mode, signal-cli-data named volume, signal-net network) and `alerter` service (builds from src/agents/alerter, extra_hosts host-gateway, all ALERT_* env vars forwarded from .env, signal-net network, depends_on signal-cli)
- `.env.example` created: all env vars documented — TIMESCALE_PASSWORD, CORS_ORIGIN, FARMOS_*, SIGNAL_SENDER (required), SIGNAL_RECIPIENT (required), and all ALERT_* with defaults and the two-places-warning for RH target/band
- `src/agents/alerter/README.md`: new "Deployment + Registration" section with Step 1-5 end-to-end flow (set env, start containers, captcha + SMS registration, restart alerter, farmer UAT)

### Task 2: Deploy + smoke test

- Signal-cli pulled (bbernhard/signal-cli-rest-api:0.200-dev) and started on signal-net
- Alerter image built successfully from src/agents/alerter/Dockerfile (node:20-alpine, npm ci --omit=dev)
- Signal-cli health verified: `GET /v1/accounts` returns `[]` (up, healthy, awaiting registration)
- Alerter correctly refuses to start without SIGNAL_SENDER/SIGNAL_RECIPIENT (mustEnv in config.js) — expected behavior; alerter is stopped, will start clean after registration

## Task Commits

1. **Task 1: Compose wiring, .env.example, README deployment section** — `8190674`
2. **Task 1 fix: Remove undefined mushy_default network ref** — `a1e8247`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] mushy_default network undefined in compose project**
- **Found during:** Task 2, first deploy attempt
- **Issue:** `alerter` service referenced `mushy_default` network, which exists as a Docker network but is not declared in docker-compose.yml or override.yml — compose cannot resolve an undeclared external network
- **Fix:** Removed `mushy_default` from alerter's networks list. Alerter reaches bridge via `extra_hosts: host-gateway` (validated in Plan 01 topology probe), not through a compose network. Only `signal-net` is needed.
- **Files modified:** `docker-compose.override.yml`
- **Commit:** `a1e8247`

## Task 3: Farmer Signal UAT — PASSED 2026-04-19

**Status:** Farmer-attested. Alert delivery confirmed end-to-end; farmer reported positive sentiment ("loves it").

Signal registration completed, alerter connected, PROBLEM/RECOVERY/HEARTBEAT messages delivering as designed.

## Known Stubs

None. All compose wiring is live. Signal-cli is running. Alerter will start immediately once SIGNAL_SENDER and SIGNAL_RECIPIENT are set in .env.

## Threat Surface Scan

- signal-cli port 8080 is NOT published to host per D-13 — only reachable from containers on signal-net
- signal-cli-data named volume holds Signal account private keys — not exposed to host filesystem paths
- No new Tailscale-served or LAN-published endpoints introduced

## Self-Check: PASSED

Files verified:
- docker-compose.override.yml: FOUND (signal-cli + alerter services present)
- .env.example: FOUND
- src/agents/alerter/README.md: FOUND (Deployment + Registration section present)

Commits verified:
- 8190674: FOUND (feat(17-05): wire alerter + signal-cli compose services)
- a1e8247: FOUND (fix(17-05): remove mushy_default network ref)

Runtime verified:
- mushy-signal-cli-1: Up, health: starting → healthy, /v1/accounts returns []
- mushy-alerter-1: Stopped (correctly refuses to start without SIGNAL_SENDER/SIGNAL_RECIPIENT)
