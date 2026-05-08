---
phase: 29
plan: 05
subsystem: alerter
tags:
  - alerter
  - rules
  - freshness-gating
  - offline-blindness
  - 999.39
requires:
  - 29-01  # effective-config fixtures
provides:
  - rules.js freshness gate on isRhOob (D-03)
  - rules.js offline-blindness gate on isHumidifierStuck (D-04 / 999.39)
  - message.js formatProblem(pi) last-known summary line (999.39 acceptance #3)
affects:
  - src/agents/alerter/src/rules.js
  - src/agents/alerter/src/message.js
  - src/agents/alerter/test/rules.test.js
  - src/agents/alerter/test/message.test.js
tech-stack:
  added: []
  patterns:
    - gate-wrap (RESEARCH §Pattern 4 / §Pattern G) — prepend short-circuit, preserve existing math byte-identical
    - opt-in liveness inputs — pre-Phase-29 callers keep working when wsConnected/humidifierLastMsgTs omitted
key-files:
  created: []
  modified:
    - src/agents/alerter/src/rules.js
    - src/agents/alerter/src/message.js
    - src/agents/alerter/test/rules.test.js
    - src/agents/alerter/test/message.test.js
decisions:
  - D-03 freshness gate: stale → suspend isRhOob (state 2 from CONTEXT.md)
  - D-04 / 999.39 offline-blindness gate: wsConnected=false OR humidifierLastMsgTs stale → suspend isHumidifierStuck
  - Backwards-compat preserved as gate semantics: undefined liveness inputs are NOT treated as offline (gate is opt-in)
metrics:
  duration: ~15min
  completed: 2026-05-08
requirements:
  - ALRT-08
  - ALRT-09
---

# Phase 29 Plan 05: Alerter rule freshness/liveness gates + pi-alert summary Summary

Wave-2 sibling of 29-04: surgical gate-wrap on `isRhOob` (D-03 freshness) and `isHumidifierStuck` (D-04/999.39 offline-blindness) plus a `formatProblem(pi)` extension carrying last-known sample context. Closes 999.39 false-CRITICAL pathology surfaced by farmer 2026-05-07 after the 11h fc1 outage.

## What Shipped

### Task 1 — `rules.js` gates (commits `92f4670` RED, `c9b503e` GREEN)
- `isRhOob(humidity, effective)` short-circuits to `false` when `effective.freshness.state === 'stale'`. Math (`Math.abs(humidity - effective.rhTarget) > effective.rhBand`) byte-identical to pre-Phase-29.
- `isHumidifierStuck` gains opt-in `wsConnected` and `humidifierLastMsgTs` keyword args. Three new short-circuits before existing math:
  - `wsConnected === false` → `false`
  - `humidifierLastMsgTs === null` → `false`
  - `humidifierLastMsgTs` defined and older than `sensorOfflineMin` minutes → `false`
- Backwards-compat: legacy callers that omit liveness inputs get `undefined` (not `false`/`null`), bypassing the gates and reaching the unchanged math. Pre-Phase-29 tests pass without modification.
- 9 new tests in `Phase 29 — freshness gating + offline blindness` describe block. All pre-existing `rules.test.js` tests still green.

### Task 2 — `message.js` pi-alert summary (commits `9b9f5ca` RED, `a99b9c7` GREEN)
- `formatProblem({alertType: 'pi', fields: {lastSeenMs, lastKnown}})` emits `Last sample: RH X% · T Y°C · humidifier ON/OFF` when `lastKnown` provided, plus `(captured Nm ago)` if `lastKnown.tsMs != null`. Omits cleanly when `lastKnown` is null.
- 5 new tests in `Phase 29 — pi alert last-known summary (999.39)` describe block. All pre-existing `message.test.js` tests still green; dashboardUrl-once invariant preserved.

## Verification

| Check | Result |
|-------|--------|
| `npx jest test/rules.test.js` | 22/22 PASS (13 pre-existing + 9 new) |
| `npx jest test/message.test.js` | 12/12 PASS (7 pre-existing + 5 new) |
| Combined: 34/34 across modified suites | PASS |
| `grep -c "freshness.state === 'stale'" rules.js` | 1 |
| `grep -c "wsConnected === false" rules.js` | 1 |
| `grep -c "humidifierLastMsgTs" rules.js` | 3 (destructure + null check + stale check) |
| `grep -c "Math.abs(humidity - effective.rhTarget) > effective.rhBand" rules.js` | 1 (math preserved) |
| `grep -c "rhRise < 3.0" rules.js` | 1 (humidifier math preserved) |
| `grep -c "Last sample:" message.js` | 1 |
| `grep -c "lastKnown" message.js` | 5 |

## Deviations from Plan

None — plan executed as written.

## Notes for Downstream Plans

- **Caller wiring is 29-04's scope:** state.js must populate `fields.lastKnown` from `state.currentRh / currentTemp / humidifierOnSinceMs ? 'ON' : 'OFF' / lastRhMsgTs` at pi-alert call sites. 29-05 only owns the receive-side consumption of `fields.lastKnown`.
- **Liveness inputs to `isHumidifierStuck` are 29-04's scope at call sites:** new state.js `transition()` for humidifier alert path MUST pass `wsConnected` and `humidifierLastMsgTs` keyword args. Without them the gates degrade gracefully (backwards-compat) but the 999.39 fix is inert.
- 999.39 manual reproduction (disconnect WS, verify isHumidifierStuck does NOT fire) is deferred to plan 29-07 smoke test on fc1.

## Commits

| Phase | Hash | Message |
|-------|------|---------|
| RED Task 1 | `92f4670` | test(29-05): add failing tests for rules freshness/liveness gates |
| GREEN Task 1 | `c9b503e` | feat(29-05): gate isRhOob and isHumidifierStuck on freshness/liveness |
| RED Task 2 | `9b9f5ca` | test(29-05): add failing tests for pi alert last-known summary (999.39) |
| GREEN Task 2 | `a99b9c7` | feat(29-05): extend formatProblem(pi) with last-known summary line |

## Self-Check

All 4 commits exist in `git log`; all 4 modified files exist on disk with the required grep markers.

## Self-Check: PASSED
