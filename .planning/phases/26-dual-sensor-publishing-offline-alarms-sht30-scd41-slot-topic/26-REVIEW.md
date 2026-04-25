---
phase: 26-dual-sensor-publishing-offline-alarms-sht30-scd41-slot-topic
reviewed: 2026-04-25T21:37:51Z
depth: standard
files_reviewed: 14
files_reviewed_list:
  - src/chambers/fc-core/fc_core/fc_sensors.py
  - src/chambers/fc-core/fc_core/fc_controller.py
  - src/chambers/fc-core/fc_core/test/test_sensors.py
  - src/chambers/fc-core/fc_core/test/test_controller.py
  - src/mission-control/bridge/src/index.js
  - src/agents/alerter/src/state.js
  - src/agents/alerter/src/rules.js
  - src/agents/alerter/src/index.js
  - src/agents/alerter/src/message.js
  - src/agents/alerter/src/snooze.js
  - src/agents/alerter/src/config.js
  - src/agents/alerter/test/state.test.js
  - src/agents/alerter/test/snooze.test.js
  - docker-compose.override.yml
findings:
  critical: 0
  warning: 2
  info: 4
  total: 6
status: issues_found
---

# Phase 26: Code Review Report

**Reviewed:** 2026-04-25T21:37:51Z
**Depth:** standard
**Files Reviewed:** 14
**Status:** issues_found

## Summary

Phase 26 ships dual-sensor publishing on the Pi side cleanly: per-sensor `try`/`except` keeps SCD41 alive when SHT30 raises, slot-1 silent fallback is correct, slot-2 is SCD41-only with `frame_id='scd41'`, and per-physical-sensor freshness is tracked in `fc_controller` via `frame_id` provenance plus slot-2 arrival. The new tests cover the three frame_id cases (a/b/c), provenance refresh asymmetry, and append-only `sensor_health` KeyValues.

Diff scope (vs `f2fde37`) is confined to `fc_sensors.py`, `fc_controller.py`, and the two test files; `bridge/src/index.js`, the alerter modules, and `docker-compose.override.yml` are unchanged since base. The bridge already flattens `DiagnosticStatus.values` into a plain object, so the new `sht30_fresh` / `scd41_fresh` keys reach WS clients and the alerter without any bridge change required.

The most important finding is a **phase-objective gap** at the alerter end of the path: the controller publishes `level=OK` even when one physical sensor is stale, and the alerter's `isSensorError` only fires on `level === 2`. As written, a SHT30 or SCD41 outage propagates to OpenMCT/Mission Control via `sht30_fresh=false` / `scd41_fresh=false` but never produces a Signal alert. This is the headline deliverable of the phase per the ROADMAP context ("per-physical-sensor offline alarms via the Mission Control alerter"). Either the controller must escalate to `level=ERROR` on per-sensor staleness, or the alerter must inspect the new KeyValues — neither is in this diff. Flagged as a Warning rather than Critical because the existing alarms (RH OOB, Pi offline, humidifier stuck) still work and the Mission Control health surface still reflects the truth; only the new Signal pathway is incomplete.

Everything else is small: a couple of dead instance variables on `fc_sensors`, a missing test for `data_ready=False`, and a state-change re-publish that compares a bool against an initial `None` (cosmetic only — the early-return paths prevent the spurious publish from being observed).

## Warnings

### WR-01: Per-physical-sensor offline alarms never reach Signal

**File:** `src/chambers/fc-core/fc_core/fc_controller.py:283-302`, `src/agents/alerter/src/rules.js:15-17`, `src/agents/alerter/src/state.js:204-227`
**Issue:**
The phase contract is "per-physical-sensor offline alarms via the Mission Control alerter (Signal)." On the Pi side, freshness is correctly computed (`_compute_sht30_fresh` / `_compute_scd41_fresh`) and re-publication on flip is correctly gated by state change (controller lines 343-347). But:

1. `_publish_sensor_health` always sets `msg.level = WARN if warming_up else OK` (controller line 283-285). When `sht30_fresh` flips to `false` after warmup has cleared, the published level is still `OK`.
2. `isSensorError(sensorHealth)` returns `sensorHealth.level === 2` (rules.js line 16). It does not inspect `values.sht30_fresh` / `values.scd41_fresh`.
3. `state.js` `sensor_health` handler (lines 204-227) routes `level === 1` to `warmingUp = true` and `level === 0` to `warmingUp = false`; only `isError === true` (i.e., `level === 2`) drives the sensor alert state machine.

Net effect: a SHT30 or SCD41 outage refreshes Mission Control's `sensor_health` topic with the new KeyValues (good — OpenMCT and `/farmer/summary` see it), but **no Signal message is sent**, defeating the phase's stated alarm objective.

**Fix:** Pick one of the two ends. Recommended: extend the alerter to fire a sensor alert when either `values.sht30_fresh === 'false'` or `values.scd41_fresh === 'false'` (the bridge already passes them through as strings — see `bridge/src/index.js:687`). Approximate shape in `state.js`:

```javascript
case 'sensor_health': {
  const { level, values = {} } = event;
  if (level === 1) next.warmingUp = true;
  else if (level === 0) next.warmingUp = false;

  // Phase 26: per-physical-sensor offline detection via append-only KeyValues
  const sht30Offline = values.sht30_fresh === 'false';
  const scd41Offline = values.scd41_fresh === 'false';
  const isPhysicalOffline = sht30Offline || scd41Offline;

  const isError = isSensorError(event) || isPhysicalOffline;
  const sensorFields = {
    message: isPhysicalOffline
      ? `${sht30Offline ? 'SHT30' : ''}${sht30Offline && scd41Offline ? ' + ' : ''}${scd41Offline ? 'SCD41' : ''} offline`
      : event.message,
  };
  // ... existing driveAlertType call unchanged
}
```

If the controller path is preferred instead, raise `msg.level = DiagnosticStatus.ERROR` when `not (sht30_fresh and scd41_fresh)` (and clear once both fresh again). That's a smaller diff, but it conflates "controller warming up" semantics with "a physical sensor died" — the alerter-side fix is cleaner.

### WR-02: `_publish_sensor_health` re-publish on freshness flip is suppressed during warmup, masking startup transitions

**File:** `src/chambers/fc-core/fc_core/fc_controller.py:329-347`
**Issue:**
The state-change republish at lines 343-347 lives **after** the early return in `_grace_active()` at line 334. While grace is active only the first tick publishes (`_warmup_signal_published` guard at line 331-333). If SHT30 starts up healthy mid-grace, fails, and recovers all before grace clears, none of those flips are reflected on `fc1/sensor_health` — the topic stays at the initial WARN snapshot. After grace clears (line 336-339), a single OK publish stamps current freshness; subsequent flips are then republished correctly.

In practice with `startup_grace_period=20.0` and `sensor_stale_timeout=10.0`, the window where a flip can happen during grace is small (need a sensor read to land then go stale within the same 20s). But on a degraded sensor that flaps near the timeout boundary, the first ~20s are effectively unobservable.

**Fix:** Either (a) accept the gap — it's bounded by `startup_grace_period` and the alerter wouldn't fire during warmup anyway per ALRT-05, or (b) move the freshness state-change check above the grace early-return and let it republish during grace too:

```python
def control_loop(self):
    # Phase 26 D-03: republish on freshness flip — runs every tick, regardless of grace
    sht30_fresh = self._compute_sht30_fresh()
    scd41_fresh = self._compute_scd41_fresh()
    freshness_flipped = (
        sht30_fresh != self._last_sht30_fresh
        or scd41_fresh != self._last_scd41_fresh
    )

    if self._grace_active():
        self.set_humidifier(False)
        if not self._warmup_signal_published or freshness_flipped:
            self._publish_sensor_health(warming_up=True)
            self._warmup_signal_published = True
        return
    # ... rest unchanged, drop the now-duplicated flip-check here
```

If you keep option (a), add a code comment near line 334 documenting that freshness flips during grace are intentionally suppressed and rely on the post-grace publish to catch up.

## Info

### IN-01: `_sht30_last_read_ns` / `_scd41_last_read_ns` are written but never read

**File:** `src/chambers/fc-core/fc_core/fc_sensors.py:65-66, 86, 97, 131-132`
**Issue:**
Both instance variables are populated on every successful read in both hardware and sim paths but are not read anywhere in the file (or anywhere else in the package — confirmed by the diff being scoped to two files). The downstream freshness signal travels via `frame_id` and slot-2 arrival, computed in `fc_controller`. Looks like leftover scaffolding from an earlier design.

**Fix:** Either remove them, or expose them via `get_last_read_times()` if a future phase needs them for an external introspection probe. Removal is the lower-risk option:

```python
# delete lines 65-66, 86, 97, 131-132
```

### IN-02: No test for `SCD41.data_ready == False`

**File:** `src/chambers/fc-core/fc_core/test/test_sensors.py`
**Issue:**
`test_no_stale_publish` covers `node.scd = None`, and `test_frame_id_provenance` case (c) covers SHT30 raising. Neither covers the realistic SCD41 first-tick state where the sensor is alive but `data_ready` is False — that branch (sensors.py lines 92-99) is reached on every cold boot for the first ~5s. A regression that swapped `if self.scd.data_ready` for `if not self.scd.data_ready` would slip past the suite.

**Fix:** Add a test variant of `test_slot2_publishes_scd41` with `data_ready=False`:

```python
def test_scd41_not_ready_no_publish_on_slot2(ros_context):
    node = FruitingChamberSensors()
    _force_hardware_mode(node)
    node.sht = _make_sht30_mock(23.5, 88.0)
    node.scd = _make_scd41_mock(99.0, 50.0, 500, data_ready=False)
    _patch_publishers(node)
    node.read_sensors()
    # Slot 1 still publishes from SHT30
    assert node.temp_pub.publish.called
    # Slot 2 must NOT publish — SCD41 has no fresh sample
    node.temp_2_pub.publish.assert_not_called()
    node.humidity_2_pub.publish.assert_not_called()
    node.co2_pub.publish.assert_not_called()
    node.destroy_node()
```

### IN-03: Magic constant `1e9` for ns→s conversion repeated five times

**File:** `src/chambers/fc-core/fc_core/fc_controller.py:212, 263, 278, 310, 324, 358`
**Issue:**
`(... ).nanoseconds / 1e9` appears in `_set_humidifier_with_dwell`, `_grace_active`, `_publish_sensor_health`, `_compute_sht30_fresh`, `_compute_scd41_fresh`, and `control_loop`. Pre-existing pattern, but Phase 26 added two more instances. Easy refactor to a module-level constant or a `_elapsed_seconds(self, since)` helper.

**Fix:** Optional. If touched:

```python
NS_PER_SEC = 1e9

def _elapsed_seconds(self, since):
    return (self.get_clock().now() - since).nanoseconds / NS_PER_SEC
```

### IN-04: Sim-mode dual-publish always tags `frame_id='sht30'` on slot 1

**File:** `src/chambers/fc-core/fc_core/fc_sensors.py:122, 124`
**Issue:**
In simulation mode, slot 1 is always stamped `'sht30'` and `_sht30_last_read_ns` is always refreshed (line 131). This is fine for normal sim use, but it makes it impossible to test the SCD41-fallback path end-to-end through the sim pipeline (e.g., a launch-file integration test that wants to exercise the `sht30_fresh=false, scd41_fresh=true` controller branch without spinning up real I2C). The unit tests in `test_sensors.py` already cover the fallback via `_force_hardware_mode`, so this is non-blocking — just worth a parameter (`sim_sht30_alive: bool`) if a future phase wants sim-mode integration coverage of the fallback.

**Fix:** Optional. Defer until a need arises.

---

_Reviewed: 2026-04-25T21:37:51Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
