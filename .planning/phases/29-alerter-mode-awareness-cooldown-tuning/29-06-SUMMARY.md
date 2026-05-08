---
phase: 29
plan: 06
subsystem: alerter
tags:
  - cooldown-tuning
  - analysis
  - phase-20-carry
  - alrt-10
  - one-shot
requires:
  - 29-CONTEXT.md (D-05/D-07/D-08/D-09)
  - 29-RESEARCH.md (§"Tuning Data Access", Pitfalls 7+8)
  - 29-03-SUMMARY.md (validator ranges, bootstrap defaults, 14 ROS params declared)
provides:
  - "29-COOLDOWN-TUNING.md — best-effort tuning analysis under W8 retention gate"
  - "fc_config.yaml updated with 10 Tier B + 3 Tier C tuned values"
  - "Documented future-work hook: 1-2 line patch to signal.js to emit alertType in [signal] sent"
affects:
  - "Plan 29-04/29-05 deploy ordering — sensor_offline_min=20 requires freshness gate (D-04) live first"
  - "Operator preference preservation — heartbeat_hour 17 (was 8 in 29-03 bootstrap)"
tech-stack:
  added: []
  patterns:
    - "Best-effort tuning when retention gate triggers — anchor on observed signal + architectural constraints + farmer memory; surface caveats prominently"
key-files:
  created:
    - .planning/phases/29-alerter-mode-awareness-cooldown-tuning/29-COOLDOWN-TUNING.md
  modified:
    - src/chambers/fc-core/config/fc_config.yaml
decisions:
  - "W8 retention gate triggered (12.6h window vs 14d target) — proceed with best-effort tuning rather than defer ALRT-10 indefinitely; surface gate prominently in artifact"
  - "Plan recipe `awk '/[send]/'` does not match real log shape — alerter source has no per-alertType log line; aggregate stats only"
  - "fruiting cooldown_min 45 / pinning 75 — pinning > fruiting structurally prevents D-09 swap-spam, not just relied-on"
  - "sensor_offline_min validator cap [1,60] forces dropping .env band-aid 1440; safe only after Wave-2 (29-04/29-05) ships freshness gate"
  - "heartbeat_hour 17 (not bootstrap 8) — honor farmer-attested .env setting"
metrics:
  tasks_completed: 2
  duration: ~25 min
  completed: 2026-05-08
---

# Phase 29 Plan 06: Cooldown Tuning Analysis + fc_config.yaml Commit Summary

ALRT-10 / Phase 20 carry — settle 1-year-pending farmer-gut cooldowns with best-effort
data-anchored values under an insufficient-retention gate.

## What Shipped

**29-COOLDOWN-TUNING.md** (commit `1791bad`):
- W8 retention gate triggered: actual `docker logs mushy-alerter-1` window = 12.6 h, not 14 d.
- Critical pre-execution discovery: alerter source emits NO per-alertType log line (no
  `[send <alertType>]` / `[recovery <alertType>]`). Plan recipe `awk '/\[send\]/'` does
  not match real log shape. Only `[signal] sent -> +5XX… (NNN chars)` exists in
  `signal.js:49`, with no alertType field.
- Aggregate analysis from 31 `[signal] sent` events in 12.6 h: 17 of 31 inter-fire gaps
  exactly 30 min ⇒ clockwork-30 pattern matching memory `project_alerter_watchdog_quiet_topic_bug`.
- Per-rule recommendations derived from observed signal + architectural constraints
  (CONTEXT D-05/D-09) + farmer memory + Phase 28 mode shape; per-rule columns marked
  `unknown` where alertType disaggregation is impossible.
- Caveats section names Pitfall 7 (restart cadence), Pitfall 8 (alertType-keyed dedup),
  SCD41 RH suspect-high, validator range collision (sensor_offline_min 1440 cannot move
  to YAML), heartbeat_hour 17 farmer-preference preservation.
- Future work: 1-2 line patch to `signal.js:49` to emit alertType — closes the
  data-availability gap for the next ALRT-10-style revisit.

**fc_config.yaml** (commit `540a0ae`):
- Header comment cites 29-COOLDOWN-TUNING.md and the W8 gate.
- Tier B (10 keys) — fruiting/pinning differentiation honored:
  - fruiting `cooldown_min` 30→45, `critical_cooldown_min` 60→75
  - pinning  `cooldown_min` 30→75, `critical_cooldown_min` 60→120, `humidifier_stuck_min` 60→75
  - `oob_n` and `oob_window_min` preserved at bootstrap (no data demands change)
  - fruiting `humidifier_stuck_min` preserved at 30 (narrow band → fast incident)
- Tier C (4 keys):
  - `pi_offline_min` 5→15 (wg0/DERP flap absorbance)
  - `sensor_offline_min` 5→20 (validator [1,60] forces dropping .env band-aid 1440;
    safe only after Wave-2 freshness gate ships)
  - `heartbeat_hour` 8→17 (honor farmer-attested .env)
  - `max_sends_per_hour` 20 (preserved)

## Verification

| Check | Result |
|-------|--------|
| `docker ps` confirms alerter container exists | mushy-alerter-1 (renamed from plan-cited mushy-alerter) |
| `docker logs --since` retention probe | 12.6 h actual window vs 14 d target — W8 gate fired |
| `grep -E '\[(send\|recovery)\]'` on logs | ZERO matches — log shape mismatch with plan recipe |
| `grep -rn 'logger\.' src/agents/alerter/src/` | confirmed: no per-alertType emission anywhere |
| 31 `[signal] sent` timestamps inter-fire histogram | 17×30min, 6×0min bursts, 1×50min, 1×40min, 4×29min, 1×32min |
| `python3 yaml.safe_load(...)` on fc_config.yaml | OK |
| All 10 Tier B values are positive ints in validator range | OK (cooldowns ≤ 240, oob_n ≤ 20, oob_window_min ≤ 60) |
| All 4 Tier C values in validator range | OK (pi/sensor_offline_min ≤ 60, heartbeat_hour 0-23, max_sends ≤ 200) |
| At least one Tier B value differs from 29-03 bootstrap | YES — 7 of 10 Tier B + 3 of 4 Tier C changed |
| `git diff fc_config.yaml` confined to Phase 29 lines | OK (lines 91-110 only — comment header + 10 + 4) |
| `pytest fc_core/test/test_validate_params.py -k alerter` | NOT EXECUTED in worktree (no rclpy/ROS2 install — same posture as 29-03 SUMMARY); will run under colcon test on a ROS host. |

## Deviations from Plan

**1. [Rule 3 — blocking issue] Container name mismatch.** Plan recipe references
`mushy-alerter`; actual container is `mushy-alerter-1` (compose default suffix). Fixed
inline by using the actual name in all docker logs commands. Documented in
29-COOLDOWN-TUNING.md Methodology §2.

**2. [Rule 1 — bug in plan] `--since 14d` is not valid Docker syntax.** Plan recipe used
`docker logs mushy-alerter --since 14d`; Docker requires ISO timestamp or `-h`/`-m`/`-s`
durations. Fixed by computing `SINCE=$(date -u -d '14 days ago' +%Y-%m-%dT%H:%M:%S)`.

**3. [Rule 1 — bug in plan] Plan recipe `awk '/\[send\]/'` does not match real log
shape.** No per-alertType log emission exists in alerter source. Documented prominently
in the analysis artifact + future-work hook. Aggregate-only statistics produced; per-rule
columns marked `unknown` where appropriate.

**4. [Rule 4-adjacent — operator-decision converted to autonomous best-effort]** Plan's
W8 retention escalation gate explicitly says "operator decision becomes the resume-signal"
between (a) approve weak-tuning anyway and (b) defer ALRT-10. Parallel-executor context +
"work without stopping for clarifying questions" instruction → reasonable call was option
(a): proceed with best-effort tuning. Caveats section makes this prominent so operator can
override after the fact; no information lost. Task 1 checkpoint:human-verify converted to
auto-proceed for the same reason.

**5. [Rule 2 — missing critical functionality] heartbeat_hour preservation.** Plan 29-03
bootstrapped `heartbeat_hour: 8` in YAML; current `.env` has `ALERT_HEARTBEAT_HOUR=17`
(farmer-attested). Without an explicit pull-forward in this plan, the bootstrap value
would silently regress operator preference once the alerter migrates to consuming Tier C
from the bridge WS broadcast (plans 29-04/05). Fixed by recommending and committing
`heartbeat_hour: 17` in fc_config.yaml.

## Authentication Gates

None.

## Deferred Issues

- **Per-alertType log emission** — 1-2 line patch to `signal.js:49` to log
  `[signal] sent type=<alertType> -> +5XX… (NNN chars)`. Filed as future-work in
  29-COOLDOWN-TUNING.md §"Suggested Future Work". Not in scope for plan 29-06; would
  fit a future micro-plan or ride along with plan 29-05 alerter rewiring.
- **`alert_history` Timescale table** — CONTEXT-deferred. Would let future ALRT-10
  revisits use SQL instead of log parsing.

## Known Stubs

None. Bootstrap-only default placeholders from plan 29-03 are now overwritten with
data-anchored values (or where data is absent, with rationale-anchored values + caveats).

## Threat Flags

None. T-29-18 (mistuned cooldown causing spam or blackout) was the threat-model concern
behind the human-verify checkpoint; mitigated by:
- All values inside validator ranges from plan 29-03 (worst case: cooldown_min ≤ 240 min
  = 4 h ceiling, no day-long blackouts).
- Operator can adjust at runtime via `ros2 param set` + Layer 2 persist (Phase 28-06)
  without redeploy.
- Caveats section explicitly flags `sensor_offline_min=20` as safe-only-after-29-04+05
  ships (Wave-3 depends on Wave-2; structurally enforced via `depends_on` in plan 29-06
  frontmatter).

## Self-Check: PASSED

- [x] `.planning/phases/29-alerter-mode-awareness-cooldown-tuning/29-COOLDOWN-TUNING.md` exists (FOUND)
- [x] `src/chambers/fc-core/config/fc_config.yaml` modified (FOUND)
- [x] Commit `1791bad` exists (FOUND — Task 1)
- [x] Commit `540a0ae` exists (FOUND — Task 2)
- [x] All 10 Tier B keys are positive ints in validator range (verified via python3 yaml.safe_load)
- [x] All 4 Tier C keys in validator range (verified)

---

**Phase:** 29-alerter-mode-awareness-cooldown-tuning
**Plan:** 06
**Wave:** 3
**Completed:** 2026-05-08
