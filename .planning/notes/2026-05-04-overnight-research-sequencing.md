# Overnight Research + Plan Batch — Sequencing Recommendations

**Date:** 2026-05-04 (research+plan run overnight into 2026-05-05)
**Phases:** 999.32, 999.33, 999.34 — all PID-tuning-adjacent backlog items

Three phases were researched and planned in parallel overnight. All artifacts are on disk in their respective phase directories. Nothing committed against prod code; nothing deployed to fc1.

## Artifacts

| Phase | Research | Plans | Status |
|---|---|---|---|
| 999.32 PID derivative filter not wired | `999.32-RESEARCH.md` (HIGH conf) | `999.32-01-PLAN.md` (1 plan, 2 tasks) | Ready for cold review |
| 999.33 Digital twin chamber sim | `RESEARCH.md` (MED-HIGH conf) | `999.33-{01,02,03}-PLAN.md` (3 plans, 3 waves) | Ready for cold review |
| 999.34 SHT30 heater cycle | `RESEARCH.md` (HIGH driver / MED cadence / LOW long-run) | `999.34-{01,02,03}-PLAN.md` (3 plans, 3 waves) | Ready for cold review |

## Cross-phase dependencies surfaced

- **999.34 ↔ 999.32:** 999.34 plan-02 has both branches for the dep — delegates to 999.32's `reset_derivative_filter()` if shipped, else inline reset of vendored `simple_pid._last_input`. Ship-without-999.32 escape hatch is real.
- **999.33 deliberately does NOT implement derivative filtering** ("sim must lag prod, not lead it"). Composes cleanly when 999.32 ships — re-validate sim fidelity afterwards.
- **999.32 reserves the 4th reset hook** as a no-op stub with comment seam for 999.34 to fill in.

## Recommended execution order

**1. 999.33 (digital twin) — execute first.**
Zero prod runtime risk. Doesn't touch fc1. Honors farmer constraint "don't change prod code while live-tuning" by definition. Unblocks future tuning iteration without farmer-presence gating — which is the strategic ask that motivated filing it. Biggest cold-review surface (the compute_duty refactor touches prod hot path; the 7200s ramp-in and hardcoded gains decisions deserve a careful look).

**2. 999.32 + 999.34 paired — next live-tuning weekend with farmer present.**
Both touch prod. 999.34 alone is net-negative without 999.32 (live test 2026-05-04 22:02 UTC proved this — heater pulse without controller guard caused PID to spike duty 0 → 0.85). Pair them. Either:
- (a) Ship 999.32 first as a sole-change validation weekend, then 999.34 the following weekend. Cleanest, slowest.
- (b) Ship 999.32 then 999.34 in the same weekend. Faster, requires more attention.
- (c) Ship 999.34 with inline derivative reset (the escape hatch in plan-02), defer 999.32 indefinitely. Don't recommend — 999.32 is independently load-bearing for the next round of Kp/Kd tuning regardless of heater work.

Recommendation: **(a) or (b) depending on weekend availability.**

## Cold-review flags worth attention

- **999.33 plan-03** hardcodes PID gains (0.35, 0.001, 4.0) in the CI synthetic-grow test rather than reading from `fc_config.yaml`. Planner explicitly asks for pushback if you want yaml-tracking instead. Tradeoff: yaml-tracking means CI breaks when you tune; hardcoding means CI must be reviewed when you tune.
- **999.33 SIM-08** uses 7200s (2h) ramp-in skip-window before asserting RH-error band, not 1800s (30min). Calibrated for cold-start through dead-time + chamber τ + first window-rollover. Strict-mode reviewers may want tighter.
- **999.34** has 4 deferred discuss-phase questions captured in plan-03 (Timescale skip-vs-quality-flag, RH-stuck condition trigger, heater-write-raise policy, SHT30↔SCD41 thermal coupling). All have working defaults; flagged for explicit confirmation before ship.
- **999.32** plan ships a live A/B affordance: `ros2 param set pid_derivative_filter_tau 0.0` reverts to current behavior without redeploy. No-cost safety valve worth knowing about.

## ROADMAP discoverability

All three phases are still backlog-form bullets in `ROADMAP.md`, not the resolver-friendly `### Phase N:` + `- [ ] **Phase N:**` form. Per memory `feedback_gsd_phase_discoverability`, executor needs the latter. When ready to execute:

1. Promote the chosen phase to `### Phase 999.NN:` + checkbox in ROADMAP.md
2. Then `/gsd:execute-phase 999.NN`

Not promoting them now — keeps backlog tidy and avoids signaling commitment until you've reviewed the plans.

## Out of scope / deferred

- **999.33 shape (b) — Gazebo / physical sim:** explicitly deferred indefinitely per RESEARCH.md. Re-evaluate when 999.6 (multi-chamber), 999.7 (rover), or Phase 24 (vision) enters discuss-phase.
- **999.34 long-run efficacy:** can only be proven by 30-day SHT30↔SCD41 RH-delta soak. Plan-03 RUNBOOK includes Day-30 review reminder.
- **999.31** (PWM duty-history deque size mismatch): NOT included in overnight batch. Likely subsumed by 999.29 (max-continuous-on cap redesign). Trivial 1-line fix if 999.29 doesn't ship first.
