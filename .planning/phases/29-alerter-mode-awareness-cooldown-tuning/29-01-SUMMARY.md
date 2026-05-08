---
phase: 29
plan: 01
subsystem: alerter, bridge
tags: [alerter, bridge, allowlist, test-scaffolding, wave-0]
requires:
  - Phase 28 SetParameters allowlist (control_param.js) shipped
provides:
  - bridge ALLOWLIST entries for Tier B per-mode alerter keys + Tier C globals
  - reusable jest fixtures: effective-config (fresh/stale/cold) + bridge envelopes
    (currentModeMsg, alerterOverridesMsg, alerterGlobalsMsg)
affects:
  - downstream plans 29-02 (bridge subscriptions), 29-03 (controller validator),
    29-04 (alerter resolveEffectiveConfig), 29-05 (rules.js gating)
tech-stack:
  added: []
  patterns:
    - entryIntRange validator (mirrors entryDoubleRange; integer-only via Number.isInteger)
key-files:
  created:
    - src/agents/alerter/test/fixtures/effective-config.js
  modified:
    - src/mission-control/bridge/src/control_param.js
    - src/mission-control/bridge/test/control_param.test.js
    - src/agents/alerter/test/fixtures/bridge-messages.js
decisions:
  - "Tier B keys (5) added per declared mode -> 10 alerter keys total in ALLOWLIST"
  - "Tier C globals registered as integer-typed runtime-mutable params"
  - "entryIntRange rejects fractional doubles outright (T-29-01 defense-in-depth)"
metrics:
  duration: ~25min
  completed: 2026-05-08
  tasks: 2/2
  commits: 3
---

# Phase 29 Plan 01: Wave 0 scaffolding (allowlist + fixtures) Summary

Extended the bridge SetParameters allowlist with the 10 Tier B per-mode alerter dotted-keys and 4 Tier C global keys Phase 29 will introduce, and added reusable jest fixtures for effective-config and the three new bridge WS envelopes. Resolves RESEARCH.md Open Question 1 (ALLOWLIST is a hardcoded enum, not regex/prefix) and stands up shared test scaffolding so plans 04/05 do not each re-invent it.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | Add failing tests for Phase 29 ALRT allowlist keys | `5cb37a0` | bridge/test/control_param.test.js |
| 1 (GREEN) | Extend bridge allowlist with Tier B/C alerter keys | `8b7aeb3` | bridge/src/control_param.js |
| 2 | Add jest fixtures for effective-config + bridge envelopes | `2812350` | alerter/test/fixtures/{effective-config.js,bridge-messages.js} |

## Verification

- `cd src/mission-control/bridge && npx jest test/control_param.test.js` — 75/75 pass (61 pre-existing + 14 new + 1 bonus T-29-01 case)
- Fixture probe `node -e ...` — prints `{"fresh":true,"stale":"stale","cold":"cold","cm":true,"ov":true,"gl":true,"oldStillThere":true}` (pre-existing fixture exports preserved verbatim)
- `Object.keys(ALLOWLIST).filter(k => k.includes('alerter')).length` — returns `10` (5 Tier B keys × 2 modes)
- 4 Tier C global keys registered: `pi_offline_min`, `sensor_offline_min`, `heartbeat_hour`, `max_sends_per_hour`

## Decisions Made

- **D-A: `entryIntRange` strict-integer validator.** Rejects fractional doubles (e.g. `5.5`) outright instead of letting `Math.trunc` silently truncate them at the wire layer (line 113). This is T-29-01 defense in depth — if a client sends `5.5` and we truncated to `5`, the bridge would log success while the rclpy controller validator (29-03) would reject — a confusing inconsistency.
- **D-B: Pre-existing `bridge-messages.js` exports preserved verbatim.** Restructured the file into named consts then re-exported the original 9 keys plus 3 new factories. Zero downstream breakage.
- **D-C: Pitfall 5 — `t_target` default is `null` not `NaN` in fixture.** `JSON.stringify(NaN) === 'null'`; bridge emits `null` on the wire even though controller publishes NaN. Fixture matches WS shape, not ROS shape.

## Deviations from Plan

- **Acceptance-criterion grep mismatch (Rule 1 — minor).** Plan acceptance criterion `grep -c "modes\.fruiting\.alerter\." src/mission-control/bridge/src/control_param.js` expects ≥5 literal occurrences, but the implementation uses a `for (const m of DECLARED_MODES)` loop with `${m}` template literals (mirroring the existing pattern at line 86-92 for `target_humidity` etc.). Runtime verification (`Object.keys(...).filter(k => k.includes('alerter')).length === 10`) confirms the 10 keys exist. The grep criterion was overly literal; the runtime test is the load-bearing check.

No other deviations. Plan executed exactly as written.

## Deferred Issues

Pre-existing (NOT introduced by this plan, NOT fixed per scope-boundary rule):

- `src/agents/alerter/test/config.test.js` — 1 failing test (`returns object with all fields populated from defaults`)
- `src/agents/alerter/test/integration.test.js` — 3 failing tests (end_to_end_rh_problem_and_recovery, warmup_blocks_rh_alert, snooze_mutes_while_active)

Verified pre-existing via `git stash && npx jest <files>` reproducing identical failures at `8b7aeb3` HEAD before Task 2's commit. Filed to phase deferred-items.md if not already tracked.

## Threat Flags

None. Phase 29 plan 01 introduces no new network surface — only extends an existing allowlist (T-29-01 mitigated per plan threat model via `entryIntRange` integer enforcement).

## Self-Check: PASSED

- FOUND: src/mission-control/bridge/src/control_param.js (modified)
- FOUND: src/mission-control/bridge/test/control_param.test.js (modified)
- FOUND: src/agents/alerter/test/fixtures/effective-config.js (created)
- FOUND: src/agents/alerter/test/fixtures/bridge-messages.js (modified)
- FOUND commit: 5cb37a0 (RED tests)
- FOUND commit: 8b7aeb3 (GREEN allowlist)
- FOUND commit: 2812350 (fixtures)
