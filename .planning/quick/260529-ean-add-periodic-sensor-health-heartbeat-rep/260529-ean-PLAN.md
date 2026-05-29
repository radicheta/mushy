---
phase: quick-260529-ean
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/chambers/fc-core/fc_core/fc_controller.py
  - src/chambers/fc-core/fc_core/test/test_controller.py
autonomous: true
requirements: [QUICK-260529-ean]
must_haves:
  truths:
    - "A perfectly healthy, stable SHT30 causes sensor_health to be republished at least once per heartbeat interval, even with no freshness flip."
    - "A flip-based publish resets the heartbeat clock so the controller never double-publishes (flip + heartbeat) in the same window."
    - "The heartbeat does not fire during the startup grace window (the warmup WARN publish covers that period)."
    - "Real-failure detection is preserved: Pi-authoritative *_fresh=='false' still flips and publishes immediately."
    - "_last_sht30_fresh / _last_scd41_fresh bookkeeping is unchanged — flip detection still works after the heartbeat lands."
  artifacts:
    - path: "src/chambers/fc-core/fc_core/fc_controller.py"
      provides: "Periodic heartbeat republish of sensor_health gated on a shared last-publish timestamp"
      contains: "_last_sensor_health_publish"
    - path: "src/chambers/fc-core/fc_core/test/test_controller.py"
      provides: "Unit coverage for heartbeat-fires, flip-resets-clock, no-fire-in-grace"
      contains: "heartbeat"
  key_links:
    - from: "control_loop()"
      to: "_publish_sensor_health()"
      via: "heartbeat-interval elapsed check on _last_sensor_health_publish"
      pattern: "_last_sensor_health_publish"
    - from: "_publish_sensor_health()"
      to: "_last_sensor_health_publish"
      via: "every publish path stamps the shared timestamp (flip + warmup + heartbeat)"
      pattern: "self\\._last_sensor_health_publish ="
---

<objective>
Add a periodic heartbeat republish of `fc1/sensor_health` from `fc_controller.control_loop()` so the alerter's per-physical-sensor freshness watchdog (`isSensorSilent` in `src/agents/alerter/src/state.js`) keeps receiving DiagnosticStatus messages even when a healthy, stable sensor never causes a freshness flip.

Purpose: The `sensor_health` topic is deliberately QUIET / TRANSIENT_LOCAL — fc_controller currently publishes ONLY on freshness flips (control_loop lines ~1576-1578) and warmup transitions (lines ~1563, ~1569). A perfectly healthy SHT30 (the PRIMARY RH sensor) never triggers a republish, so the alerter's `sht30LastSeenMs` goes stale and after `sensor_offline_min` minutes the watchdog false-fires "Primary Humidity Sensor offline", re-firing hourly on the critical cooldown. The `.env` band-aid `ALERT_SENSOR_OFFLINE_MIN=1440` is silently shadowed by `fc_config.yaml sensor_offline_min:20` (globals shadow env; validator caps the range). A heartbeat republish feeds the watchdog regardless of flips, preserving real-failure detection (Pi-authoritative `*_fresh==='false'` still flips immediately) AND newly catching a silently-stalled controller.

Output: ~5-10 lines in `fc_controller.py` (a shared last-publish timestamp + a heartbeat check in `control_loop`), plus 3 unit tests in `test_controller.py`.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@./CLAUDE.md

<interfaces>
<!-- Key code already in the file. The executor uses these directly — no exploration needed. -->

fc_controller.py init block (~lines 354-360), already present:
```python
self._last_sht30_fresh = None   # tri-state; None means "not yet evaluated"
self._last_scd41_fresh = None
# (...)
self._boot_time = self.get_clock().now()
self._warming_up = True
self._warmup_signal_published = False
```

Control timer setup (~line 388):
```python
self.timer = self.create_timer(
    self.get_parameter('control_interval').value,
    self.control_loop
)
```

_publish_sensor_health (~line 1480) — already stamps the freshness bookkeeping at the end:
```python
def _publish_sensor_health(self, warming_up: bool):
    # ...builds DiagnosticStatus msg with sht30_fresh / scd41_fresh KeyValues...
    self.sensor_health_pub.publish(msg)
    self._last_sht30_fresh = sht30_fresh
    self._last_scd41_fresh = scd41_fresh
```

control_loop publish paths (~lines 1558-1578):
```python
# WARMUP-01 grace: publishes WARN once (guarded by _warmup_signal_published)
if self._grace_active():
    # ...
    if not self._warmup_signal_published:
        self._publish_sensor_health(warming_up=True)
        self._warmup_signal_published = True
    return

if self._warming_up:                       # grace-exit transition
    self._warming_up = False
    self._publish_sensor_health(warming_up=False)
    # ...

# Phase 26 D-03: flip-based republish (state-change only)
sht30_fresh = self._compute_sht30_fresh()
scd41_fresh = self._compute_scd41_fresh()
if (sht30_fresh != self._last_sht30_fresh
        or scd41_fresh != self._last_scd41_fresh):
    self._publish_sensor_health(warming_up=False)
```

Clock idiom in use everywhere in this node: `self.get_clock().now()` returning an rclpy `Time`; elapsed seconds computed as `(self.get_clock().now() - <stored Time>).nanoseconds / 1e9`. Match this idiom (NOT `time.monotonic()` — the rest of sensor_health/freshness math uses ROS clock so tests can drive it).

Test infra (test_controller.py): tests instantiate `FruitingChamberController()` directly, set `node._boot_time = rclpy.time.Time(nanoseconds=0, clock_type=_ROS_TIME)`, override `node._grace_active = lambda: False` to bypass grace, and capture publishes via `node.sensor_health_pub.publish = lambda msg: published.append(msg)`. `_ROS_TIME` and the `ros_context` fixture already exist in the file.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add shared last-publish timestamp + heartbeat republish in control_loop</name>
  <files>src/chambers/fc-core/fc_core/fc_controller.py</files>
  <behavior>
    - HEARTBEAT FIRES: With grace bypassed and no freshness flip, after the heartbeat interval has elapsed since the last sensor_health publish, control_loop() publishes a fresh DiagnosticStatus on sensor_health (warming_up=False).
    - FLIP RESETS CLOCK: A flip-based publish stamps the same timestamp, so a heartbeat does NOT additionally fire in the same window (no double-publish on the tick where a flip already published).
    - NO HEARTBEAT IN GRACE: While _grace_active() is true, the heartbeat path is never reached (control_loop returns early after the warmup WARN publish); the warmup publish stamps the timestamp so the first post-grace heartbeat is measured from grace exit, not boot.
    - STEADY STATE: Across many ticks with a stable sensor and no flip, the gap between consecutive sensor_health publishes never exceeds the heartbeat interval.
  </behavior>
  <action>
    Define a module-level constant near the top of fc_controller.py (alongside other module constants), `SENSOR_HEALTH_HEARTBEAT_SEC = 60.0`, with a comment stating it must stay comfortably below the alerter's effective sensor-offline watchdog (fc_config `sensor_offline_min` clamped to the validator's [1,60]-minute range; 60s is well under 1 minute... note: choose 60.0s — well under even the minimum 1-minute clamp floor, so it is robust to any in-range watchdog value). Do NOT add a new fc_config param — a module constant is the clean choice for a quick task (per constraints).

    In __init__, after the `_warmup_signal_published = False` line (~360), initialize `self._last_sensor_health_publish = None`. None means "never published yet"; the warmup WARN publish (or the first flip) will stamp it. This keeps the heartbeat from firing during the startup grace window because control_loop returns early in grace before reaching the heartbeat check, and the heartbeat check treats None as "not due yet from a heartbeat standpoint" only AFTER a real publish has stamped it — see next point.

    Centralize timestamp bookkeeping inside `_publish_sensor_health()`: at the END of the method (right after the existing `self._last_scd41_fresh = scd41_fresh` line ~1514), add `self._last_sensor_health_publish = self.get_clock().now()`. This makes EVERY publish path (warmup WARN, grace-exit OK, flip, heartbeat) reset the shared heartbeat clock — satisfying the constraint that a flip resets the heartbeat clock and avoids double-publishing.

    In control_loop(), AFTER the existing flip-based republish block (after line ~1578) and BEFORE the `if self.current_temp is None ...` block (~1580), add the heartbeat check: if `self._last_sensor_health_publish is not None` AND `(self.get_clock().now() - self._last_sensor_health_publish).nanoseconds / 1e9 >= SENSOR_HEALTH_HEARTBEAT_SEC`, then call `self._publish_sensor_health(warming_up=False)`. Because _publish_sensor_health stamps `_last_sensor_health_publish`, the next heartbeat is measured from this publish. Guarding on `is not None` ensures the heartbeat never fires before the first real (warmup) publish has occurred — defense alongside the grace early-return.

    Do NOT alter the flip-based publish (lines ~1576-1578) or the warmup publishes (~1563, ~1569). Do NOT change _compute_sht30_fresh / _compute_scd41_fresh / freshness bookkeeping — verify they remain intact.
  </action>
  <verify>
    <automated>cd src/chambers/fc-core && python -c "import ast,sys; ast.parse(open('fc_core/fc_controller.py').read()); print('syntax-ok')"</automated>
  </verify>
  <done>
    fc_controller.py parses; `SENSOR_HEALTH_HEARTBEAT_SEC = 60.0` module constant exists; `self._last_sensor_health_publish` initialized in __init__; _publish_sensor_health stamps it on every call; control_loop has a heartbeat check after the flip block that calls _publish_sensor_health(warming_up=False) when the interval has elapsed; flip and warmup publish paths unchanged.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Unit tests for heartbeat-fires, flip-resets-clock, no-fire-in-grace</name>
  <files>src/chambers/fc-core/fc_core/test/test_controller.py</files>
  <behavior>
    - test_sensor_health_heartbeat_republishes_when_stale: grace bypassed, no flip, drive the clock forward past SENSOR_HEALTH_HEARTBEAT_SEC since the last publish -> exactly one heartbeat publish lands with warming_up=='false' (DiagnosticStatus.OK).
    - test_sensor_health_heartbeat_clock_reset_by_flip: a flip publish stamps _last_sensor_health_publish; a control_loop tick immediately after (clock not advanced past the interval) does NOT add a second publish.
    - test_sensor_health_heartbeat_not_fired_in_grace: with _grace_active()->True, advancing the clock far past the heartbeat interval produces only the single warmup WARN publish, never an extra OK heartbeat.
  </behavior>
  <action>
    Add three tests following the existing patterns in test_controller.py (use the `ros_context` fixture, `node = FruitingChamberController()`, capture publishes via `node.sensor_health_pub.publish = lambda msg: published.append(msg)`).

    To drive time deterministically, control the node clock the same way other tests do — set `node._boot_time` and/or monkeypatch `node.get_clock` to return a stub whose `.now()` returns a caller-advanced `rclpy.time.Time(nanoseconds=..., clock_type=_ROS_TIME)`. A small helper that returns a Time at a settable nanosecond offset is sufficient (mirror the `_ROS_TIME` Time construction already used at lines ~273/360). Import `SENSOR_HEALTH_HEARTBEAT_SEC` from `fc_core.fc_controller` and convert to nanoseconds for the advance.

    For the heartbeat-fires test: bypass grace (`node._grace_active = lambda: False`), set `node._warming_up = False`, seed `_last_sht30_fresh`/`_last_scd41_fresh` equal to what `_compute_*_fresh()` will return so NO flip occurs (or stub `_compute_sht30_fresh`/`_compute_scd41_fresh` to constants and set the matching `_last_*` attrs), set `node._last_sensor_health_publish` to a Time at T0, advance the clock to T0 + (interval + epsilon), call `control_loop()`, assert exactly one captured publish with the `warming_up` KeyValue == 'false'.

    For the clock-reset test: same setup, set `_last_sensor_health_publish` to T0, advance clock to a point well under the interval, call control_loop once -> assert zero NEW publishes (no flip, not yet due).

    For the grace test: `node._grace_active = lambda: True`, `node._warmup_signal_published = False`, advance the clock far past the interval, call control_loop twice; assert exactly one publish total (the warmup WARN), and its level is DiagnosticStatus.WARN.

    Keep the tests self-contained and avoid coupling to actuator/PID side effects (grace/flip-only paths return before the PID hot loop, or stub current_temp/current_humidity to None as needed). Always `node.destroy_node()` at the end.
  </action>
  <verify>
    <automated>cd src/chambers/fc-core && python -m pytest fc_core/test/test_controller.py -k "heartbeat" -x -q</automated>
  </verify>
  <done>
    Three heartbeat tests pass; existing test_controller.py tests still pass (run `python -m pytest fc_core/test/test_controller.py -q` to confirm no regressions).
  </done>
</task>

</tasks>

<verification>
1. Static: `python -c "import ast; ast.parse(open('src/chambers/fc-core/fc_core/fc_controller.py').read())"` succeeds.
2. Unit: `cd src/chambers/fc-core && python -m pytest fc_core/test/test_controller.py -q` — all pass (3 new heartbeat tests + existing sensor_health/flip/grace tests unchanged).
3. (Optional, if a ROS2 env is sourced) `colcon build --packages-select fc_core --symlink-install` then `colcon test --packages-select fc_core`.

**Deploy / live-verify (HUMAN, gated — do NOT run from this plan):**
This change deploys to fc1 (Raspberry Pi). Per the fc1 remote-action preflight protocol the executor must NOT ssh-deploy. The operator runs: edit is already committed -> `git push fc1/prod` -> `scripts/pi-deploy` (or `fc-update.service` on boot) which does `colcon build` (fc_msgs then fc_core) -> restart fc-core. Then observe `ros2 topic echo fc1/sensor_health` shows a fresh DiagnosticStatus at least once per ~60s with `sht30_fresh: true`, and confirm the alerter no longer emits "Primary Humidity Sensor offline" for a healthy SHT30. (Reference: memory `feedback_fc1_remote_action_preflight_protocol`, `feedback_deploy_method`.)
</verification>

<success_criteria>
- A stable, healthy sensor causes sensor_health to republish at least once per SENSOR_HEALTH_HEARTBEAT_SEC (~60s), independent of freshness flips.
- A freshness flip resets the heartbeat clock (shared `_last_sensor_health_publish`), so no double-publish in the same window.
- No heartbeat publish during the startup grace window.
- Existing flip-based and warmup publish behavior unchanged; freshness bookkeeping intact.
- No new fc_config param introduced (module constant only).
- Tests green; ROS clock idiom (`self.get_clock().now()`) used for the heartbeat timing.
</success_criteria>

<output>
Create `.planning/quick/260529-ean-add-periodic-sensor-health-heartbeat-rep/260529-ean-SUMMARY.md` when done.
</output>
