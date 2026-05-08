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

**Verified live (2026-05-08):** post-deploy `humidifier_duty` varied 0→0.15→0, now correctly 0 (RH 97% above band). Pre-deploy was pinned at 0.15 for 12h. Fix confirmed in production. CLOSED.

---

## DEFER-29-02 — Bridge `/control/param` int values fail with `integer_value must be type of bigint` [open]

**Filed:** 2026-05-08 (during 29-07 Smoke 3)
**Severity:** medium — workaround exists (direct `ros2 param set` over SSH); blocks runtime tuning of integer-typed alerter globals from the bridge HTTP surface.

**Symptom:** `POST http://localhost:8765/control/param` with `{"node":"fc_controller","param":"sensor_offline_min","value":5}` returns a SetParameters error: `integer_value must be type of bigint`.

**Root cause:** Phase 29-01 ALLOWLIST integer handler in `src/mission-control/bridge/src/control_param.js:139` returns `{ type: T_INTEGER, integer_value: Math.trunc(value) }`. The underlying `rclnodejs` (or DDS bridge) requires `integer_value` to be a JavaScript `BigInt`, not a Number, before it crosses into the SetParameters service call.

**Workaround used during 29-07 Smoke 3:** `ssh fc1 'ros2 param set /fc_controller sensor_offline_min 5'` — this propagated through `/fc1/control/alerter_globals` correctly. The Tier C / mode-overrides delivery channel is fine; only the bridge-side HTTP-→ROS bridge for integer params is broken.

**Fix (one-liner):** Wrap as `BigInt(Math.trunc(value))` at `control_param.js:139`. Add a jest assertion that the integer handler emits a `BigInt`.

**Track:** 999.X (file under bridge runtime-tuning surface; not blocking).

---

## DEFER-29-03 — Alerter `state.js` reducer emits no logger calls on rule evaluations / config updates [open]

**Filed:** 2026-05-08 (during 29-07 Smoke 1)
**Severity:** low — behavior is correct; observability gap only.

**Symptom:** Plan 29-07 Task 2 acceptance criterion `docker logs mushy-alerter | grep mode_update` returned empty even though mode swaps were propagating end-to-end. Verified via WS envelope sniff that the alerter *was* receiving and applying `mode_update` / `overrides_update` / `globals_update` envelopes — but the reducer in `src/agents/alerter/src/state.js` has no `logger.info(...)` calls in the transition cases.

**Root cause:** Phase 29-04 implemented the reducer cases purely as state transitions; `logger.info` was assumed elsewhere but never landed in the reducer itself.

**Fix:** Add a 1-line `logger.info('[mode_update] name=%s', payload.name)` (and analogous lines for `overrides_update` and `globals_update`) in each transition case. Add jest assertions that `logger.info.mock.calls` includes the expected tag per case.

**Track:** 999.X (filed but not blocking).
