# Phase 03: Closed-Loop Control - Research

**Researched:** 2026-04-04
**Domain:** Python control-loop logic, ROS2 node timing, actuator safety patterns
**Confidence:** HIGH — all findings are grounded in the actual source files; no external library research required.

## Summary

Phase 3 is a pure logic phase: no new packages, no new topics, no new actuators. The entire surface area is three additions to `fc_controller.py` — timestamp tracking in `humidity_callback`, a staleness check at the top of `control_loop`, and a dwell time guard around `set_humidifier`. The config file gains two parameters. The test file gains cases for the three new behaviors.

All implementation decisions are locked in CONTEXT.md. The research job here was to audit the existing code precisely so the planner can write tasks against exact line numbers and real class state, not guesses.

The main architectural subtlety is time: the controller already imports `time` (stdlib) but also has `self.get_clock().now()` available via ROS2. CONTEXT.md (D-08) specifies using `self.get_clock().now()` for `_last_humidity_timestamp`. This is the right choice for sim-time compatibility, but it requires care in tests: `rclpy.time.Time().nanoseconds` returns 0 when the ROS clock hasn't advanced, so tests must either advance time explicitly or mock `self.get_clock().now()`. The established test pattern in this codebase is `unittest.mock.patch` — that pattern extends cleanly to clock mocking.

**Primary recommendation:** Implement in one wave of three sequential plans (03-01 bang-bang cleanup, 03-02 dwell time, 03-03 staleness/safe-state) because each plan's test cases require the previous plan's state changes to be present.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Config naming (CTRL-02)**
- D-01: Keep existing parameter names (`target_humidity`, `humidity_tolerance`) — deployed on FC-1, renaming breaks live config.
- D-02: Add `min_dwell_time` and `sensor_stale_timeout` to `fc_config.yaml` with descriptive comments.
- D-03: Existing bang-bang at lines 164-168 uses `target_humidity ± humidity_tolerance` as the hysteresis band. CTRL-01 is partially satisfied — needs dwell time and staleness guards to be complete.

**Minimum dwell time (CTRL-03)**
- D-04: Default `min_dwell_time: 300.0` (5 minutes) in `fc_config.yaml`.
- D-05: Track `_last_humidifier_toggle` timestamp in the controller. When `set_humidifier()` is called with a state change, check elapsed time since last toggle. If under dwell time, skip the change and log at DEBUG level.
- D-06: Dwell time applies to both ON→OFF and OFF→ON transitions equally.

**Staleness detection (CTRL-04)**
- D-07: Default `sensor_stale_timeout: 10.0` (10 seconds) in `fc_config.yaml`.
- D-08: Track `_last_humidity_timestamp` in `humidity_callback()` — update each time a message arrives using `self.get_clock().now()`.
- D-09: In `control_loop()`, check if current time minus `_last_humidity_timestamp` exceeds `sensor_stale_timeout`. If stale → enter safe state.

**Safe state (CTRL-05)**
- D-10: Safe state = humidifier OFF. Log WARN on entry: "Sensor data stale — humidifier OFF for safety".
- D-11: Auto-recover when fresh data arrives — no manual reset needed. Log INFO on recovery: "Fresh sensor data received — resuming control".
- D-12: Existing `if self.current_humidity is None: return` at line 149 must call `set_humidifier(False)` instead of silently returning.
- D-13: Fans and lights unaffected by humidity safe state.

### Claude's Discretion

- Exact placement of dwell time check (inside `set_humidifier` vs in `control_loop` before calling it)
- Whether to add a `_safe_state_active` boolean flag for cleaner logging (avoid repeated WARN on every control tick)
- Test structure and simulation helpers for the new behaviors

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CTRL-01 | Closed-loop bang-bang control maintains humidity setpoint with hysteresis | Skeleton at lines 164-168 exists; needs dwell + staleness guards to be complete |
| CTRL-02 | Setpoint and deadband configurable via `fc_config.yaml` | `target_humidity` and `humidity_tolerance` already present; add `min_dwell_time` + `sensor_stale_timeout` using existing `declare_parameters` pattern |
| CTRL-03 | Minimum dwell time — humidifier cannot cycle faster than configurable interval | Add `_last_humidifier_toggle: Optional[rclpy.time.Time]` to `__init__`; check in dwell guard |
| CTRL-04 | Stale sensor data detected — control loop does not act on data older than threshold | Add `_last_humidity_timestamp: Optional[rclpy.time.Time]` to `__init__`; set in `humidity_callback`; check at top of `control_loop` |
| CTRL-05 | Sensor failure drives humidifier to safe state (OFF), not frozen last state | Replace `return` at line 149 with `set_humidifier(False)`; add `_safe_state_active` flag for log deduplication |
</phase_requirements>

## Standard Stack

No new packages are required. This phase uses only what is already installed.

### Core (already present)
| Component | Version | Purpose | Status |
|-----------|---------|---------|--------|
| Python `time` stdlib | 3.10+ | Already imported; NOT used for ROS clock | Already imported (line 5), do not use for ROS timestamps |
| `rclpy.time.Time` | Jazzy | ROS2 monotonic clock for timestamps | Available via `self.get_clock().now()` on any Node |
| `unittest.mock.patch` | stdlib | Time/clock mocking in tests | Already used in `test_light_control` |
| `pytest` | system | Test runner | Already used for all existing tests |

### No New Dependencies

Do not add `freezegun`, `pytest-mock`, or any other time-mocking library. The established pattern in this codebase is `unittest.mock.patch` and it is sufficient.

**Installation:** None required.

## Architecture Patterns

### Existing Code Map (audited from source)

```
fc_controller.py
├── __init__() — lines 12-92
│   ├── declare_parameters() — lines 15-33  (ADD: min_dwell_time, sensor_stale_timeout)
│   ├── hardware init — lines 37-67
│   ├── subscribers — lines 70-79
│   ├── current state — lines 81-84         (ADD: _last_humidity_timestamp, _last_humidifier_toggle)
│   └── timer — lines 87-90
├── humidity_callback() — line 97-99        (ADD: _last_humidity_timestamp update)
├── set_humidifier() — lines 121-125        (CANDIDATE for dwell time guard OR keep in control_loop)
├── get_humidifier_state() — lines 138-141  (READ in dwell time check)
└── control_loop() — lines 148-179
    ├── None-check — line 149              (CHANGE: call set_humidifier(False) instead of return)
    ├── staleness check — ADD HERE          (before existing bang-bang logic)
    └── bang-bang logic — lines 164-168     (UNCHANGED in structure, dwell time wraps calls)
```

### Pattern 1: Dwell Time Guard — Placement Decision (Claude's Discretion)

**Option A: Inside `set_humidifier`**
- Pro: enforced unconditionally, no way to bypass by accident
- Con: `set_humidifier` is called from safe-state logic too; dwell guard must NOT block the safe-state OFF call
- Verdict: requires extra `force=False` parameter to bypass from safe-state — adds complexity

**Option B: In `control_loop` before calling `set_humidifier`**
- Pro: safe-state path (`set_humidifier(False)`) is never gated by dwell time
- Con: dwell logic is in the caller, not the function
- Verdict: simpler and safer given D-13 (safe state must always be reachable)

**Recommendation: Option B** — place dwell time check in `control_loop` only around the two bang-bang `set_humidifier` calls. Safe state calls bypass the guard entirely. This keeps `set_humidifier` a thin hardware abstraction.

### Pattern 2: Staleness Flag for Log Deduplication (Claude's Discretion)

**Recommendation: add `_safe_state_active: bool = False`** to instance state.

Without the flag, every control tick (1 Hz) while sensor is stale logs WARN — that floods the log and obscures other warnings. The flag enables "log on transition only":

```python
# Source: this codebase pattern (established in Phase 2 for filter)
if stale and not self._safe_state_active:
    self._safe_state_active = True
    self.get_logger().warn("Sensor data stale — humidifier OFF for safety")
elif not stale and self._safe_state_active:
    self._safe_state_active = False
    self.get_logger().info("Fresh sensor data received — resuming control")
```

### Pattern 3: ROS2 Clock Timestamp Arithmetic

```python
# In humidity_callback — store ROS time
self._last_humidity_timestamp = self.get_clock().now()

# In control_loop — check staleness
if self._last_humidity_timestamp is not None:
    elapsed_ns = (self.get_clock().now() - self._last_humidity_timestamp).nanoseconds
    elapsed_sec = elapsed_ns / 1e9
    stale = elapsed_sec > self.get_parameter('sensor_stale_timeout').value
```

The subtraction of two `rclpy.time.Time` objects returns a `rclpy.duration.Duration` with a `.nanoseconds` attribute.

**Initial state:** `_last_humidity_timestamp = None`. If None at control_loop time, the existing `if self.current_humidity is None: return` check fires first — but per D-12 that line is being changed to call `set_humidifier(False)`. After D-12 is applied, a None timestamp at first startup is safe because the control loop will call set_humidifier(False) anyway until the first reading arrives.

### Pattern 4: Parameter Declaration (existing pattern to follow)

```python
# Source: fc_controller.py lines 15-33 — existing pattern
self.declare_parameters(
    namespace='',
    parameters=[
        # ... existing params ...
        ('min_dwell_time', 300.0),       # ADD: seconds
        ('sensor_stale_timeout', 10.0),  # ADD: seconds
    ]
)
```

### Anti-Patterns to Avoid

- **Using `time.time()` for ROS timestamps:** The controller imports `time` (stdlib) for non-ROS purposes. Do NOT use `time.time()` for `_last_humidity_timestamp` or `_last_humidifier_toggle`. Use `self.get_clock().now()` consistently so the code is sim-time compatible (D-08).
- **Dwell time blocking safe state:** Safe state OFF must always reach the actuator. Any dwell guard that gates ALL `set_humidifier` calls will block safety-critical transitions.
- **Silent `return` on None humidity:** Line 149 currently silences failures. After D-12, this path must actively drive the humidifier OFF.
- **Repeated WARN logging per tick:** Without `_safe_state_active` flag, 1 Hz WARN floods systemd journal and obscures real events. Add the flag.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Time subtraction | Custom nanosecond arithmetic | `rclpy.duration.Duration.nanoseconds` (returned by `Time - Time`) | Already correct, handles overflow |
| Hysteresis band | Custom deadband math | Existing lines 164-168 with `target_humidity ± humidity_tolerance` | Already tested and correct |
| Actuator abstraction | New GPIO wrapper | Existing `set_humidifier()` / `get_humidifier_state()` | Already handles sim vs real hardware |

**Key insight:** This phase adds control-flow guards around existing primitives — it does not replace them.

## Common Pitfalls

### Pitfall 1: Dwell Time Blocks Safe State
**What goes wrong:** Dwell guard placed inside `set_humidifier()` prevents the safe-state path from turning humidifier OFF during active dwell period.
**Why it happens:** The guard feels natural inside the function, but the safe-state call path is different from the control-decision path.
**How to avoid:** Place dwell guard only in `control_loop` around the bang-bang calls (lines 165-168). Never gate `set_humidifier(False)` from safe-state logic.
**Warning signs:** Test for "safe state fires during dwell period" fails, or humidifier stays ON when sensor data is stale.

### Pitfall 2: `_last_humidity_timestamp` Initialized to `None` Race
**What goes wrong:** On first startup, `_last_humidity_timestamp` is `None` and a None-check is skipped, causing an AttributeError or unintended stale-state trigger.
**Why it happens:** The staleness check is `(now - self._last_humidity_timestamp).nanoseconds` — this crashes if the attribute is None.
**How to avoid:** Guard: `if self._last_humidity_timestamp is not None:` before the subtraction. If None and no humidity has arrived yet, the existing None-check path handles it.
**Warning signs:** `AttributeError: 'NoneType' has no attribute 'nanoseconds'` in startup logs.

### Pitfall 3: Clock in Tests Returns Zero / Doesn't Advance
**What goes wrong:** `self.get_clock().now()` returns the same value for every call in unit tests (ROS clock is not ticking), making staleness always False or always True.
**Why it happens:** In the pytest `ros_context` fixture, `rclpy.init()` starts a context but no spinning node is advancing the clock.
**How to avoid:** Mock `self.get_clock` to return a controllable clock, or mock `self.get_clock().now()` with `unittest.mock.patch.object`. Return a `rclpy.time.Time(nanoseconds=N)` with different N values to simulate elapsed time.
**Warning signs:** Staleness test passes trivially regardless of timestamp, or never fires.

### Pitfall 4: `_last_humidifier_toggle` Type Inconsistency
**What goes wrong:** Using `time.time()` (float, wall clock) for `_last_humidifier_toggle` but `rclpy.time.Time` for `_last_humidity_timestamp` — mixing time sources makes tests fragile.
**Why it happens:** `import time` is already at the top of the file; easy to reach for.
**How to avoid:** Use `self.get_clock().now()` for both timestamps. Consistent source, consistent test mocking strategy.
**Warning signs:** Dwell time tests pass locally but behave oddly in colcon test where environment differs.

### Pitfall 5: Dwell Time Never Resets on Force/Safe-State Override
**What goes wrong:** Safe state calls `set_humidifier(False)` bypassing dwell guard. When sensor recovers, the next toggle attempt is blocked by dwell time computed from the last *non-safe* toggle — resulting in longer-than-expected delay before humidifier can turn on again.
**Why it happens:** `_last_humidifier_toggle` is only updated when the dwell guard allows a toggle.
**How to avoid:** Update `_last_humidifier_toggle` whenever the humidifier actually changes state — including safe-state forced OFF. The dwell timer should reset from any real state change.
**Warning signs:** After a stale-sensor recovery, control loop logs "dwell time not elapsed" for longer than `min_dwell_time` from the last real user toggle.

## Code Examples

### Timestamp tracking in humidity_callback
```python
# Source: CONTEXT.md D-08 + rclpy Node API
def humidity_callback(self, msg):
    self._humidity_buffer.append(msg.relative_humidity)
    self.current_humidity = median(self._humidity_buffer)
    self._last_humidity_timestamp = self.get_clock().now()  # ADD
```

### Staleness check at top of control_loop
```python
# Source: CONTEXT.md D-09, D-10, D-11, D-12
def control_loop(self):
    # Handle no-data-yet case — explicitly safe (D-12)
    if self.current_temp is None or self.current_humidity is None:
        set_humidifier(False)
        return

    # Staleness guard (D-09)
    stale = False
    if self._last_humidity_timestamp is not None:
        elapsed_sec = (
            self.get_clock().now() - self._last_humidity_timestamp
        ).nanoseconds / 1e9
        stale = elapsed_sec > self.get_parameter('sensor_stale_timeout').value

    if stale:
        if not self._safe_state_active:          # log on transition only
            self._safe_state_active = True
            self.get_logger().warn(
                "Sensor data stale — humidifier OFF for safety"
            )
        self.set_humidifier(False)
        # Temperature and light control continues (D-13)
        ...
        return

    if self._safe_state_active:                  # recovery log
        self._safe_state_active = False
        self.get_logger().info("Fresh sensor data received — resuming control")

    # ... existing temperature control ...
    # Bang-bang humidity control with dwell guard (D-05)
    desired_state = None
    if self.current_humidity < (...):
        desired_state = True
    elif self.current_humidity > (...):
        desired_state = False

    if desired_state is not None:
        self._set_humidifier_with_dwell(desired_state)
```

### Dwell time guard helper (in control_loop)
```python
# Source: CONTEXT.md D-05, D-06
def _set_humidifier_with_dwell(self, state):
    current_state = self.get_humidifier_state()
    if state == current_state:
        return  # no transition needed
    if self._last_humidifier_toggle is not None:
        elapsed_sec = (
            self.get_clock().now() - self._last_humidifier_toggle
        ).nanoseconds / 1e9
        if elapsed_sec < self.get_parameter('min_dwell_time').value:
            self.get_logger().debug(
                f"Dwell time not elapsed ({elapsed_sec:.1f}s < "
                f"{self.get_parameter('min_dwell_time').value}s), skipping toggle"
            )
            return
    self.set_humidifier(state)
    self._last_humidifier_toggle = self.get_clock().now()
```

### Clock mocking in tests
```python
# Source: established unittest.mock.patch pattern in test_controller.py
import rclpy.time
from unittest.mock import patch, MagicMock

def make_clock(nanoseconds):
    mock_clock = MagicMock()
    mock_clock.now.return_value = rclpy.time.Time(nanoseconds=nanoseconds)
    return mock_clock

def test_sensor_staleness(ros_context):
    node = FruitingChamberController()
    # Simulate callback arriving 2 seconds ago
    t_callback = rclpy.time.Time(nanoseconds=0)
    t_now = rclpy.time.Time(nanoseconds=int(15e9))  # 15 seconds later

    with patch.object(node, 'get_clock') as mock_gc:
        mock_gc.return_value.now.return_value = t_callback
        _send_humidity(node, 0.82)

        mock_gc.return_value.now.return_value = t_now
        node.current_temp = 23.0  # prevent None-check early exit
        node.control_loop()

    assert node.humidifier_state == False
    node.destroy_node()
```

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (python3-pytest, ROS2 ament test infra) |
| Config file | none (driven by colcon test) |
| Quick run command | `pytest src/chambers/fc-core/fc_core/test/test_controller.py -x` |
| Full suite command | `colcon test --packages-select fc_core && colcon test-result --verbose` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CTRL-01 | Bang-bang turns humidifier ON below lower threshold, OFF above upper threshold | unit | `pytest src/chambers/fc-core/fc_core/test/test_controller.py::test_humidity_control -x` | Yes (extend existing) |
| CTRL-02 | `min_dwell_time` and `sensor_stale_timeout` are readable ROS2 parameters with correct defaults | unit | `pytest src/chambers/fc-core/fc_core/test/test_controller.py::test_new_params_declared -x` | No — Wave 0 gap |
| CTRL-03 | Humidifier does not toggle when dwell time has not elapsed | unit | `pytest src/chambers/fc-core/fc_core/test/test_controller.py::test_dwell_time_blocks_toggle -x` | No — Wave 0 gap |
| CTRL-03 | Humidifier toggles after dwell time has elapsed | unit | `pytest src/chambers/fc-core/fc_core/test/test_controller.py::test_dwell_time_allows_toggle_after_wait -x` | No — Wave 0 gap |
| CTRL-04 | Stale sensor data (> sensor_stale_timeout) triggers humidifier OFF | unit | `pytest src/chambers/fc-core/fc_core/test/test_controller.py::test_sensor_staleness -x` | No — Wave 0 gap |
| CTRL-05 | Humidifier turns OFF when humidity is None (startup / failure) — not frozen | unit | `pytest src/chambers/fc-core/fc_core/test/test_controller.py::test_none_humidity_safe_state -x` | No — Wave 0 gap |
| CTRL-05 | Auto-recovery: humidifier resumes control after fresh data arrives | unit | `pytest src/chambers/fc-core/fc_core/test/test_controller.py::test_safe_state_recovery -x` | No — Wave 0 gap |

### Sampling Rate
- **Per task commit:** `pytest src/chambers/fc-core/fc_core/test/test_controller.py -x`
- **Per wave merge:** `colcon test --packages-select fc_core && colcon test-result --verbose`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `test_new_params_declared` — covers CTRL-02 (min_dwell_time, sensor_stale_timeout defaults)
- [ ] `test_dwell_time_blocks_toggle` — covers CTRL-03 (guard prevents early toggle)
- [ ] `test_dwell_time_allows_toggle_after_wait` — covers CTRL-03 (guard permits toggle after wait)
- [ ] `test_sensor_staleness` — covers CTRL-04 (stale data → humidifier OFF)
- [ ] `test_none_humidity_safe_state` — covers CTRL-05 (None humidity → explicit OFF, not frozen)
- [ ] `test_safe_state_recovery` — covers CTRL-05 (auto-recover on fresh data)

All new tests go in the existing file: `src/chambers/fc-core/fc_core/test/test_controller.py`.
No new test files or conftest.py needed — the `ros_context` fixture already handles rclpy init/shutdown.

## Environment Availability

Step 2.6: SKIPPED (no external dependencies — phase is pure Python logic changes to existing files, no new services or tools required).

## Open Questions

1. **Dwell timer behavior during safe-state OFF transitions**
   - What we know: Safe state bypasses dwell guard; `_last_humidifier_toggle` is only set when a real toggle fires.
   - What's unclear: Should the safe-state forced-OFF update `_last_humidifier_toggle`? If yes, the humidifier cannot turn back on for `min_dwell_time` after sensor recovery. If no, it might turn on immediately on recovery even if it just turned off.
   - Recommendation: Update `_last_humidifier_toggle` on safe-state OFF too (call `self.set_humidifier(False); self._last_humidifier_toggle = self.get_clock().now()`). This is conservative and prevents rapid cycling after recovery. Test should verify this behavior explicitly.

2. **`test_temperature_control` currently uses `node.fan_pwm.get_duty_cycle()`**
   - What we know: Line 37 in existing test references `node.fan_pwm` — but in simulation mode there is no `fan_pwm` attribute. This test may already be broken or silently skipped.
   - What's unclear: Whether `colcon test` currently passes all existing tests on this machine.
   - Recommendation: Run the existing test suite before writing new tests to establish baseline pass/fail state. Fix pre-existing failures before adding new test cases to avoid confusion.

## Sources

### Primary (HIGH confidence)
- `src/chambers/fc-core/fc_core/fc_controller.py` — full source audit, line numbers verified
- `src/chambers/fc-core/config/fc_config.yaml` — full config audit, all existing parameters listed
- `src/chambers/fc-core/fc_core/test/test_controller.py` — full test audit, fixtures and patterns verified
- `.planning/phases/03-closed-loop-control/03-CONTEXT.md` — all decisions D-01 through D-13 read verbatim

### Secondary (MEDIUM confidence)
- ROS2 Jazzy rclpy.time API — `Time - Time` returns `Duration` with `.nanoseconds`; verified from `fake_sensors.py` usage of `self.get_clock().now()` in this same codebase

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies, all components audited from live files
- Architecture: HIGH — patterns derived from actual code at exact line numbers
- Pitfalls: HIGH — identified from direct code analysis of the existing implementation
- Test patterns: HIGH — clock mocking strategy derived from existing `datetime.patch` pattern already in the test file

**Research date:** 2026-04-04
**Valid until:** Indefinite — findings are tied to the actual source files, not external library versions
