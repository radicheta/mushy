# Phase 63 — Plan 05 Summary

**Status:** COMPLETE
**Date:** 2026-07-25
**Branch:** `feat/phase-63-chamber-alerter`

---

## What shipped

### Task 1 — Port message.js → chamber/message.py (D-04 TZ fix + fmt_num)
**Commit:** `f84a7b6` — `feat(63): port message.js with the CHM-02 timezone fix`

- `farm_agent/chamber/message.py`: `ALERT_TITLES`, `_js_round`, `fmt_num`,
  `fmt_duration`, `fmt_relative`, `hhmm`, `format_problem`, `format_recovery`,
  `format_heartbeat`.
- **CHM-02 / SC2 closed:** `hhmm(ts_ms, tz_name)` renders through
  `ZoneInfo(tz_name)`; `format_problem`'s pi branch passes `config.timezone`.
- `tests/chamber/test_message.py`: 29 tests.

**RED observed:**
```
ImportError while importing test module '.../tests/chamber/test_message.py'.
E   ImportError: cannot import name 'message' from 'farm_agent.chamber'
```

### Task 2 — Port heartbeat.js → chamber/heartbeat.py (defer-on-empty scheduler)
**Commit:** `256d460` — `feat(63): port the daily heartbeat scheduler to chamber/heartbeat.py`

- `farm_agent/chamber/heartbeat.py`: `HeartbeatState`, `tick`, `heartbeat_loop`.
- `tests/chamber/test_heartbeat.py`: 8 tests, all clock-injected (no sleeps except
  the 50 ms cancellation probe).

**RED observed:**
```
ImportError while importing test module '.../tests/chamber/test_heartbeat.py'.
E   ImportError: cannot import name 'heartbeat' from 'farm_agent.chamber'
```

---

## Verification

| Check | Result |
|-------|--------|
| `uv run pytest tests/chamber/test_message.py -v` | **29 passed** (plan predicted 28; +1 from an added parity case) |
| `uv run pytest tests/chamber/test_heartbeat.py -v` | **8 passed** |
| `test_hhmm_renders_montevideo_not_utc` (both `==` and `!=`) | ✅ |
| `test_problem_body_renders_local_time` | ✅ — fix reaches templates, not just the helper |
| `test_defers_on_empty_summary_then_fires` | ✅ |
| `test_day_boundary_uses_configured_zone_not_utc` | ✅ |
| real UTC calls in message.py (`timezone.utc`/`utcnow`/`isoformat`) | **0** |
| `grep -c ZoneInfo` message.py / heartbeat.py | 3 / 3 |
| `uv run pytest tests/chamber/ -q` | **112 passed** |
| `uv run pytest tests/ -q` | **761 passed, 36 skipped** (was 724 + 36) |

No skips added; the 36 remain the pre-existing baseline.

---

## Parity verification against the Node source

Read `message.js` (155 lines) and `heartbeat.js` in full before implementing.
Confirmed true: the `hhmm` bug (`toISOString().slice(11,16)`, config.timezone
never consulted), all template strings including the `??` scrubbed-em-dash forms,
the 999.18 deliberate no-body for sht30/scd41, `heartbeat.js:54`'s `>=`, and the
defer-on-empty branch that leaves `lastFiredDay` untouched.

Both epoch literals were independently recomputed against
`ZoneInfo("America/Montevideo")`: `1_783_985_400_000` = 2026-07-13T23:30:00Z =
**20:30** local, and `1_783_944_900_000` = 12:15:00Z = **09:15** local. Correct
as written.

---

## Deviations

1. **The plan's `fmt_num(-0.04) == "-0"` expectation was WRONG — corrected.**
   The plan asserted `String(+(-0.04).toFixed(1)) === "-0"` in JS. Executed
   against real `node`:
   ```
   -0.04 -> "0"          (not "-0")
   String(-0) = "0"
   -0.06 -> "-0.1"
   ```
   `(-0.04).toFixed(1)` is `"-0.0"`, unary `+` yields `-0`, and **JS
   `String(-0)` is `"0"`**. Since byte-parity with Node is the overriding
   constraint (Phase 64 gates on ≥95% field match), I implemented Node's real
   behaviour and fixed the test expectation to `"0"`, adding `-0.06 → "-0.1"`
   as a companion case proving the sign still survives when the magnitude does.
   This also let the implementation drop the plan's special-case `copysign`
   branch: Python's `int(-0.0) == 0` reproduces Node for free.

   Had the plan's version shipped, the Python alerter would have emitted `-0`
   where Node emits `0` — a silent parity break in a farmer-facing string.

2. **Two acceptance-criteria greps read non-zero but are satisfied in substance**
   (same naive-grep pattern as Plan 04):
   - `grep -c "timezone.utc\|utcnow\|isoformat" message.py` == 1 → the sole hit is
     line 91, the docstring line *warning* "never format via timezone.utc, never
     isoformat()". No such call exists.
   - `grep -c "86_400\|86400" heartbeat.py` == 1 → the sole hit is line 6, the
     plan's own docstring "not a fixed 86_400". No such constant exists.

   Both comments came verbatim from the plan's Step 3 code blocks and were kept:
   they document *why* the code is shaped as it is.

3. **Test count 29, not 28** — the extra is the `-0.06` parity case from
   Deviation 1.

---

## ⚠ FLAGGED FOR PLAN 07 — the `>=` vs `==` heartbeat asymmetry

The plan's `<interfaces>` block asked this summary to escalate it, and it is
**unresolved and load-bearing**:

- `heartbeat.js:54` fires the scheduler tick when `hour >= heartbeatHour`, and
  the scheduler marks the day consumed when it dispatches.
- `state.js:662` (Plan 07's territory) only emits the actual Signal message when
  `hour === heartbeatHour`.

**Consequence:** an alerter restarted at 10:00 with `heartbeat_hour=8` fires the
tick (10 >= 8), consumes the day, and then the FSM's `==` gate drops the message.
The farmer silently gets no heartbeat that day.

This plan ported the **scheduler half faithfully** (`>=` + defer-on-empty). Plan 07
owns the `==` gate and must explicitly decide: reproduce the miss for parity, or
add it to the Phase-64 intentional-delta list and fix it. **Do not let this pass
unnoticed** — it is a real silent-failure path, and it interacts with the
defer-on-empty logic (a deferred day retried at 10:15 hits the same `==` wall).

---

## Produced for later plans

```python
ALERT_TITLES: dict[str, str]
fmt_num(n) -> str
fmt_duration(ms) -> str
fmt_relative(past_ms, now_ms) -> str
hhmm(ts_ms, tz_name) -> str
format_problem(*, alert_type, severity, fields, config, now_ms) -> str
format_recovery(*, alert_type, fields, duration_ms, config) -> str
format_heartbeat(*, summary, config, now_ms) -> str

HeartbeatState(last_fired_day: str | None)
tick(*, state, config, now_ms, get_summary, dispatch, log=None) -> None
async heartbeat_loop(*, config, get_summary, dispatch, clock=None,
                     interval_s=900.0, log=None) -> None
```

`format_problem` field keys are snake_case (`first_oob_ms`, `last_known.ts_ms`,
`on_since_ms`, `rh_at_on`, `current_rh`) — Plan 07's FSM must emit those names.
