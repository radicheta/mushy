# Phase 63 — Plan 07 Summary

**Status:** COMPLETE
**Date:** 2026-07-25
**Branch:** `feat/phase-63-chamber-alerter`

---

## What shipped

### Task 1 — FSM primitives + resolve_effective_config
**Commit:** `52052c2` — `feat(63): port the FSM primitives and effective-config resolver`

`STATES`, `ALERT_TYPES`, `SEVERITY`, `STARTUP_GRACE_MS`, `Freshness`,
`EffectiveConfig`, `AlertEntry`, `ChamberState`, `initial_state`, `cooldown_ms`,
`is_snoozed`, `has_mode_context`, `_pick`, `resolve_effective_config`.
21 tests.

**RED observed:**
```
ImportError while importing test module '.../tests/chamber/test_state.py'.
E   ImportError: cannot import name 'state' from 'farm_agent.chamber'
```

### Task 2 — drive_alert_type + per-event handlers
**Commit:** `66133da` — `feat(63): port the alert FSM with Node's call-site asymmetries intact`

`_fast_fire`, `drive_alert_type`, helpers `_last_known` / `_eval_pi` /
`_eval_physical_sensors`, and `transition` covering all 13 event types
(humidity, mode_update, overrides_update, globals_update, temperature, co2,
sensor_health, sensor_freshness, humidifier, pi_liveness, tick, snooze,
heartbeat_tick) with an unknown type as a no-op. 22 further tests (43 total).

**RED observed:**
```
E   AttributeError: module 'farm_agent.chamber.state' has no attribute 'drive_alert_type'
tests/chamber/test_state.py:235: AttributeError
```
Task 1's 21 tests stayed green throughout.

---

## Verification

| Check | Result |
|-------|--------|
| `uv run pytest tests/chamber/test_state.py -v` | **43 passed** |
| `grep -c "def drive_alert_type"` | **1** (one generic fn, not six) |
| all four `*_parity_quirk_*` tests | **PASSED** (named individually below) |
| `test_mode_update_preserves_cooldown` | PASSED |
| `test_drive_alert_type_does_not_mutate_the_input_entry` | PASSED |
| `test_stale_effective_config_suspends_the_rh_rule` | PASSED |
| `uv run lint-imports --config .lint-imports` | **1 kept, 0 broken** |
| `uv run pytest tests/ -q` | **825 passed, 36 skipped** (was 782 + 36) |

No skips added; the 36 remain the pre-existing baseline.

---

## 🚩 PHASE-64 DELTA CANDIDATES (reproduced here, NOT fixed)

The plan requires these be listed explicitly. All four are Node behaviours that
look like bugs, are reproduced faithfully, and are pinned by tests. **None is on
the current intentional-delta list (TZ fix, quote-ts coercion, fmtNum); a decision
is owed before Phase 64 replays traffic.**

1. **`tick`/pi does not fast-fire while `pi_liveness`/pi does** — js:580 passes
   `effective`; js:547 passes `{...effective, oobN:1, oobWindowMin:0}`.
   *Effect:* the same outage FIRES immediately when the 10s health poll reports it,
   but is debounced through oob_n=5 / oob_window_min=3 when only the periodic tick
   sees it. **Directly shapes SC1 timing.**
   Pinned by `test_parity_quirk_tick_pi_does_not_fast_fire`.

2. **sensor fires on 1 error, recovers on 5 clean samples** — js:354 passes a
   fast-fire config, js:359 passes raw `config`, and `drive_alert_type` counts
   recovery against `config.oob_n`.
   Pinned by `test_parity_quirk_sensor_fires_on_one_error_recovers_on_five`.

3. **sht30/scd41/sensor watchdogs never see Tier B/C overrides** — every one of
   their call sites (js:353, 386, 437, 610, 621) builds from raw `config`, and
   `is_sensor_silent` likewise receives raw `config`. A Tier C global
   `sensor_offline_min` override therefore never reaches the per-sensor watchdog,
   contradicting D-01's "detectors consume the effective config" framing.
   Pinned by `test_parity_quirk_sensor_watchdogs_ignore_tier_c_overrides`.

4. **heartbeat `==` hour (state.js:662) vs `>=` hour (heartbeat.js:54)** — the
   scheduler dispatches and consumes the day at `>=`, but the FSM only emits at
   `==`. An alerter restarted at 10:00 with `heartbeat_hour=8` **silently burns
   the day**. Interacts with Plan 05's defer-on-empty logic: a day deferred to
   10:15 hits the same wall.
   Pinned by `test_parity_quirk_heartbeat_requires_exact_hour`.
   (Also flagged from the other side in 63-05-SUMMARY.md.)

   > **RESOLVED 2026-07-27 as a SANCTIONED DELTA (MUSHY-44 item 4).** The reducer
   > now gates on `hour >= heartbeat_hour`, matching the scheduler. The pinning
   > test was flipped to `test_heartbeat_fires_after_the_hour_not_only_on_it`,
   > which also asserts the one-per-local-day cap still holds. Phase 64's parity
   > gate must score this as an INTENDED divergence, not a mismatch. Quirks 1-3
   > above remain pinned and unfixed.

---

## ⚠ 63-RESEARCH.md correction required before Phase 64

**RESEARCH Pitfall 3 is inaccurate.** It states that both pi call sites apply the
fast-fire override and advises extracting one `_fast_fire_config` helper applied
"consistently at all 6 call sites".

Verified against `state.js` on 2026-07-25: **js:580 (tick/pi) does NOT apply it.**
Following the research doc's advice would have made the two paths consistent,
changing pi FIRING latency on the tick path from ~11 min to ~1 tick — a silent
SC1 timing change that Phase 64's ≥95% field-match gate would fail.

The plan's own call-site matrix caught this and is correct; the research doc
should be amended so Phase 64 does not plan against the wrong claim.

Every other claim in the plan's call-site matrix was verified line-by-line against
`state.js` and held.

---

## Deviations

1. **`test_parity_quirk_tick_pi_does_not_fast_fire` assertion narrowed.** The plan
   wrote `assert actions == []`. That is unachievable and contradicts Node: the
   same tick legitimately evaluates the sht30/scd41 watchdogs (js:609-626), which
   **do** fast-fire from raw config, so with `sht30_last_seen_ms == BOOT` and
   `now == BOOT + 90min` both watchdogs fire and the list is never empty. Changed
   to `assert [a for a in actions if a.get("alert_type") == "pi"] == []`, which is
   what the test actually pins. The `pi` state assertion (`PENDING`, not `FIRING`)
   is unchanged and is the load-bearing half.

   For the same reason `test_parity_quirk_sensor_fires_on_one_error_recovers_on_five`'s
   first count assertion was scoped to `alert_type == "sensor"`.

2. **`test_mode_update_preserves_cooldown` needed `st.ws_connected = True`.** As
   written the test could not exercise its own intent. `initial_state` seeds
   `ws_connected=False` (verified identical in Node, js:46), so
   `resolve_effective_config` returned **stale** freshness, which suspends the RH
   rule (`rules.is_rh_oob` → False). The humidity sample then read as *in-band* and
   emitted a RECOVERY rather than testing the cooldown at all. With the socket up
   the mode is fresh, RH is OOB, and the cooldown assertion is real.

   Worth stating plainly: **the implementation was right and the test was wrong.**
   I confirmed Node's `initialState` before changing anything rather than bending
   the port to satisfy the test.

3. **`_eval_pi` / `_eval_physical_sensors` extracted as helpers.** The pi
   evaluation is duplicated verbatim in Node across js:514-551 and js:560-582,
   differing *only* in the fast-fire flag; likewise the sensor watchdog across
   js:385-414 and js:609-626. Extracting them with the asymmetry as an explicit
   parameter (`pi_config_is_fast_fire`) makes the quirk impossible to lose in a
   later refactor. Behaviour is unchanged.

4. **`is_humidifier_stuck` call sites pass `ws_connected` and
   `humidifier_last_msg_ts` explicitly.** Required by the Plan-04 null/undefined
   simplification flagged in 63-04-SUMMARY.md — without them the Python detector
   would suppress unconditionally. This is the audit that summary asked for; both
   call sites (humidity js:281, tick js:590) now pass them.

---

## Produced for Plan 08

```python
STATES, ALERT_TYPES, SEVERITY, STARTUP_GRACE_MS
Freshness, EffectiveConfig, AlertEntry, ChamberState
initial_state(now_ms) -> ChamberState
cooldown_ms(alert_type, config) -> int
is_snoozed(entry, now_ms) -> bool
has_mode_context(state) -> bool
resolve_effective_config(state, env_config, now_ms) -> EffectiveConfig
drive_alert_type(entry, alert_type, oob_now, fields, now_ms, config) -> (AlertEntry, list)
transition(prev, event, now_ms, config) -> (ChamberState, list[dict])
```

**Action shapes Plan 08 must handle:**
- `{"kind": "send", "alert_type", "severity", "body"}`
- `{"kind": "recovery", "alert_type", "body", "duration_ms"}`
- `{"kind": "heartbeat", "body"}` — note: **no** `alert_type` key, and it bypasses
  all snoozes by design.

`transition` is pure and never does I/O; Plan 08 owns dispatching the actions and
must iterate them sequentially (no `asyncio.gather`) to keep ordering and log
attribution deterministic.
