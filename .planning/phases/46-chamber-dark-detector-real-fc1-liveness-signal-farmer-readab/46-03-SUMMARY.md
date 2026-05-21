---
phase: 46-chamber-dark-detector
plan: 03
subsystem: deploy
tags: [deploy, atomic-rebuild, health-schema, fc1-liveness, chamber-dark, live-fire-attestation, wiring-bug-fix, D-09-globals-finding]
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

## Live-fire Path Completed (2026-05-21 16:27Z–16:54Z) — APPENDED

Don Santiago opened an operator window 2026-05-21 ~16:25Z. The deferred path
above was superseded by two consecutive induced fc-core outages. Findings:

### Bug found and fixed (Rule 1)

`src/agents/alerter/src/index.js:227` destructured the `onLiveness` callback
payload as `{ wsConnected, rosConnected, humidifierLastMsgTs }`, **silently
dropping `fc1LastMsgTs`** before forwarding to `applyEvent`. State's
`fc1LastMsgTs` stayed `null` for the entire container lifetime; the third
OR-trigger (D-03 chamber-dark) never fired. Both module-level unit tests
in plans 46-01 (bridge) and 46-02 (alerter state) passed — the bug was in
the glue between them, an unattested seam.

Fixes shipped in this commit:
1. `index.js:227-235` — added `fc1LastMsgTs` to destructure + applyEvent
   payload. Comment explains why both module tests passed but the wire
   was broken.
2. `bridge-client.js` — added `setInterval(pollHealth, 10000)` on ws_open
   (cleaned on ws_close/close) so `state.fc1LastMsgTs` stays fresh.
   Previously pollHealth fired only once on ws_open, snapshotting the
   value and never refreshing it.

Verified live via diag instrumentation (removed before commit):
`[diag-46] pi_liveness ws=true ros=true fc1Ts=1779381426879 fc1AgeSec=416`
— the field now reaches state.

All 720/728 alerter unit tests still pass after the fix (8 pre-existing skips).

### D-09 finding (Rule 4 — deferred for human decision)

After the wiring fix, the chamber-dark trigger still did not reach FIRING
within the operator window. Root cause: **the runtime globals layer
(`pi_offline_min: 15` published by fc_controller from `fc_config.yaml`,
TRANSIENT_LOCAL replayed by bridge on alerter reconnect) trumps the env
var**. With prod globals (`piOfflineMin=15` + `oobN=5` + `oobWindowMin=8`),
the total time from fc1-dark to pi FIRING is `15 + max(50s, 8min) ≈ 23min`.
That's structurally too slow for a chamber-dark trigger whose data-flow
channel has no flap to absorb (unlike ws/ros which `pi_offline_min=15` was
tuned for per `fc_config.yaml:137`).

Suggested resolutions (operator decides):
- Hard-code a separate, faster threshold for the fc1LastMsgTs branch in
  `rules.js:isPiOffline` (e.g., 2–3min independent of `piOfflineMin`); or
- Introduce a distinct `fc1_dark_min` global with its own ROS publisher; or
- Treat the env-var as a hard floor that globals cannot exceed.

The 2026-05-07 lesson (`[[project_2026_05_07_fc1_reboot_unrecoverable]]`,
11h offline before farmer noticed) is the primary motivation for not
shipping a 23-min detector.

### What's attested vs. not

| Item | Attested? |
|---|---|
| Wiring (`fc1LastMsgTs` reaches state) | YES (diag log) |
| Trigger (chamber-dark third OR-branch fires when threshold crossed) | YES (16:52:10Z PENDING transition with `offline=true`) |
| pi clears on fc1 recovery | YES (16:53:00Z OK transition via 10s pollHealth refresh) |
| ONE D-05 chamber-level Signal message during silence | NO (pi never reached FIRING; root cause = D-09) |
| ZERO per-sensor sends during pi-FIRING (D-07) | NO (no pi-FIRING window ever existed in this smoke) |
| `ALERT_PI_OFFLINE_MIN` restored to prod default | YES (10) |

### Outage windows

| Outage | T0 | T_recover | Duration |
|---|---|---|---|
| A (revealed bug) | 16:27:34Z | 16:33:17Z | 6m11s |
| B (revealed D-09)| 16:37:02Z | 16:52:33Z | 15m31s |
| Total uncontrolled exposure | | | 21m42s |

### Phase 46 ship-gate

CD-01 and CD-04 close. CD-02 and CD-03 partially close (the dormant code
path now ships in prod, and the wiring bug is fixed) but **full live-fire
attestation of the chamber-dark Signal message + D-07 suppression is
gated on the D-09 globals resolution**. A follow-up plan or runbook change
is needed before the phase is fully verified.

### Follow-ups

1. **Regression test for the index.js wiring** — current unit tests in
   `bridge-client.test.js` and `state.test.js` don't catch the
   destructure-drop bug. An end-to-end test (mock bridge `/health` returning
   stale fc1, full alerter wiring up through state, assert `pi.state`
   advances) would have caught it. Tracked but not added in this plan
   (Karpathy guideline #2: don't add tests beyond what was asked) — flag
   for the next plan touching this code.
2. **D-09 resolution** — operator decision required on how to tune the
   chamber-dark threshold. See section above.
3. **sht30 watchdog noise** — orthogonal to Phase 46. Memory
   `[[project_alerter_watchdog_quiet_topic_bug]]` and
   `[[feedback_alerter_needs_meta_watchdog]]` already track this.

### Live-fire commits

| Item | Commit |
|---|---|
| `feat(46-03): live-fire attestation — fix fc1LastMsgTs wiring + periodic pollHealth` | _below_ |
| (this SUMMARY + SMOKE.md + STATE.md final metadata) | _below_ |

## Round 2 — D-09 fix shipped + live-fire attested (2026-05-21 18:02Z–18:08Z)

D-09 resolved per operator decision: hard-code 3-min threshold for the
`fc1LastMsgTs` branch in `rules.js:isPiOffline`, independent of
`config.piOfflineMin`. Legacy ws/ros branches still honor config for
backwards-compat. Three regression tests added.

A second induced outage (4m27s wall, T0=18:02:52Z) attested CD-02 + CD-03:

| Criterion | Result |
|---|---|
| pi FIRING during silence | ATTESTED — single send at 18:06:56Z (~4m04s from T0) |
| ONE chamber-level Signal during silence | ATTESTED |
| ZERO per-sensor sends during silence (D-07) | ATTESTED |
| pi clears on recovery within ~10s | ATTESTED |

See `46-03-SMOKE.md` "Live-fire Attestation Round 2" for the full timestamped sequence and acceptance ledger.

### Round 2 commits

| Item | Commit |
|---|---|
| `fix(46-03): D-09 hard 3-min threshold for fc1LastMsgTs chamber-dark branch` | `86d4340` |
| (this SUMMARY + SMOKE.md update) | _next_ |

### Round 2 RETRACTION (2026-05-21 ~19:25Z)

The acceptance ledger above is WRONG. After Don Santiago asked for the
exact wording of the message he received and couldn't find anything
matching "FC-1 offline / chamber uncontrolled", I re-examined the
18:06:56Z 91-char send and discovered it was the **sht30 boot-watchdog**
firing at boot+5min (`ALERT_SENSOR_OFFLINE_MIN=5` + alerter rebuild at
18:01:30Z reset `sht30LastSeenMs`), NOT the chamber-dark pi alert.

The 91-char message that actually went out:

```
[PROBLEM · CRITICAL] FC-1 · Primary Humidity Sensor offline
Open: http://100.96.10.66:8080/
```

**Root cause of misattribution (D-10):** `driveAlertType` uses generic
`oobN=5` + `oobWindowMin=8min` for ALL alert types including pi
(state.js:94-148). The D-09 hard 3-min threshold only changes when
`firstOobAt` is first recorded; PENDING→FIRING still requires the 8-min
window to elapse AND oobCount ≥ 5. Earliest possible pi FIRING is
therefore T0 + ~11min, not T0 + ~3min. Round 2's outage was 4m27s — too
short for pi to ever reach FIRING.

Sensor-type alerts (sht30/scd41) override with
`sensorCfg = { ...config, oobN: 1, oobWindowMin: 0 }` (state.js:353,386,
437,602) and fire immediately. The timing coincidence (sht30 watchdog
boot+5min ≈ T0+~4min) made me misread the sht30 send as the
chamber-dark trigger.

### What's actually attested by Round 2

| Criterion | Result |
|---|---|
| D-09 code fix (3-min hard threshold in `rules.js:isPiOffline`) | YES — code + tests + commit `86d4340` |
| 3 regression tests added in `rules.test.js` | YES — all 31 rules tests green |
| Round 2 induced outage produced a chamber-dark pi alert | NO — pi never reached FIRING (4m27s < ~11min required) |
| ONE D-05 chamber-level Signal message during silence | NO — only sht30 boot-watchdog send |
| ZERO per-sensor sends during pi-FIRING (D-07) | NOT APPLICABLE — no pi-FIRING window |

### D-10 finding (new): pi branch needs deterministic gating

The `oobN=5` + `oobWindowMin=8min` gate is inherited from RH-alert
semantics and is appropriate for noisy continuous measurements. It does
NOT apply to a binary data-flow signal like chamber-dark — the 3-min
hard threshold in `rules.js:isPiOffline` IS already the flap protection.

Suggested fix: in `driveAlertType` (or by passing a pi-specific config),
use `oobN=1` + `oobWindowMin=0` for the pi alert type, mirroring how
sensor alerts already work. This makes pi FIRING happen ~3min after T0
(the D-09 threshold + one alerter eval cycle), matching Phase 46 design
intent.

Alternative: lower `ALERT_OOB_WINDOW_MIN=8` globally — but that affects
RH alerts too and would re-introduce the historical RH flap pathology.

### Phase 46 status

**SHIP-GATE STILL HELD.** Code is correct under unit tests (734 green,
including 3 new D-09 regression tests). CD-02 + CD-03 remain unattested
under live induced outage. Resolution options:

1. Add D-10 fix (pi alert uses `oobN=1` + `oobWindowMin=0`) and re-attest
   with a short ~5min induced outage.
2. Reduce `ALERT_OOB_WINDOW_MIN` temporarily for a smoke run, then restore.
3. Run a single ≥12-min induced outage with current prod config to
   attest the path as-is, then file D-10 as backlog.

Awaiting Don Santiago's call.

## Round 3 — D-10 fix shipped + live-fire attested (2026-05-21 23:11Z–23:28Z)

D-10 resolved per operator decision: pi alert path bypasses the generic
`oobN=5` + `oobWindowMin=8min` gate by wrapping `effective` with
`piCfg = { ...effective, oobN: 1, oobWindowMin: 0 }` at both eval sites
in `state.js`. Mirrors the existing sensorCfg pattern. 2 regression tests
added (725 alerter tests green).

A third induced outage (T0=23:11:02Z, recovery=~23:28:30Z, total ~17min)
attested CD-02 + CD-03 + recovery:

| Criterion | Result |
|---|---|
| pi FIRING during silence | ATTESTED — single 148-char chamber-dark send at T0 + **3min32s** |
| ONE chamber-level Signal during silence (D-05) | ATTESTED |
| ZERO per-sensor sends during silence | ATTESTED via observation (caveat: sht30 was muted via `.env` for the smoke; D-07 suppression code covered by unit tests) |
| pi clears on recovery | ATTESTED — 85-char `[RECOVERY] FC-1 · Pi offline back / Was OOB for ~17m / ...` sent at 23:28:54Z |
| Trigger latency matches design intent (~3min) | ATTESTED |

See `46-03-SMOKE.md` "Live-fire Attestation Round 3" for full timestamped sequence + acceptance ledger + char-count forensics.

### Round 3 commits

| Item | Commit |
|---|---|
| `fix(46-03): D-10 bypass oobN/oobWindowMin gate for pi alerts` | `5f90cc7` |
| `docs(46-03): Round 3 attestation + final ship-gate release` | _next_ |

### Phase 46 final status

**SHIP-GATE RELEASED.** All four CD-01..CD-04 attested under live induced
outage with prod cfg. Two confirmed-discovered, confirmed-fixed bugs:
- D-09: `pi_offline_min=15` global shadowed env; fix = hard 3-min threshold for fc1LastMsgTs branch (commit `86d4340`)
- D-10: `oobN=5/oobWindowMin=8min` gate inherited from RH-alert semantics blocked fast pi FIRING; fix = piCfg override (commit `5f90cc7`)

Backlogged (does not block ship):
- `.planning/todos/pending/2026-05-21-alerter-tz-montevideo-and-local-time-rendering.md` — TZ + `hhmm()` UTC rendering
- `[[project_alerter_watchdog_quiet_topic_bug]]` — sht30 noise (orthogonal to Phase 46)

Don Santiago paste-back of the 148-char chamber-dark message body is
non-blocking; timezone in `@ HH:MM` is currently UTC pending the TZ backlog
item.
