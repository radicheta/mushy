# Phase 63 — Plan 04 Summary

**Status:** COMPLETE
**Date:** 2026-07-25
**Branch:** `feat/phase-63-chamber-alerter`

---

## What shipped

### Task 1 — Port rules.js → chamber/rules.py (5 pure detectors)
**Commit:** `e693dda` — `feat(63): port rules.js detectors to chamber/rules.py`

- `farm_agent/chamber/rules.py`: `FC1_DARK_THRESHOLD_MS = 3 * 60_000` plus
  `is_rh_oob`, `is_sensor_error`, `is_pi_offline`, `is_humidifier_stuck`,
  `is_sensor_silent`. All pure, all config-by-parameter, no module globals.
- `tests/chamber/test_rules.py`: 26 tests, each historical guard named with the
  incident it prevents.

**RED observed:**
```
ImportError while importing test module '.../tests/chamber/test_rules.py'.
E   ImportError: cannot import name 'rules' from 'farm_agent.chamber'
```

### Task 2 — Port snooze.js → chamber/snooze.py (command grammar)
**Commit:** `12509ec` — `feat(63): port snooze.js grammar to chamber/snooze.py`

- `farm_agent/chamber/snooze.py`: `VALID_ALERT_TYPES`, `VALID_DURATIONS`,
  `STRICT`, `SIMPLE`, `_SNOOZE_PREFIX`, `parse_snooze_command`.
- `tests/chamber/test_snooze.py`: 37 tests including the 13-case hostile-input
  parametrization and the pinned `mute rh 2h` parity quirk.

**RED observed:**
```
ImportError while importing test module '.../tests/chamber/test_snooze.py'.
E   ImportError: cannot import name 'snooze' from 'farm_agent.chamber'
```

---

## Verification

| Check | Result |
|-------|--------|
| `uv run pytest tests/chamber/test_rules.py -v` | **26 passed** |
| `uv run pytest tests/chamber/test_snooze.py -v` | **37 passed** |
| `uv run pytest tests/chamber/ -q` | **75 passed** (deps 3 + config 9 + rules 26 + snooze 37) |
| `grep -Ec "def (is_rh_oob\|is_sensor_error\|is_pi_offline\|is_humidifier_stuck\|is_sensor_silent)"` | **5** |
| `FC1_DARK_THRESHOLD_MS` present, `== 3 * 60_000` | ✅ |
| Both regexes anchored `^`/`$` + `re.IGNORECASE` | ✅ |
| `uv run lint-imports --config .lint-imports` | **1 kept, 0 broken** |
| `uv run pytest tests/ -q` | **724 passed, 36 skipped** (was 661 + 36) |

No skips added by this plan; the 36 remain the pre-existing baseline.

---

## Parity verification against the Node source

Per [[feedback_verify_research_claims_against_source]] I read
`src/agents/alerter/src/rules.js` (110 lines) and `snooze.js` (63 lines) in full
before implementing rather than trusting the plan's transcription. **Every claim
the plan made about the Node source held**, including:

- `isRhOob` short-circuits on `effective.freshness.state === 'stale'` only.
- `isPiOffline` reads `config.piOfflineMin` for triggers 1-2 and the hardcoded
  `FC1_DARK_THRESHOLD_MS` for trigger 3 — the Pitfall-2 separation is real.
- `rosConnected === false` is an explicit identity check, not a falsy check.
- `isSensorSilent` uses `sensorOfflineMin` and never touches the flap floor.
- `STRICT` anchors on the literal `snooze`, so `"mute rh 2h"` really does fall
  through to `{ok: false, reply: null}` — the quirk is genuine, now pinned.

---

## Deviations

1. **`grep -c "config.pi_offline_min" == 1` acceptance criterion reads 2.**
   Not a defect. There is exactly **one** reader (line 69,
   `threshold_ms = config.pi_offline_min * 60_000`); the second hit is line 81,
   the plan's own explanatory comment `"Hard 3-minute constant, NOT
   config.pi_offline_min."` — which the plan supplied verbatim in its Step 3 code
   block. The criterion's *intent* (the fc1-dark branch must not be a second
   reader) is satisfied. The comment was kept because it is load-bearing
   documentation of the Phase-46 D-09 decision; mangling it to satisfy a naive
   grep would trade real value for a counter.

2. **Test-count discrepancy inside the plan itself.** Task 1 Step 4 predicts
   "26 passed" while the plan's `<verification>` block says "24 + 37". The actual
   count is **26 + 37**; Step 4 and the acceptance criteria are right and the
   verification block's `24` is stale. No action taken beyond noting it.

3. **`is_humidifier_stuck` null-vs-undefined simplification** — carried out
   exactly as the plan specified, and worth restating because it is a **real
   behavioural delta from Node**: JS treats `humidifierLastMsgTs === null` as
   suppress but `undefined` as "pre-Phase-29 caller, skip the staleness gate".
   Python has only `None`, so `None` suppresses. Consequence: **every Plan 07
   call site must pass `ws_connected` and `humidifier_last_msg_ts` explicitly**,
   or the detector silently never fires. Flagged here for the FSM wiring audit.

4. **`SIMPLE` regex drops Node's redundant `\b`** (`(snooze|mute|quiet)\b\s*$` →
   `(snooze|mute|quiet)\s*$`), as the plan directed. Verified equivalent for these
   inputs: `\s*$` already forces the match to end at the keyword, so `"snoozes"`
   is rejected by both forms. Covered by the parametrized bare-keyword test.

---

## Produced for later plans

Plan 07's FSM consumes, at these exact signatures:

```python
FC1_DARK_THRESHOLD_MS: int  # 3 * 60_000
is_rh_oob(humidity, effective) -> bool
is_sensor_error(sensor_health: dict) -> bool
is_pi_offline(*, ws_connected, ros_connected, now_ms, ws_last_connected_ms,
              ros_disconnected_since_ms, fc1_last_msg_ts, config) -> bool
is_humidifier_stuck(*, humidifier_on_since_ms, rh_at_on, current_rh, now_ms,
                    config, ws_connected=None, humidifier_last_msg_ts=None) -> bool
is_sensor_silent(*, last_seen_ms, now_ms, config) -> bool

VALID_ALERT_TYPES: list[str]
VALID_DURATIONS: dict[str, int]
parse_snooze_command(text, now_ms) -> dict
```

`is_rh_oob`'s `effective` stays duck-typed: Plan 07's `EffectiveConfig` should
expose `rh_target`, `rh_band`, and optionally `freshness` (an object with
`.state`). A bare `ChamberConfig` works and is treated as fresh.
