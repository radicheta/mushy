---
phase: 26
plan: 01
subsystem: fc_core
tags: [ros2, python, pytest, sensors, freshness, sht30, scd41, frame_id]
requires:
  - sensor_msgs.msg.Temperature
  - sensor_msgs.msg.RelativeHumidity
  - diagnostic_msgs.msg.DiagnosticStatus
  - rclpy
provides:
  topics:
    - "/fc1/temperature_2 (sensor_msgs/Temperature, depth=10) — SCD41-only, frame_id='scd41'"
    - "/fc1/humidity_2 (sensor_msgs/RelativeHumidity, depth=10) — SCD41-only, frame_id='scd41'"
  topic-fields:
    - "/fc1/temperature header.frame_id ∈ {'sht30','scd41'} — physical-sensor provenance"
    - "/fc1/humidity header.frame_id ∈ {'sht30','scd41'} — physical-sensor provenance"
  sensor_health-keys:
    - "sht30_fresh ('true'|'false') — derived from slot-1 frame_id provenance"
    - "scd41_fresh ('true'|'false') — derived from slot-2 arrival timestamps"
affects:
  - mission_control_bridge (next: Plan 02 — forwards slot-2 topics + freshness keys)
  - alerter (next: Plan 03 — consumes sht30_fresh / scd41_fresh for offline alarms)
tech-stack:
  added:
    - "Per-physical-sensor try/except guard (Pitfall 1 fix)"
    - "frame_id-driven liveness propagation across producer→consumer (Phase 26 contract)"
  patterns:
    - "Slot-2 dual-publishing (D-02)"
    - "Quiet-topic republish-on-flip (mirrors Phase 16 sensor_health pattern for new freshness keys)"
key-files:
  created:
    - "src/chambers/fc-core/fc_core/test/test_sensors.py — 6 unit tests (D-01/D-02/D-03 + frame_id provenance)"
  modified:
    - "src/chambers/fc-core/fc_core/fc_sensors.py — slot-2 publishers, per-sensor try/except, _publish_temp/_publish_humidity helpers stamping frame_id"
    - "src/chambers/fc-core/fc_core/fc_controller.py — slot-2 subs, _compute_sht30_fresh / _compute_scd41_fresh, sensor_health gains 2 KeyValues, republish-on-flip in control_loop"
    - "src/chambers/fc-core/fc_core/test/test_controller.py — appended 3 freshness tests (frame_id, slot-2, sensor_health keys)"
decisions:
  - "frame_id approach (not header.frame_id-less subscriptions): Plan 02 / 03 don't need extra wiring — controller derives SHT30 freshness directly from existing slot-1 stream"
  - "SCD41 freshness derived from slot-2 arrivals (not data_ready polling): consumer-side stays naive about producer details; matches D-03 gap-acceptable semantics"
  - "Append-only KeyValue order: existing 4 keys (warming_up, grace_elapsed_sec, grace_total_sec, buffer_full) preserved verbatim; sht30_fresh + scd41_fresh appended (Pitfall 4 — Phase 16 panel parser is positional-tolerant but order stability is the contract)"
metrics:
  duration: ~25 min
  completed: 2026-04-25T21:21:38Z
  tasks: 3
  commits: 3
  files_changed: 4
---

# Phase 26 Plan 01: Dual sensor publishing (SHT30/SCD41 slot-1 + slot-2) Summary

Implemented dual-slot sensor publishing with per-physical-sensor freshness via
`header.frame_id` provenance, and surfaced `sht30_fresh`/`scd41_fresh` boolean
flags on `/fc1/sensor_health` for downstream alerter consumption.

## Files Modified

| File | Change |
|------|--------|
| `src/chambers/fc-core/fc_core/fc_sensors.py` | Slot-2 publishers added; outer try/except split into per-sensor (SHT30/SCD41) try/except; `_publish_temp` / `_publish_humidity` helpers stamp `header.frame_id`; sim mode emits offset slot-2 values; per-sensor freshness state (`_sht30_last_read_ns`, `_scd41_last_read_ns`). |
| `src/chambers/fc-core/fc_core/fc_controller.py` | Slot-2 subscriptions + callbacks; slot-1 callbacks read `msg.header.frame_id == 'sht30'` to refresh `_last_sht30_timestamp`; `_compute_sht30_fresh` / `_compute_scd41_fresh` helpers; two new `KeyValue` entries (`sht30_fresh`, `scd41_fresh`) appended to `sensor_health.values`; republish-on-flip hook added at top of `control_loop` (post-warmup, pre-staleness-guard). |
| `src/chambers/fc-core/fc_core/test/test_sensors.py` | NEW — 6 unit tests (slot1_uses_sht30, slot1_falls_back_to_scd41, slot2_publishes_scd41, slot2_independent_of_sht30, no_stale_publish, frame_id_provenance with three sub-cases including SHT30 raise → SCD41 fallback). |
| `src/chambers/fc-core/fc_core/test/test_controller.py` | APPEND-ONLY — 3 new tests (frame_id-driven SHT30 freshness, slot-2-driven SCD41 freshness, sensor_health KeyValue append-only contract). |

## Test Results

```
$ python3 -m pytest fc_core/test/test_controller.py fc_core/test/test_sensors.py
============================== 38 passed in 0.55s ==============================
```

- `test_sensors.py`: 6/6 pass (RED→GREEN cycle clean — initial run failed 5/6 with `AssertionError: '' == 'sht30'` and `AttributeError: temp_2_pub` before Task 2; PASS after Task 2 implements `_publish_temp`/`_publish_humidity` with frame_id and slot-2 publishers).
- `test_controller.py`: 32/32 pass (29 pre-existing + 3 Phase 26 additions). No regressions.

`colcon build --packages-select fc_core --symlink-install`: success in 0.66s.

## Topic Snapshot (sim-mode launch — verified pattern, no live launch executed)

The new publishers and subscriptions are wired in fc_sensors.__init__ (creating `temp_2_pub`, `humidity_2_pub`) and fc_controller.__init__ (creating `temp2_sub`, `humidity2_sub`). On a live launch, `ros2 topic list | grep fc1` will show:

```
/fc1/co2
/fc1/humidity
/fc1/humidity_2          # NEW
/fc1/temperature
/fc1/temperature_2       # NEW
/fc1/sensor_health       # KeyValue list extended with sht30_fresh, scd41_fresh
/fc1/actuators/humidifier
```

## Evidence: frame_id provenance is wired end-to-end

Producer side (`fc_sensors.py`):
- 2 occurrences of `frame_id = 'sht30'` / `frame_id = 'scd41'` literals at slot-1 fallback gating (`slot1_t_src` / `slot1_rh_src`).
- `_publish_temp(pub, value, source)` and `_publish_humidity(pub, value, source)` helpers write `msg.header.frame_id = source` on every publish, so all 4 publish call sites (slot-1 temp, slot-1 humidity, slot-2 temp, slot-2 humidity) carry frame_id.
- Slot-2 call sites pass `'scd41'` literal directly: `self._publish_temp(self.temp_2_pub, slot2_t, 'scd41')`.

Consumer side (`fc_controller.py`):
- `temperature_callback` and `humidity_callback` each contain `if msg.header.frame_id == 'sht30': self._last_sht30_timestamp = self.get_clock().now()` (2 occurrences).
- 6 references to frame_id total in fc_controller (callbacks + slot-2 contract comments).

Test side (`test_sensors.py`):
- 22 `header.frame_id` assertions covering all six tests, including the SHT30-raises sub-case which exercises the per-sensor try/except (Pitfall 1) and proves slot-1 falls back to `'scd41'` provenance when SHT30 fails mid-read.

## Plan 02 / Plan 03 Readiness Handoff

**Plan 02 (bridge slot-2 forwarding) can now consume:**
- `/fc1/temperature_2` (sensor_msgs/Temperature, depth=10, BEST_EFFORT default QoS like slot-1)
- `/fc1/humidity_2` (sensor_msgs/RelativeHumidity, depth=10)
- `header.frame_id` field on all four temp/humidity topics carries `'sht30'` or `'scd41'` — Plan 02 should preserve this on the WS payload (pass through the frame_id field) so downstream charts/dashboards can label provenance.

**Plan 03 (alerter offline alarms) can now consume:**
- `/fc1/sensor_health` `KeyValue` list now contains:
  - `sht30_fresh: 'true' | 'false'` (string-bool)
  - `scd41_fresh: 'true' | 'false'` (string-bool)
- Republish semantics: emitted on flip only (preserves Phase 16 quiet-topic invariant). TRANSIENT_LOCAL QoS unchanged → late-joining alerter restarts get the latest state immediately.
- Alerter can drive Signal alerts directly off either flag flipping `false`. The `_last_*_fresh` tri-state means the very first publish from a fresh boot may emit immediately as the previous-state was `None`; alerter should not treat the first sample as a "transition" event (de-bounce on alerter side OR wait for the warmup-clear publish before tracking flips).

## Deviations from Plan

None of the Rule 1/2/3 categories triggered. Plan executed as written.

**One nuance worth flagging for Plan 02 review (not a deviation):** the plan's interface example showed `slot1_t_src = 'sht30' if sht30_t is not None else 'scd41'` — implemented verbatim. This means the `frame_id` is per-channel: a single read where SHT30 returns temperature successfully but raises on `relative_humidity` (theoretically possible with a partial I2C transaction) would emit slot-1 temperature with `frame_id='sht30'` and slot-1 humidity with `frame_id='scd41'`. fc_controller's freshness logic handles this correctly because either channel arriving with `'sht30'` refreshes `_last_sht30_timestamp`. The behavior is correct under the plan's contract; just calling out that it differs from a "whole-sensor-or-nothing" provenance model in case Plan 02/03 assume otherwise.

## Pre-existing Test Isolation Issue (Deferred — Out of Scope)

`pytest fc_core/test/` (collecting all three test files) fails because `test_camera.py` installs `sys.modules['rclpy']`/`sys.modules['sensor_msgs']` MagicMock stubs at module import time, which pollutes the import path for `test_controller.py` and `test_sensors.py` when those collect after it. Workaround: run `pytest fc_core/test/test_controller.py fc_core/test/test_sensors.py` (explicit file enumeration) — 38/38 pass. This issue predates Phase 26 (test_camera.py from Phase 08-01 / commit fd5b7f7) and is logged in `.planning/deferred-items.md` (created by this plan if absent) for future cleanup. **Not blocking** — colcon CI on the Pi loads each test file in its own pytest invocation via the colcon-pytest entrypoint, so the issue is dev-loop-only.

## Self-Check: PASSED

Created files exist:
- `src/chambers/fc-core/fc_core/test/test_sensors.py` — FOUND
- `.planning/phases/26-dual-sensor-publishing-offline-alarms-sht30-scd41-slot-topic/26-01-SUMMARY.md` — (this file)

Modified files updated and committed:
- `src/chambers/fc-core/fc_core/fc_sensors.py` (commit 9a41bae) — FOUND
- `src/chambers/fc-core/fc_core/fc_controller.py` (commit 4b66185) — FOUND
- `src/chambers/fc-core/fc_core/test/test_controller.py` (commit 4b66185) — FOUND

Commits exist on branch:
- `9640d99` test(26-01): add failing tests for dual-slot sensor publishing + frame_id provenance — FOUND
- `9a41bae` feat(26-01): publish SHT30/SCD41 on separate slot topics with per-sensor freshness + frame_id provenance — FOUND
- `4b66185` feat(26-01): per-sensor freshness in sensor_health via frame_id provenance — FOUND

Verification commands pass:
- `pytest fc_core/test/test_controller.py fc_core/test/test_sensors.py` → 38/38 passed
- `colcon build --packages-select fc_core --symlink-install` → exit 0
