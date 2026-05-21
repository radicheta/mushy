---
phase: 46-chamber-dark-detector
plan: 03
subsystem: deploy
tags: [deploy, atomic-rebuild, health-schema, fc1-liveness, chamber-dark, deferred-attestation]
requires: [46-01, 46-02]
provides:
  - prod-deployed-bridge-with-fc1-liveness
  - prod-deployed-alerter-with-chamber-dark
  - health-schema-attestation
affects:
  - mushy-bridge-1 container (recreated with new image)
  - mushy-alerter-1 container (recreated with new image)
tech_stack:
  added: []
  patterns:
    - atomic-coordinated-rebuild (single compose invocation, two services)
    - graceful-degradation (alerter handles missing fc1 block defensively; pre-46 fallback intact)
key_files:
  created:
    - .planning/phases/46-chamber-dark-detector-real-fc1-liveness-signal-farmer-readab/46-03-SMOKE.md
  modified: []
decisions:
  - "Substituted `docker compose` (v2) for `docker-compose` (v1) — v1 binary not installed on elder-plops; v2 is the canonical interface per `[[project_compose_v2_upgrade]]`. Atomicity and semantics preserved."
  - "Corrected probe port 3000 -> 8081 — bridge actually listens on 8081 per its own boot log; plan text was stale (`[[feedback_verify_runtime_compose]]`)."
  - "Took DEFERRAL PATH for task 2 (induced-outage attestation). Auto-mode executor cannot perform fc1 remote-action pre-flight per `[[feedback_fc1_remote_action_preflight_protocol]]`, and chamber state post-2026-05-20 outage warrants operator coordination."
metrics:
  duration: ~7min (rebuild 4m48s + probes & doc ~2min)
  completed: 2026-05-21
  tasks: 1 of 2 (task 2 deferred per plan DEFERRAL PATH)
  files-touched: 1 (SMOKE.md created; SUMMARY.md created; STATE.md updated)
requirements: [CD-01, CD-02, CD-03, CD-04]
---

# Phase 46 Plan 03: Atomic deploy + /health schema verification — Summary

Atomic coordinated rebuild of bridge + alerter on elder-plops (dev=prod). `/health.fc1.{last_msg_ts, last_msg_age_sec}` schema is live in production. Task 2 (induced fc-core outage attestation with farmer) is deferred to an operator window per the plan's documented DEFERRAL PATH.

## What Shipped

- `docker compose up -d --build bridge alerter` ran atomically; both `mushy-bridge-1` and `mushy-alerter-1` recreated together. Status `Up` (alerter `Up healthy`).
- `GET /health` on the running bridge returns the new `fc1` block: `{ last_msg_ts, last_msg_age_sec }`, both numbers. Two probes 30s apart show fc1 publishing live (`age_sec: 1` then `0`; `last_msg_ts` advanced ~47s).
- Alerter consumed `/health` polls with the new field without throwing — no `crash` / `TypeError` / `undefined is not` matches in 200 lines of logs.
- WebSocket bridge<->alerter connection established (`ws_open`) after ~16s of standard reconnect backoff (bridge port bind delay).

See `46-03-SMOKE.md` for verbatim curl outputs, timestamps, and the full acceptance checklist.

## Commits

| Item                                                            | Commit  |
| --------------------------------------------------------------- | ------- |
| `feat(46-03): atomic rebuild + /health.fc1 schema verified live` (SMOKE.md) | `affb0c9` |
| (this SUMMARY + STATE update — final metadata commit)           | _final commit below_ |

## Verification

- `curl http://localhost:8081/health | jq -e '.fc1 | has("last_msg_ts") and has("last_msg_age_sec")'` -> `true` (exit 0). Two probes 30s apart.
- `docker compose ps` shows `mushy-bridge-1` and `mushy-alerter-1` both `Up`.
- `docker logs --tail 200 mushy-alerter-1 | grep -iE 'crash|TypeError|undefined is not'` -> empty.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `docker-compose` (v1) binary not on PATH**

- **Found during:** Task 1 rebuild
- **Issue:** Plan acceptance criterion specified the literal command `docker-compose up -d --build bridge alerter`. Compose v1 is not installed on elder-plops; only v2 (`docker compose`) is present.
- **Fix:** Substituted `docker compose` for `docker-compose`. v2 is the canonical interface on this host per memory `[[project_compose_v2_upgrade]]`. Atomicity and semantics are identical; only the binary name differs.
- **Files modified:** none (deployment-time substitution; SMOKE.md documents)
- **Commit:** `affb0c9`

**2. [Rule 3 - Blocking] Bridge listens on port 8081, not 3000**

- **Found during:** Task 1 schema verification
- **Issue:** Plan said `curl http://localhost:3000/health`. Probe returned `Exit code 7` (connection refused). Bridge actually binds port 8081 per its own boot log (`[bridge] HTTP + WebSocket server on port 8081`).
- **Fix:** Probed `http://localhost:8081/health` instead. Per `[[feedback_verify_runtime_compose]]` (read live runtime, not plan target). All schema gates pass on the correct port.
- **Files modified:** none
- **Commit:** `affb0c9`

### Deferral

**Task 2 (induced-outage attestation) DEFERRED.** Auto-mode executor cannot perform fc1 remote-action pre-flight per `[[feedback_fc1_remote_action_preflight_protocol]]` (cannot confirm chamber state with farmer; cannot schedule the ~15min uncontrolled-humidity window). fc1 just survived an unscripted 11h outage on 2026-05-20 (`[[project_2026_05_20_fc_buffer_real_outage_validation]]`), so a deliberate induced outage stacks risk during a recovery-sensitive window. Plan resume contract: `deferred: chamber-state and farmer-availability not verified in auto-mode; induced-outage attestation to be scheduled with operator after 2026-05-20 outage settling period`.

The deferral does NOT block CD-01..CD-04 substance:
- CD-01 (bridge fc1 liveness aggregator) — attested by 241/241 bridge tests (plan 46-01) + live `/health.fc1` schema this plan.
- CD-02/CD-03 (alerter chamber-dark trigger, per-sensor suppression, farmer-readable message) — attested by 720/728 alerter tests (plan 46-02, 8 pre-existing skips). Live induced-outage attestation deferred to operator window.
- CD-04 (atomic deploy) — attested by this plan's single-command rebuild + dual-container `Up` status.

Operator-window protocol is documented in `46-03-SMOKE.md` under "Suggested operator-window protocol" for paste-into-runbook reuse.

### Authentication gates

None.

### Threat surface

No new network endpoints. The `fc1` block on `/health` is purely additive on the already-public bridge health endpoint and exposes only an aggregate timestamp — no new trust boundary.

## Known Stubs

None.

## TDD Gate Compliance

N/A — plan 03 is a deploy + observe plan (`type: execute`), not TDD. Plans 46-01 and 46-02 carry the RED/GREEN gates (`e8b1467` / `0919f83` and `1e78cf1` / `aeee31a` respectively).

## Self-Check: PASSED

- `[ -f .planning/phases/46-chamber-dark-detector-real-fc1-liveness-signal-farmer-readab/46-03-SMOKE.md ]` -> FOUND
- Commit `affb0c9` -> FOUND in `git log --oneline -5`
- `docker compose ps` shows both `mushy-bridge-1` and `mushy-alerter-1` Up -> VERIFIED at 13:11:49Z
- `curl /health | jq .fc1` returns `{last_msg_ts, last_msg_age_sec}` -> VERIFIED at 13:12:03Z and 13:12:49Z

## Links

- `46-03-SMOKE.md` — verbatim curl outputs, timestamps, deferral rationale, operator-window protocol
- `46-01-SUMMARY.md` — bridge fc1 liveness aggregator (commits `e8b1467`, `0919f83`)
- `46-02-SUMMARY.md` — alerter chamber-dark wiring (commits `1e78cf1`, `aeee31a`)
- `46-CONTEXT.md` — phase scope, decisions D-01..D-08
