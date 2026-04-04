---
phase: 04-observability-integration
plan: "01"
subsystem: fc_core/controller, mission-control/frontend
tags: [actuator-publishing, openmct, ros2-qos, transient-local, tdd, observability]
dependency_graph:
  requires: [03-03]
  provides: [humidifier-state-topic, co2-dashboard-entry, humidifier-dashboard-entry]
  affects: [fc_controller.py, test_controller.py, plugin.js]
tech_stack:
  added:
    - rclpy.qos.QoSProfile with DurabilityPolicy.TRANSIENT_LOCAL
    - std_msgs.msg.Bool publisher
  patterns:
    - TRANSIENT_LOCAL QoS for actuator state topics (late-joiners get last value)
    - OpenMCT SENSORS array extension pattern for new telemetry types
key_files:
  created: []
  modified:
    - src/chambers/fc-core/fc_core/fc_controller.py
    - src/chambers/fc-core/fc_core/test/test_controller.py
    - src/mission-control/frontend/plugins/fruiting-chamber/plugin.js
decisions:
  - "TRANSIENT_LOCAL, RELIABLE, depth=1 QoS for humidifier_state_pub — late subscribers receive last known state immediately (D-01, ACTR-03)"
  - "Bool.data ? 1 : 0 conversion in extract function — allows standard numeric chart rendering in OpenMCT"
  - "CO2 chart range 300-5000 ppm — ambient ~415 ppm, full range covers fresh air through CO2 accumulation"
  - "Humidifier state published after light control on every control_loop tick — unconditional, reflects actual hardware state"
requirements:
  - ACTR-03
  - SENS-02
metrics:
  duration: 12min
  completed: "2026-04-04"
  tasks: 2
  files: 3
---

# Phase 04 Plan 01: Actuator State Publishing and OpenMCT Dashboard Extension Summary

**One-liner:** Added `fc/actuators/humidifier` Bool topic with TRANSIENT_LOCAL QoS to fc_controller.py (ACTR-03) and extended OpenMCT plugin with CO2 and humidifier chart entries, giving the grower a live 4-panel dashboard.

## What Was Built

### Task 1: Humidifier State Publisher (ACTR-03)

1. **New imports in `fc_controller.py`**:
   - `from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, HistoryPolicy`
   - `from std_msgs.msg import Bool`

2. **Publisher in `__init__`** (after humidity subscriber):
   - QoSProfile: `TRANSIENT_LOCAL`, `RELIABLE`, `depth=1`, `KEEP_LAST`
   - `self.humidifier_state_pub = self.create_publisher(Bool, 'fc/actuators/humidifier', actuator_qos)`

3. **Publish call in `control_loop()`** (after light control, before debug log):
   - Creates `Bool()` message, sets `.data = self.get_humidifier_state()`
   - Publishes every control tick (unconditional)

4. **TDD RED commit**: `test_humidifier_state_published` — verifies `publish` called once per tick with correct bool value

5. **Pre-existing bug fixed** in `test_temperature_control`:
   - Replaced `node.fan_pwm.get_duty_cycle()` (AttributeError in simulation mode) with `node.fan_speed`
   - This was a known pre-existing failure from Phase 3 summary

### Task 2: OpenMCT Plugin Extension (D-04, D-05)

Extended `SENSORS` array in `plugin.js` from 2 to 4 entries:

| Key | Topic | MsgType | Range |
|-----|-------|---------|-------|
| fc.humidity | /fc/humidity | sensor_msgs/msg/RelativeHumidity | 50-100% |
| fc.temperature | /fc/temperature | sensor_msgs/msg/Temperature | 10-35°C |
| fc.co2 | /fc/co2 | std_msgs/msg/Float32 | 300-5000 ppm |
| fc.humidifier | /fc/actuators/humidifier | std_msgs/msg/Bool | 0-1 |

- CO2 extract: `msg.data` (Float32 rosbridge JSON: `{"data": 415.3}`)
- Humidifier extract: `msg.data ? 1 : 0` (bool to numeric for chart rendering)
- `getTimestamp()` fallback to `Date.now()` handles messages without `header.stamp`
- `bridge/src/index.js` NOT modified (dead code per RESEARCH.md Pitfall 1)

## Commits

| Hash    | Type | Description |
|---------|------|-------------|
| 5439790 | test | Add failing test for humidifier state publishing (RED) |
| 129244e | feat | Add humidifier state publisher with TRANSIENT_LOCAL QoS (ACTR-03) |
| 04ec9fe | feat | Add CO2 and humidifier telemetry to OpenMCT plugin (D-04, D-05) |

## Test Results

19/20 tests pass. The 1 failure (`test_light_control`) is a pre-existing bug where the test calls `node.set_parameter()` which does not exist on ROS2 Node — this was out of scope for this plan and pre-dates Phase 4.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed pre-existing test_temperature_control assertion**
- **Found during:** Task 1 GREEN verification
- **Issue:** `node.fan_pwm.get_duty_cycle()` raises AttributeError in simulation mode (`fan_pwm` is None when `actuator_simulation_mode=True`)
- **Fix:** Replaced both assertions with `node.fan_speed` which is the simulation-mode state variable
- **Files modified:** `src/chambers/fc-core/fc_core/test/test_controller.py` (lines 45, 53)
- **Commit:** 129244e (included in GREEN commit)

## Known Stubs

None — humidifier_state_pub is fully wired: publishes on every control_loop tick, OpenMCT subscribes via rosbridge on demand. CO2 and humidifier entries are live telemetry consumers.

## Threat Flags

No new threat surface beyond what was analyzed in the plan's threat model. The `fc/actuators/humidifier` topic is boolean read-only telemetry on LAN/WireGuard boundary (T-04-01, T-04-02 accepted in plan).

## Self-Check: PASSED

- `src/chambers/fc-core/fc_core/fc_controller.py` — contains `from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, HistoryPolicy`, `from std_msgs.msg import Bool`, `self.humidifier_state_pub = self.create_publisher(Bool, 'fc/actuators/humidifier', actuator_qos)`, `DurabilityPolicy.TRANSIENT_LOCAL`, `ReliabilityPolicy.RELIABLE`, `depth=1`, `state_msg.data = self.get_humidifier_state()`, `self.humidifier_state_pub.publish(state_msg)`
- `src/chambers/fc-core/fc_core/test/test_controller.py` — contains `def test_humidifier_state_published`, `node.humidifier_state_pub.publish`, `node.fan_speed` (replaces fan_pwm assertions)
- `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js` — contains `key: 'fc.co2'`, `name: 'CO2'`, `unit: 'ppm'`, `topic: '/fc/co2'`, `msgType: 'std_msgs/msg/Float32'`, `key: 'fc.humidifier'`, `name: 'Humidifier'`, `topic: '/fc/actuators/humidifier'`, `msgType: 'std_msgs/msg/Bool'`, `msg.data ? 1 : 0`; SENSORS has 4 entries
- Commits 5439790, 129244e, 04ec9fe exist in git log
