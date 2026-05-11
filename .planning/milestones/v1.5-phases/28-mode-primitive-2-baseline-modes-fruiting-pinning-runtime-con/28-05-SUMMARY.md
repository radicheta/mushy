---
phase: 28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con
plan: 05
subsystem: mission-control-bridge
tags: [bridge, rclnodejs, set_parameters, allowlist, mode-tuning, http-ingress, defense-in-depth]

requires:
  - phase: 28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con
    plan: 01
    provides: D-A1..D-A5 — rclnodejs SetParameters wire shape locked, n.spin() requirement, expected_type per allowlist entry
  - phase: 28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con
    plan: 04
    provides: on_set_parameters_callback validator with PID range bounds — bridge allowlist mirrors these for defense in depth
provides:
  - "POST /control/param HTTP route on the bridge — single + batched body shapes, 200/400/422/500 contract (D-20 farmOS coordination surface)"
  - "control_param.js module: ALLOWLIST table + validate + toParamValue + makeHandler factory (testable in isolation, mocked rclnodejs)"
  - "Hardcoded allowlist (T-28-15): no disk load; hardware-pin / sim-mode / offset params explicitly absent (T-28-14)"
  - "Atomic batched-band edits: when body.params contains both band_low and band_high, ONE rcl SetParameters request is sent (Pitfall 4)"
  - "Type-coercion safety: toParamValue keys on allowlist entry's expected_type, never on JS typeof (Pattern 4 footgun closed)"
  - "T-28-18 DoS cap: max 20 params per request"
affects: [phase-28-plan-06-fc_buffer-control-persist, phase-30-farmos-mode-tuner]

tech-stack:
  added:
    - "src/mission-control/bridge/src/control_param.js (CommonJS module — matches existing bridge style)"
  patterns:
    - "Defense-in-depth param validation: bridge allowlist at HTTP ingress + on_set_parameters_callback at rcl boundary (28-04) — same range bounds in both layers (T-28-09)"
    - "Lazy rosNode binding: route registered statically at module load; handler reads module-level rosNode at request time (set inside rclnodejs.init().then()). 503 returned pre-init."
    - "Whole-batch atomicity at the bridge mirrors rclpy whole-batch atomicity: validate every param in body.params BEFORE sending; one createClient call per request"
    - "Per-route express.json() — bridge has no global body parser; safer to keep it route-local (limits attack surface to declared JSON endpoints only)"

key-files:
  created:
    - src/mission-control/bridge/src/control_param.js
  modified:
    - src/mission-control/bridge/src/index.js
    - src/mission-control/bridge/test/control_param.test.js
    - .planning/phases/28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con/deferred-items.md

key-decisions:
  - "Lazy rosNode wrapper at the route registration site (vs deferring app.post inside rclnodejs.init().then()): keeps all route registrations in the static section above the rclnodejs init block, makes the route discoverable by grep without reading async setup, and avoids an init-callback race where the route would be unavailable until rclnodejs init resolves. Cost: a single null-check + 503 path pre-init."
  - "Per-route express.json() (vs app.use(express.json()) globally): smaller blast radius — only declared JSON endpoints get a body parser; matches the bridge's existing posture (no global body parser today)."
  - "MAX_PARAMS_PER_REQUEST=20 (T-28-18 DoS cap): controller has ~15 allowlistable params total; 20 is a comfortable ceiling that still rejects pathological 1000-element arrays."
  - "TIMEOUT_MS=3000 default: SetParameters round-trip on the live stack measured ~10ms in spike §A; 3s is generous and still bounds bridge-side hang exposure."
  - "Active_mode best-effort allowlist of {fruiting, pinning} hardcoded: controller is the final authority via on_set_parameters_callback (28-04). If a future deploy declares a third mode, the bridge will 400-reject it until this list is updated AND the controller declares it — accepted as a small coordinated-deploy step (CONTEXT D-03: new modes are deploys)."
  - "Single createClient per request inside the handler (not cached at startup): rclnodejs createClient is idempotent for an existing service; caching would couple control_param.js to bridge lifecycle. Per-request creation cost is negligible vs the SetParameters round-trip."

requirements-completed: [MODE-05]

duration: ~3min
completed: 2026-05-08
---

# Phase 28 Plan 05: Wave 5 — Bridge Layer 1 Hot Path (POST /control/param) Summary

**Bridge runtime-tuning ingress lands: `POST /control/param` validates farmOS POSTs against a hardcoded allowlist + range bounds, then forwards to `fc_controller` via rclnodejs `SetParameters` using the wire shape locked in 28-01-SPIKE §A. 60/60 control_param tests GREEN; full bridge regression suite holds (modulo 2 pre-existing burn_bar failures, deferred). Allowlist range bounds mirror the Phase 28-04 controller validator (T-28-09 defense in depth). Closes MODE-05 Layer 1.**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-05-08T00:08:28Z
- **Completed:** 2026-05-08T00:11:28Z
- **Tasks:** 2 (Task 1 TDD RED→GREEN; Task 2 surgical mount)
- **Files created:** 1
- **Files modified:** 2

## Locked Endpoint Contract (D-20)

`POST /control/param` — bridge HTTP, port 8081, CORS-allowlisted to OpenMCT origin(s).

### Request shapes

**Single param:**
```json
{ "node": "fc_controller", "param": "active_mode", "value": "pinning" }
```

**Batched params (Pitfall 4 — coupled-band edits):**
```json
{
  "node": "fc_controller",
  "params": [
    { "param": "modes.pinning.band_low",  "value": 0.85 },
    { "param": "modes.pinning.band_high", "value": 0.99 }
  ]
}
```

### Response shapes

| Status | Body shape | Trigger |
|--------|-----------|---------|
| 200 | `{ "ok": true, "applied": [{"param", "value"}, ...] }` | All params accepted by controller. |
| 400 | `{ "error": "...", "rejected_param"?: "..." }` | Body shape error / unknown node / non-allowlisted param / out-of-range value / enum violation / oversized batch. |
| 422 | `{ "error": "<controller reason>", "rejected_param": "..." }` | rclpy `on_set_parameters_callback` returned `successful=false` (e.g. band invariant violated). |
| 500 | `{ "error": "<transport>" }` | rclnodejs createClient failure / SetParameters timeout (3s) / no response. |
| 503 | `{ "error": "rclnodejs not ready" }` | Pre-init request (rclnodejs.init() hasn't resolved yet). |

## Final Allowlist (hardcoded in `src/control_param.js`)

| Param                                       | Type   | Constraint                                |
|---------------------------------------------|--------|-------------------------------------------|
| `active_mode`                               | STRING | enum {fruiting, pinning} (best-effort; controller is final authority) |
| `modes.fruiting.target_humidity`            | DOUBLE | 0.0 ≤ v ≤ 1.0                             |
| `modes.fruiting.band_low`                   | DOUBLE | 0.0 ≤ v ≤ 1.0                             |
| `modes.fruiting.band_high`                  | DOUBLE | 0.0 ≤ v ≤ 1.0                             |
| `modes.fruiting.defend_side`                | STRING | enum {low, high, both}                    |
| `modes.fruiting.t_target`                   | DOUBLE | NaN OR 0.0 ≤ v ≤ 40.0                     |
| `modes.pinning.target_humidity`             | DOUBLE | 0.0 ≤ v ≤ 1.0                             |
| `modes.pinning.band_low`                    | DOUBLE | 0.0 ≤ v ≤ 1.0                             |
| `modes.pinning.band_high`                   | DOUBLE | 0.0 ≤ v ≤ 1.0                             |
| `modes.pinning.defend_side`                 | STRING | enum {low, high, both}                    |
| `modes.pinning.t_target`                    | DOUBLE | NaN OR 0.0 ≤ v ≤ 40.0                     |
| `pid_kp`                                    | DOUBLE | 0.0 ≤ v ≤ 5.0                             |
| `pid_ki`                                    | DOUBLE | 0.0 ≤ v ≤ 1.0                             |
| `pid_kd`                                    | DOUBLE | 0.0 ≤ v ≤ 20.0                            |

**Explicitly NOT allowlisted (T-28-14):** `humidifier_pin`, `light_pin`, `dht_pin`, `fan_pwm_channel`, `fan_pwm_freq`, `actuator_simulation_mode`, `sensor_simulation_mode`, `sht30_i2c_address`, `sht30_temperature_offset_c`, anything matching `*_offset_*`. Verified by table-driven jest tests.

**PID range bounds mirror Phase 28-04 validator** (`fc_controller.py::_validate_params`). Defense in depth — a bridge bypass cannot push insane gains because the rcl boundary callback also enforces.

## rclnodejs Request Shape (verbatim from 28-01-SPIKE §A — Pattern 4 confirmed, no pivot)

```javascript
{
  parameters: [
    { name: 'pid_kp',      value: { type: 3, double_value: 0.35 } },
    { name: 'active_mode', value: { type: 4, string_value: 'pinning' } }
  ]
}
```

**Type discriminator (D-A3):** `1=BOOL/bool_value`, `2=INTEGER/integer_value`, `3=DOUBLE/double_value`, `4=STRING/string_value`. Field names are snake_case.

**Response shape (D-A2):**
```javascript
{ results: [{ successful: true, reason: '' }, ...] }
```
Per-param results in same order as request.parameters. Atomic-batch failures: every result has `successful=false` with the same reason.

**Spin requirement (D-A5):** the bridge's existing `node.spin()` at index.js:868 (called inside `rclnodejs.init().then()`) covers the new client. No extra spin needed — the route reuses `rosNode`.

**No deviation from research §Pattern 4** — the spike captured the shape verbatim against the live `/fc_controller/set_parameters` service. Plan 05 implementation copies it byte-for-byte; the test suite asserts the exact shape via a captured-request expectation.

## Task Commits

1. **Task 1 RED:** `424a50d` — test(28-05): add RED tests for control_param allowlist + handler (60 specs)
2. **Task 1 GREEN:** `93e159e` — feat(28-05): implement control_param allowlist + handler (GREEN)
3. **Task 2:** `96c1f1c` — feat(28-05): mount POST /control/param route in bridge

## Decisions Made

See `key-decisions:` frontmatter. Highlights:

- **Lazy rosNode wrapper.** Route registered statically at module load, handler reads `rosNode` at request time. Pre-init requests get a 503. Discoverable by `grep '/control/param' src/index.js`; doesn't bury route registration inside the async init block.

- **Defense-in-depth range bounds.** Bridge allowlist enforces `pid_kp ∈ [0,5]`, `pid_ki ∈ [0,1]`, `pid_kd ∈ [0,20]` — the SAME bounds the Phase 28-04 `on_set_parameters_callback` validator enforces at the rcl boundary. A compromised farmOS or a misconfigured curl-poke cannot push insane gains.

- **Type-coercion safety (Pattern 4 footgun).** `toParamValue('pid_kp', 2)` returns `{type: 3, double_value: 2}`, NOT `{type: 2, integer_value: 2}` — the allowlist entry's `expected_type` is the source of truth. Tested explicitly: a JS Number `2` (looks like an integer to `typeof`) still serializes as DOUBLE.

- **Whole-batch atomicity.** When `body.params` contains both `band_low` and `band_high`, the bridge sends ONE `SetParameters` request with both params in the array. The rclpy validator (Phase 28-04) sees the post-batch state and accepts/rejects atomically. A second client racing in between the two won't observe the half-applied state because the validator rejects when the post-batch view is invalid.

- **T-28-18 DoS cap (20 params/request).** Controller has ~15 allowlistable params total. 20 leaves headroom for full-mode-replace edits without permitting pathological arrays.

## Verification

**60/60 control_param tests GREEN:**
```
$ cd src/mission-control/bridge && npx jest test/control_param.test.js
PASS test/control_param.test.js
  ALLOWLIST + DECLARED_MODES: 25 tests
  validate: 16 tests
  toParamValue: 6 tests
  handler: 13 tests
Tests:       60 passed, 60 total
```

**Full bridge suite — no regression introduced by plan 28-05:**
```
$ npx jest
Test Suites: 1 failed, 8 passed, 9 total
Tests:       2 failed, 4 todo, 131 passed, 137 total
```

The 2 failures are in `burn_bar.test.js` (Phase 22 jimp/font rendering) and **fail identically on `main` before this plan's commits** — pre-existing, out of scope per executor's scope-boundary rule. Logged at `.planning/phases/28-.../deferred-items.md`.

**Syntax check on index.js:**
```
$ node -c src/index.js && echo SYNTAX_OK
SYNTAX_OK
```

**Buffer-replay cursor (Pitfall 8) untouched:**
```
$ grep -n "advanceLastIngested" src/mission-control/bridge/src/index.js
627:            buffer_replay.advanceLastIngested(buffer_replay.DEFAULT_STATE_FILE, tsNs);
```
Line 627 (was 613 before this plan's +14-line addition near line 561 — index.js shifted by exactly the new require + new route block). Edit was 56 lines above the cursor advance, well outside the 5-line danger zone.

**Hardware-pin allowlist exclusion (T-28-14) — grep test:**
```
$ grep -E "humidifier_pin|light_pin|dht_pin|fan_pwm|simulation_mode|_offset_" src/mission-control/bridge/src/control_param.js
(no output — params are not present in the allowlist module)
```

## Deviations from Plan

None. Both tasks executed exactly as specified:

- Task 1 followed TDD RED→GREEN: tests committed first (RED, with all 60 failing on `Cannot find module ../src/control_param`), then implementation committed second (GREEN — 60/60 pass).
- Task 2 was the surgical mount described in the plan: one require, one route block, lazy rosNode binding for pre-init safety. The plan's snippet directly mounts `control_param.makeHandler(rosNode, ...)` at module load — that would have captured `rosNode = null` in a closure permanently. Wrapping with a per-request closure that reads the current `rosNode` is the structurally correct version of the same idea (treating it as a clarification of the plan's intent, not a deviation).

The plan called out one optional check: "If `n.spin()` not present, document." — the bridge already spins (`node.spin()` at line 868), so no additional spin needed. Documented in `key-decisions` and in the inline comment on the route.

## Issues Encountered

- 2 pre-existing burn_bar test failures surfaced during regression check. Confirmed pre-existing (failed before any of plan 28-05's commits via direct `npx jest test/burn_bar.test.js`). Logged to deferred-items.md; out of scope.

## User Setup Required

None — code-only changes. Lands on elder-plops via the standard bridge rebuild flow:
```
docker-compose up -d --build bridge
```
(Per CLAUDE.md: always pass `--build`; the compose file pins build context but not image tag.)

Plan 28-06 will add the persistence relay (`POST /control/persist` on bridge → `POST /control/persist` on `fc_buffer.py`); plan 28-07 finalizes the deploy gates. Live deploy of 28-05 is gated on those follow-ups for full end-to-end value.

## Next Phase Readiness

**Ready for plan 28-06** (Wave 6 — fc_buffer `POST /control/persist` + bridge proxy):

- `src/control_param.js` exports a clean module surface (`ALLOWLIST`, `validate`, `toParamValue`, `makeHandler`) — plan 06 will reuse `validate` for the persist-side allowlist mirror.
- Endpoint contract on the bridge side (`POST /control/param`) is locked; plan 06 adds `POST /control/persist` with the same body shape so farmOS can coordinate transient + persistent edits as a pair.
- rclnodejs reuse pattern proven: lazy `rosNode` wrapper pattern is the template for any future bridge ROS-client routes.

## Threat Flags

None — all surface introduced is in the plan's threat register (T-28-09, T-28-14, T-28-15, T-28-16, T-28-17, T-28-18, T-28-19). No new boundary surfaces beyond those mitigated.

## Self-Check: PASSED

Files created/modified (verified):
- `src/mission-control/bridge/src/control_param.js` — FOUND
- `src/mission-control/bridge/src/index.js` — FOUND (modified; +14 lines)
- `src/mission-control/bridge/test/control_param.test.js` — FOUND (rewritten from test.todo scaffold)
- `.planning/phases/28-.../deferred-items.md` — FOUND (created with 1 entry)

Commits exist (verified by `git log --oneline -4`):
- `424a50d` Task 1 RED — FOUND
- `93e159e` Task 1 GREEN — FOUND
- `96c1f1c` Task 2 — FOUND

Acceptance gates:
- 60/60 control_param tests GREEN ✓
- Full bridge suite: 131 passed, 2 pre-existing failures (burn_bar — out of scope) ✓
- index.js syntax check clean ✓
- Buffer-replay cursor (line 627 post-edit) untouched ✓
- Hardware/sim/offset params absent from allowlist ✓
- rclnodejs request shape matches SPIKE §A verbatim (test asserts exact shape) ✓
- PID range bounds mirror Phase 28-04 validator ✓
- Atomic batched-band edit sends ONE SetParameters call (test verifies createClient called once) ✓

---

*Phase: 28-mode-primitive-2-baseline-modes-fruiting-pinning-runtime-con*
*Completed: 2026-05-08*
