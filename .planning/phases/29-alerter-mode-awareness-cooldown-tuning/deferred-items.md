# Phase 29 Deferred Items

## DEFER-29-01 — PID bumpless re-engage pins duty at 0.15 [URGENT]

**Filed:** 2026-05-08
**Severity:** URGENT — currently affecting fc1 production. Humidifier stuck at duty=0.15 for ~12h post-restart while RH is in-band. Chamber underperforming.

**Root cause (verified 2026-05-08 from Timescale):**
- `fc_controller._engage_pid_bumplessly()` at `src/chambers/fc-core/fc_core/fc_controller.py:748` defaults `last_output: float = 0.15`.
- Caller at line 972-973 invokes it with no argument after restart: `if not self._pid_engaged: self._engage_pid_bumplessly()`.
- `simple_pid.set_auto_mode(True, last_output=0.15)` back-computes the integrator so next output = 0.15.
- When RH is in-band at re-engage time, `error_pct = 0` → output stays 0.15 forever.

**Evidence:**
- 00:25:33 UTC last varying PID output (~0.376)
- 00:25:34 → 00:26:17 — 45s gap → fc_controller restart
- 00:26:18 onward — 42,725 consecutive samples of `humidifier_duty = 0.15000000596046448` (~12h), with RH 95.7%–97.0% (in fruiting band 94.5–97.5%).

**Fix:**
- `fc_controller.py:973` — pass `self._last_published_duty` to `_engage_pid_bumplessly()` (already initialized at line 278, updated in `_publish_duty` line 768).
- `fc_controller.py:748` — drop the magic `0.15` default (the only other caller at line 729 already passes an explicit value).

**Why deferred from Phase 29:** Phase 29 scope is alerter mode-awareness + cooldown tuning, not PID re-engage logic. But the fix is one-line + one-default-removal — could be hot-patched on fc1 or rolled into the Phase 29 controller deploy (29-07).

**Open question:** What restarted fc-core at ~21:25 local 2026-05-07? Check `journalctl -u fc-core --since '2026-05-07 21:00'` next time on fc1.

**Disposition (2026-05-08):** PIGGYBACK ON 29-07 — added as Task 0 in `29-07-PLAN.md`. Two-line fix ships with the controller redeploy already required by Task 1 of 29-07. Smoke verification: post-deploy, observe `humidifier_duty` time-series for ≥10 minutes — value should vary with RH dynamics (not pin at 0.15 or any other constant) when chamber is operating.
