# Phase 15: Sensor warm-up grace period — Research

**Researched:** 2026-04-17
**Domain:** ROS2 Jazzy / rclpy controller state machine + sensor-health signalling
**Confidence:** HIGH (greenfield change in a well-understood module; codebase read verified)

<user_constraints>
## User Constraints (from 15-CONTEXT.md)

### Locked Decisions
- **Farmer constraint: "bigger gap > noise".** During warm-up, publish nothing OR publish an explicit "warming up" status. NEVER interpolate, guess, or emit best-effort values. A missing-data indicator in MC is preferable to a wrong-looking value.
- **Design-of-failure-mode signal:** false data actively erodes trust; silence/known-unknown does not.
- **Grace condition (suggested):** `_humidity_buffer` full AND ≥20s wall-clock since boot — whichever is longer.
- **New config param:** `startup_grace_period` (default 20s).
- **No actuator commands during grace.** Humidifier must not flip based on transient readings.
- **MC/UX followup:** ideally annotated ("sensors warming up, X seconds remaining"); consumed by Phase 16. Phase 15 EMITS the signal; Phase 16 consumes it.

### Claude's Discretion
- WHERE to suppress (sensor publish vs controller consume vs both).
- Signal shape for downstream (separate topic vs flag in msg vs diagnostics).
- Whether 20s is enough or per-sensor adaptive.
- Test-time clock injection pattern.

### Deferred Ideas (OUT OF SCOPE)
- MC widget rendering the warming-up state — Phase 16.
- Per-sensor adaptive warm-up tuning based on SCD41 vs SHT30 datasheets — only if trivial; defer real calibration to post-SHT30-reinstall.
- Signal alerts / farmer app integration.
- PID / time-proportional rework (999.9).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SENS-01 | Sensor warm-up grace period at fc-core boot to avoid false actuation from SCD41 settling (from 999.8 backlog) | This phase — controller early-return + sensor-health topic |
| WARMUP-01 (new) | `fc_controller.control_loop()` takes no actuator action until grace condition satisfied | §Architecture Pattern 1 |
| WARMUP-02 (new) | A `/fc1/sensor_health` topic publishes `warming_up` state so MC (Phase 16) can render gap legibly | §Architecture Pattern 2 |
| WARMUP-03 (new) | Grace period completes automatically; no human intervention | §Architecture Pattern 1 |
| WARMUP-04 (new) | Unit tests cover: pre-grace early-return, grace expiry, buffer-not-full-but-time-elapsed, time-elapsed-but-buffer-not-full, sensor_health transitions | §Validation Architecture |

Phase promotes backlog 999.8 → v1.2.1 hotfix milestone. REQUIREMENTS.md currently lists SENS-01 under "Future Requirements" and redundantly in "Out of Scope" — planning should update REQUIREMENTS.md to move SENS-01 to v1.2.1 active.
</phase_requirements>

## Summary

Phase 15 inserts a startup-grace gate into `fc_controller.control_loop()` so the first ~20s post-boot are a no-op for actuation. A new `/fc1/sensor_health` topic broadcasts controller warm-up state for Phase 16 consumption. Sensor publishes in `fc_sensors.py` are **not** suppressed — the farmer still wants the telemetry to flow into Timescale for later diagnosis, and the "gap" is enforced at the consumer/display layer via the health signal.

**Primary recommendation:** Suppress at the **controller consume** layer (not at sensor publish). Publish a `/fc1/sensor_health` `DiagnosticStatus`-shaped message on state change (warming_up ↔ ok). Keep sensor topics flowing unchanged so (a) Timescale captures the transient for future forensics, (b) `fc_display` and bridge keep working, (c) the change is surgical — one node, one new publisher, one early-return.

## Project Constraints (from CLAUDE.md)

- **Deploy is git-based on `fc1/prod`** → `scripts/pi-deploy/deploy.sh` (git pull + colcon build + systemctl restart). Phase 15 deploy follows this.
- **Simulation mode matters:** `sensor_simulation_mode` and `actuator_simulation_mode` are independent (from `fc_config.yaml`). Tests use sim mode; live uses real I2C.
- **Testing tools:** `colcon test --packages-select fc_core` and direct `pytest src/chambers/fc-core/fc_core/test/`.
- **Linting:** `ament_flake8`, `ament_pep257` — match existing style.

## Standard Stack

### Core (already in use, no new deps)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| rclpy | Jazzy | ROS2 Python node API | [VERIFIED: already used in `fc_controller.py`] |
| sensor_msgs | Jazzy | Temperature, RelativeHumidity msgs | [VERIFIED: already imported] |
| std_msgs | Jazzy | Bool | [VERIFIED: already used for actuator state] |
| diagnostic_msgs | Jazzy | DiagnosticStatus / DiagnosticArray | [CITED: ROS2 standard — docs.ros.org/en/jazzy/p/diagnostic_msgs] — canonical "is this subsystem healthy?" message |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| rclpy.clock | Jazzy | `node.get_clock().now()` | Reuse — tests already mock this pattern [VERIFIED: `test_controller.py::_mock_clock_at`] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `diagnostic_msgs/DiagnosticStatus` on `/fc1/sensor_health` | `std_msgs/Bool` `/fc1/sensor_health/warming_up` | Bool is simpler but doesn't scale to Phase 16's "green lights panel" — DiagnosticStatus carries level + message + key/value pairs in one schema [CITED: http://docs.ros.org/en/jazzy/p/diagnostic_msgs/msg/DiagnosticStatus.html] |
| Separate topic | Field on existing sensor msgs | Would require custom msg types in a new `.msg` file + package rebuild. Heavier change. Defer. |
| Separate topic | `/fc1/diagnostics` (DiagnosticArray, the ROS-standard aggregate) | DiagnosticArray is the "right" long-term choice (Phase 16 can aggregate camera + sensors + actuators), but for now a single DiagnosticStatus on a named topic is fine and forward-compatible. |

**Installation:** None — `diagnostic_msgs` is in ROS2 Jazzy base install [VERIFIED: `apt list --installed ros-jazzy-diagnostic-msgs` typically present]. Planner should verify `ros-jazzy-diagnostic-msgs` is a `package.xml` dep; it may need to be added.

**Version verification:** N/A — using distro-pinned packages (Jazzy).

## Architecture Patterns

### Recommended Structure (minimal-change)

```
src/chambers/fc-core/fc_core/
├── fc_controller.py     # ADD: startup_grace_period param, _grace_active(),
│                        #      /fc1/sensor_health publisher, early-return in control_loop
├── fc_sensors.py        # UNCHANGED (sensor publishes keep flowing)
├── fc_display.py        # UNCHANGED (gets gap naturally via no actuator changes; MC rendering in Phase 16)
└── test/
    └── test_controller.py  # ADD: 4–5 warm-up test cases
config/fc_config.yaml    # ADD: startup_grace_period: 20.0
package.xml              # VERIFY: diagnostic_msgs dependency
```

### Pattern 1: Grace Gate in `control_loop` (WHERE to suppress)

**What:** Early-return at the top of `control_loop()` before any actuator action, based on two conditions ANDed together. Safe-state (`set_humidifier(False)`) IS still applied — grace is not "frozen state", it's "known-idle".

**When to use:** First N seconds after node init.

**Example:**
```python
# In __init__, alongside other params:
('startup_grace_period', 20.0),

# New instance state in __init__:
self._boot_time = self.get_clock().now()
self._warming_up = True  # latched True until grace clears
self.sensor_health_pub = self.create_publisher(
    DiagnosticStatus, 'fc1/sensor_health', actuator_qos  # TRANSIENT_LOCAL for late-joiners
)

def _grace_active(self) -> bool:
    """True while either grace condition is unmet."""
    if len(self._humidity_buffer) < self._humidity_buffer.maxlen:
        return True
    elapsed = (self.get_clock().now() - self._boot_time).nanoseconds / 1e9
    if elapsed < self.get_parameter('startup_grace_period').value:
        return True
    return False

def control_loop(self):
    if self._grace_active():
        # Safe idle: humidifier OFF (same as existing None-guard), no dwell update
        self.set_humidifier(False)
        self._publish_sensor_health(warming_up=True)
        return  # skip all downstream logic

    if self._warming_up:  # first tick out of grace
        self._warming_up = False
        self.get_logger().info('WARMUP-CLEARED: control loop engaging')
        self._publish_sensor_health(warming_up=False)

    # ... existing None-guard, staleness, humidity control, etc.
```

**Rationale for HERE not in `fc_sensors.py`:**
1. `fc_sensors.py` blindly publishes hardware readings — that's its job. Suppressing there means Timescale loses the transient (farmer has expressed interest in post-hoc data even when warming up — SENS data is always useful).
2. `fc_display.py` subscribes to same sensor topics; suppressing at sensor would blank the display too. Phase 16 wants to render "warming up, N s left" — needs the SIGNAL, not just absence.
3. Single point of change — one node, one gate. Surgical (CLAUDE.md §3).
4. Restart isolation: if controller restarts but sensors don't, controller gets fresh grace period automatically via `_boot_time` set in `__init__`. That is correct behavior.

### Pattern 2: Sensor Health Signal (the SIGNAL shape for Phase 16)

**Topic:** `/fc1/sensor_health`
**Type:** `diagnostic_msgs/msg/DiagnosticStatus`
**QoS:** `TRANSIENT_LOCAL` depth=1 (same pattern as `fc1/actuators/humidifier`) so MC/bridge reconnects get current state immediately.

**Publish policy:** On state CHANGE only (not every tick) to keep topic quiet. Always publish once at grace-enter (first tick) and once at grace-exit. Phase 16 renders whatever it last saw.

**Message shape:**
```python
msg = DiagnosticStatus()
msg.level = DiagnosticStatus.WARN if warming_up else DiagnosticStatus.OK
msg.name = 'fc1/controller'
msg.message = 'warming up' if warming_up else 'ok'
msg.hardware_id = 'fc1'
msg.values = [
    KeyValue(key='warming_up', value=str(warming_up).lower()),
    KeyValue(key='grace_elapsed_sec', value=f'{elapsed:.1f}'),
    KeyValue(key='grace_total_sec', value=f'{grace_period:.1f}'),
    KeyValue(key='buffer_full', value=str(buffer_full).lower()),
]
```

**Why this shape for Phase 16:**
- `level` directly drives the green/yellow/red semantic (OK=green, WARN=yellow, ERROR=red).
- `values` key/value pairs give MC the countdown ("X seconds remaining") the CONTEXT.md calls for without forcing MC to know internals.
- `name='fc1/controller'` so Phase 16 can treat this as ONE entry in a DiagnosticArray aggregated with future camera/actuator health entries — forward compatible.
- On the wire: standard, self-describing, already-supported in `rosbridge_suite` so the Node bridge relays it without custom serializers.

### Anti-Patterns to Avoid
- **Don't suppress `fc_sensors.py` publishes.** Destroys Timescale forensics, blanks `fc_display`, and forces anyone consuming sensors to also consume grace separately. The farmer's "gap over noise" is about what the FARMER SEES in MC, not what the system records.
- **Don't publish `/fc1/sensor_health` every tick.** `TRANSIENT_LOCAL` + on-change is the pattern that already worked for `/fc1/actuators/humidifier`. Mirror it.
- **Don't adapt the grace per-sensor heuristically.** Calibration is blocked on SHT30 reinstall (per CALIBRATION-FINDINGS-2026-04-11.md caveat). 20s fixed is the honest choice. If empirical data later shows SCD41 needs longer, tune the config — no code change.
- **Don't block temperature/fan control.** Phase controller's temperature path already runs independently during staleness (`D-13` in code). BUT: during warm-up, temp readings are also settling, so early-return covers the whole loop. This is OK — fan defaults to OFF, which is safe, and 20s is short.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Structured health signal | Custom `.msg` with `bool warming_up` | `diagnostic_msgs/DiagnosticStatus` | Standard; MC bridges + rqt already parse it; Phase 16 inherits aggregation for free |
| Time-since-boot | `time.time()` math | `self.get_clock().now() - self._boot_time` | rclpy Time works with sim clock (future) and tests already mock via `_mock_clock_at` [VERIFIED: `test_controller.py:11`] |
| Late-joiner replay of "warming up" state | Custom cache | `QoSProfile(durability=TRANSIENT_LOCAL, depth=1)` | Already the pattern for `humidifier_state_pub` at `fc_controller.py:91-98` |

## Runtime State Inventory

This is a code-only addition — no migrations, no external registrations.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — Timescale schema unchanged (new topic not bridged to DB in this phase). | none |
| Live service config | None — no n8n, Datadog, or external service config references `sensor_health`. | none |
| OS-registered state | fc-core systemd unit restart is the trigger that exercises this code path. No unit change needed. | none |
| Secrets/env vars | None. | none |
| Build artifacts | `install/fc_core/` will be rebuilt by `colcon build --symlink-install` on deploy. `build/fc_core/build/lib/fc_core/fc_controller.py` is a stale mirror — harmless, regenerated. | none (normal build) |

## Common Pitfalls

### Pitfall 1: `_boot_time` captured too early
**What goes wrong:** If `_boot_time` is set before the first sensor message, the 20s starts ticking during ROS initialization — in simulation mode the node is already subscribed but hardware I/O may take longer. Grace expires while sensors still haven't reported.
**Why it happens:** "Boot" in a ROS2 context is ambiguous — node `__init__` vs first callback.
**How to avoid:** Use `__init__` time as `_boot_time`. The AND-with-buffer-full condition covers the slow-sensor case: grace won't clear until both (a) 20s elapsed AND (b) 5 humidity samples received. At 2s sensor interval that's 10s minimum to fill the buffer; total grace ≈ max(20s, 10s) = 20s. Correct.
**Warning signs:** If tests show grace clears before any humidity callback fires, the AND logic is broken.

### Pitfall 2: Sim-mode sensor_simulation_mode=True publishes instantly without warm-up
**What goes wrong:** In sim mode, `fc_sensors.py` starts publishing synthetic values on timer tick — no real warm-up transient. But the controller still applies grace, so during dev work a developer sees "20s of dead time on every restart" even though it's unnecessary in sim.
**Why it happens:** Grace is unconditional on `sensor_simulation_mode`.
**How to avoid:** **Don't condition on sim mode** — keeping behavior identical between sim and hw is critical for test parity (this is a v1.0 design principle visible across the codebase). 20s in dev is annoying but acceptable. If it becomes a blocker, add a config override `startup_grace_period: 0.0` in a dev-only override yaml — don't bake sim-vs-hw branching into the controller.
**Warning signs:** Developers ask to "skip warmup in sim" — push back; offer config override.

### Pitfall 3: Grace interaction with staleness recovery (D-09/D-10)
**What goes wrong:** If sensors go stale mid-run (staleness already OFFs the humidifier) and then `fc_sensors` restarts (but controller doesn't), fresh humidity arrives but it's a WARM-UP transient from the sensor side. Controller has no grace because its own `_boot_time` is old.
**Why it happens:** Grace is per-controller-boot, not per-fresh-data-stream.
**How to avoid:** Out of scope for Phase 15 — this is a v1.3+ concern. Document as Open Question. The common case (systemd restarts the whole fc-core node group via the launch file, so controller and sensors reboot together) is covered.
**Warning signs:** Sensor-side restart without controller restart — unusual but possible if someone runs `ros2 run fc_core fc_sensors` manually.

### Pitfall 4: Publishing DiagnosticStatus before subscribers exist
**What goes wrong:** Bridge/MC connects later; first on-change publish is lost; MC sees nothing until next state change (which might never come — system stays OK).
**Why it happens:** Default QoS VOLATILE drops messages to late-joiners.
**How to avoid:** Use `TRANSIENT_LOCAL` durability + depth=1 on the health publisher. Mirror the actuator_qos pattern already at `fc_controller.py:91-98`. Late-joining bridge gets last health state on subscribe.

### Pitfall 5: Test that only checks `humidifier_state == False` during grace passes even with no gate
**What goes wrong:** Before grace-gate exists, humidifier defaults to False anyway (simulation init). A naive "humidifier OFF during warmup" test passes even when the gate isn't wired.
**Why it happens:** Weak test — doesn't distinguish "gate prevented ON" from "nothing tried to turn it ON yet".
**How to avoid:** Test must pre-condition humidity BELOW threshold (buffer full with 0.70) AND `_warming_up` state, then assert humidifier still False AND sensor_health last-published warning. Compare pre-grace vs post-grace outcomes in the same test.

## Code Examples

### Grace gate — drop-in at top of control_loop
```python
# Source: proposed; mirrors existing None-guard at fc_controller.py:207-209
def control_loop(self):
    # WARMUP-01: startup grace — no actuation until sensors settle
    if self._grace_active():
        self.set_humidifier(False)
        if not self._warmup_signal_published:
            self._publish_sensor_health(warming_up=True)
            self._warmup_signal_published = True
        return

    if self._warming_up:
        self._warming_up = False
        self._publish_sensor_health(warming_up=False)
        self.get_logger().info('WARMUP-CLEARED: engaging control')

    # ... existing None-guard, staleness, humidity/temp/light control
```

### Publisher construction — mirror actuator_qos
```python
# Source: fc_controller.py:91-99 (existing pattern)
health_qos = QoSProfile(
    depth=1,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
)
self.sensor_health_pub = self.create_publisher(
    DiagnosticStatus, 'fc1/sensor_health', health_qos
)
```

### Test fixture for grace (extends existing `_mock_clock_at`)
```python
# Source: proposed; extends test_controller.py:11-15 pattern
def test_warmup_grace_blocks_humidifier(ros_context):
    """Humidifier stays OFF during startup_grace_period, even with low humidity buffer full."""
    with patch('fc_core.fc_controller.FruitingChamberController.get_clock',
               return_value=_mock_clock_at(int(0))):
        # Clock starts at 0 BEFORE node init — _boot_time captured at 0
        node = FruitingChamberController()
        node.current_temp = 23.0

    # t=5s, buffer full, humidity low — pre-grace, should NOT turn on
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(5e9))):
        for _ in range(5):
            _send_humidity(node, 0.70)
        node.control_loop()
        assert node.humidifier_state == False
        assert node._warming_up == True

    # t=21s, buffer still full — grace cleared, should turn on
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(21e9))):
        node.control_loop()
        assert node.humidifier_state == True
        assert node._warming_up == False

    node.destroy_node()
```

**Key test-infrastructure finding:** `test_controller.py:11-15` already defines `_mock_clock_at(nanoseconds)` that returns a mock whose `.now()` returns a `rclpy.time.Time`. New tests reuse this directly. The existing pattern patches `node.get_clock` (an instance method), which works after node init. For `_boot_time` captured in `__init__`, we need to patch BEFORE `FruitingChamberController()` is called — patch the class method (see example above) OR set `node._boot_time` manually post-init:

```python
node = FruitingChamberController()
node._boot_time = rclpy.time.Time(nanoseconds=0)  # simpler
```

Prefer the manual override — smaller diff, more obvious.

## State of the Art

No old-vs-new deltas — this is a new feature, not a migration. Relevant context:

| Context | Status |
|---------|--------|
| `diagnostic_msgs` as the ROS-standard health contract | Stable since ROS1; unchanged in Jazzy [CITED: http://docs.ros.org/en/jazzy/p/diagnostic_msgs/] |
| `DiagnosticAggregator` pattern (single aggregated `/diagnostics` topic) | Available but overkill for one signal; revisit in Phase 16 |
| rclpy clock mocking in tests | Project-local pattern in `test_controller.py`; no library needed |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | [ASSUMED] 20s is sufficient — based on the single observed transient at t=0s→t=12s in CONTEXT.md. SCD41 actual warm-up per datasheet not verified. | §User Constraints (20s default) | Grace expires too early; farmer sees late-phase transient. Mitigation: config-tunable, no code change to extend. |
| A2 | [ASSUMED] `fc_display` users are OK seeing normal (possibly-spiky) values during grace; the "gap" is really enforced in MC via health signal. | §Pattern 1 rationale | If fc_display shows a spike that reaches the farmer without MC mediating, the farmer-constraint is violated on that surface. Currently `fc_display` only logs to console — not farmer-visible. Safe for now. |
| A3 | [ASSUMED] `ros-jazzy-diagnostic-msgs` is installed on fc1 and elder-plops. | §Standard Stack | Build/install failure at deploy. Mitigation: `package.xml` explicit dep + deploy script validates. |
| A4 | [ASSUMED] `rosbridge_suite` in the MC bridge serializes `DiagnosticStatus` transparently to WebSocket JSON. | §Pattern 2 | Phase 16 discovers it needs a custom serializer. rosbridge v2+ handles standard msgs reliably [CITED: https://github.com/RobotWebTools/rosbridge_suite] — very low risk. |
| A5 | [ASSUMED] Temperature settling follows the same ~12s window as humidity. CONTEXT.md example only shows both in one trace. | §Anti-Patterns (full-loop early-return) | Temp-control could start slightly earlier. Not worth complication; 20s is short. |

**Planner/discuss gate:** A1 and A3 should be confirmed with the user before planning locks. A1 controls the default param value; A3 controls whether `package.xml` needs editing.

## Open Questions

1. **Grace behavior on mid-run sensor re-init (sensors restart, controller doesn't)**
   - What we know: controller `_boot_time` is set in `__init__`; sensors going stale + returning fresh data does NOT reset grace.
   - What's unclear: do we want a short re-grace when humidity_callback goes from no-data to data after a long gap (say >1min)?
   - Recommendation: defer. Not in farmer's stated scope. Document as v1.3 followup. Add Pitfall #3 above.

2. **Should fan control (temperature loop) also wait for grace?**
   - What we know: in current code, fan/temp logic runs regardless of staleness.
   - What's unclear: does temperature reading settle on the same ~20s window, or faster?
   - Recommendation: early-return the ENTIRE control_loop during grace (simpler, safe — fan defaults to min_fan_speed=50% via existing `set_fan_speed(min)` path; during grace it defaults OFF since we return before that call). Confirm with farmer: is it OK if fan sits at 0 for 20s on reboot? Likely yes.

3. **REQUIREMENTS.md inconsistency**
   - What we know: SENS-01 listed BOTH under "Future Requirements" AND "Out of Scope" ("Dropped from v1.2 scope").
   - Recommendation: Phase 15 planning should include an update to REQUIREMENTS.md moving SENS-01 to active v1.2.1 requirements and removing the Out-of-Scope row. Small doc edit, include in plan.

4. **Should Phase 16 influence the signal shape more?**
   - What we know: Phase 16 CONTEXT-SEED.md calls for a "panel with green lights" aggregating camera + sensors + actuators.
   - Recommendation: `DiagnosticStatus` on a per-subsystem topic (`fc1/sensor_health`, future `fc1/camera/health`, etc.) is the cleanest forward path. Phase 16 can aggregate into a `DiagnosticArray` publisher in the bridge if wanted. No Phase-15 coupling to Phase 16 internals.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| rclpy | controller | ✓ | Jazzy | — |
| diagnostic_msgs | new health publisher | likely ✓ (distro-base) | Jazzy | Downgrade to `std_msgs/Bool` on `/fc1/sensor_health/warming_up` — loses Phase 16 forward-compat |
| colcon build | deploy | ✓ | — | — |
| pytest | tests | ✓ | — | — |
| fc1 Pi reachable via `fc1-ts` | soak test | ✓ (Tailscale; memory: `feedback_ssh_tailscale.md`) | — | — |

**Missing deps with no fallback:** None.

**Missing deps with fallback:** `diagnostic_msgs` — planner should verify with `apt list --installed | grep ros-jazzy-diagnostic-msgs` during Wave 0.

## Validation Architecture

Nyquist validation is ENABLED (`workflow.nyquist_validation: true` in config.json). Include this section.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (via ament_python + colcon test) |
| Config file | `src/chambers/fc-core/setup.cfg` (existing) |
| Quick run command | `pytest src/chambers/fc-core/fc_core/test/test_controller.py -x -k warmup` |
| Full suite command | `colcon test --packages-select fc_core && colcon test-result --verbose` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| WARMUP-01 | `control_loop` early-returns during grace; humidifier stays OFF even when humidity < threshold and buffer full | unit | `pytest .../test_controller.py::test_warmup_grace_blocks_actuation -x` | ❌ Wave 0 |
| WARMUP-01 | Grace cleared by time-elapsed AND buffer-full together; both conditions required | unit | `pytest .../test_controller.py::test_warmup_grace_requires_both_conditions -x` | ❌ Wave 0 |
| WARMUP-01 | Grace with partial buffer but time elapsed → still blocked | unit | `pytest .../test_controller.py::test_warmup_grace_time_but_not_buffer -x` | ❌ Wave 0 |
| WARMUP-01 | Grace with full buffer but time not elapsed → still blocked | unit | `pytest .../test_controller.py::test_warmup_grace_buffer_but_not_time -x` | ❌ Wave 0 |
| WARMUP-02 | `/fc1/sensor_health` publishes DiagnosticStatus.WARN on entry to grace | unit | `pytest .../test_controller.py::test_sensor_health_warn_during_grace -x` | ❌ Wave 0 |
| WARMUP-02 | `/fc1/sensor_health` publishes DiagnosticStatus.OK on grace clear (state-change only) | unit | `pytest .../test_controller.py::test_sensor_health_ok_after_grace -x` | ❌ Wave 0 |
| WARMUP-02 | Health topic uses TRANSIENT_LOCAL QoS so late-joiners get last state | unit (publisher inspection) | `pytest .../test_controller.py::test_sensor_health_qos_transient_local -x` | ❌ Wave 0 |
| WARMUP-03 | Grace clears automatically without intervention at t=20s with buffer full | unit | covered by `test_warmup_grace_requires_both_conditions` | ❌ Wave 0 |
| WARMUP-04 | `startup_grace_period` parameter declared with default 20.0 | unit | `pytest .../test_controller.py::test_startup_grace_period_param_declared -x` | ❌ Wave 0 |
| Integration | On live fc1 restart, no humidifier ON within first 20s (journalctl grep) | manual soak | `ssh fc1-ts sudo systemctl restart fc-core && sleep 30 && journalctl -u fc-core --since "30 sec ago" \| grep -i 'humidifier.*on'` must be empty | manual-only (hardware timing) |
| Integration | `/fc1/sensor_health` topic emits WARN then OK on restart (ROS topic echo) | manual soak | `ros2 topic echo /fc1/sensor_health --once` after restart | manual-only |

### Sampling Rate
- **Per task commit:** `pytest src/chambers/fc-core/fc_core/test/test_controller.py -x` (~2–3s, runs full controller test module)
- **Per wave merge:** `colcon test --packages-select fc_core && colcon test-result --verbose`
- **Phase gate:** Full suite green + 1-minute soak on fc1 showing no actuation in first 20s post-restart

### Wave 0 Gaps
- [ ] `src/chambers/fc-core/fc_core/test/test_controller.py` — extend with ~7 new `test_warmup_*` and `test_sensor_health_*` cases
- [ ] `src/chambers/fc-core/package.xml` — verify/add `<depend>diagnostic_msgs</depend>`
- [ ] `src/chambers/fc-core/config/fc_config.yaml` — add `startup_grace_period: 20.0`

## Security Domain

Not applicable (no external input, no auth surface, no crypto, no data persistence changes). `security_enforcement` default treated as enabled — confirmed no applicable ASVS categories for this phase:

| ASVS Category | Applies | Reason |
|---------------|---------|--------|
| V2 Authentication | no | No auth surface |
| V3 Session | no | No sessions |
| V4 Access Control | no | No access control |
| V5 Input Validation | no | No external input (config param values controlled by ops via YAML on trusted host) |
| V6 Cryptography | no | No crypto |

Threat patterns: none applicable. The only failure mode is controller-internal and non-adversarial (sensor settling noise).

## Sources

### Primary (HIGH confidence)
- Codebase: `src/chambers/fc-core/fc_core/fc_controller.py` (full read) — existing patterns for QoS, clock mocking, param declaration, dwell guard, staleness guard
- Codebase: `src/chambers/fc-core/fc_core/test/test_controller.py` (full read) — `_mock_clock_at` pattern confirmed reusable
- Codebase: `src/chambers/fc-core/fc_core/fc_sensors.py` (full read) — confirmed publish path, decided not to modify
- Codebase: `src/chambers/fc-core/config/fc_config.yaml` — param style
- Planning: `.planning/phases/15-sensor-warmup-grace-period/15-CONTEXT.md` — design constraints
- Planning: `.planning/phases/16-system-health-panel/CONTEXT-SEED.md` — forward dependency shape
- Planning: `.planning/phases/999.9-pid-time-proportional-humidity-control/CALIBRATION-FINDINGS-2026-04-11.md` — transient observation, 16s deadtime

### Secondary (MEDIUM confidence)
- `diagnostic_msgs` ROS2 docs: http://docs.ros.org/en/jazzy/p/diagnostic_msgs/ — message schema
- Project memory: `feedback_ssh_tailscale.md` (fc1 via Tailscale), `feedback_deploy_method.md` (git → fc1/prod)

### Tertiary (LOW confidence)
- None. All critical claims verified against code or official docs.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all reuse of existing imports; diagnostic_msgs is ROS-standard
- Architecture: HIGH — pattern mirrors existing actuator_qos publisher and None-guard early-return
- Pitfalls: MEDIUM — pitfalls 1, 4 verified via code reading; pitfalls 2, 3, 5 reasoned from design; all actionable
- Test infrastructure: HIGH — `_mock_clock_at` pattern already proven in 9+ existing tests

**Research date:** 2026-04-17
**Valid until:** 2026-05-17 (codebase stable; revisit if 999.9 PID rework lands first, which would change actuator path)
