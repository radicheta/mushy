---
phase: 26
slug: dual-sensor-publishing-offline-alarms-sht30-scd41-slot-topic
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-04-25
---

# Phase 26 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Sourced from RESEARCH.md §Validation Architecture and the three plans (26-01, 26-02, 26-03).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Pi-side framework** | pytest (ament_python) — `setup.py` L33 declares `tests_require=['pytest']` |
| **Pi-side config** | `src/chambers/fc-core/fc_core/test/` directory; existing files `test_camera.py`, `test_controller.py`. **No `test_sensors.py` exists yet** — Plan 01 Task 1 creates it (Wave 0 gap closed by RED-phase task). |
| **Alerter framework** | jest ^29.7.0 — `src/agents/alerter/package.json` L16 |
| **Alerter config** | `src/agents/alerter/jest.config.js`; tests in `test/` parallel to `src/` |
| **Bridge framework** | none formal; `node -c` parse check + container smoke logs |
| **Pi quick run** | `cd src/chambers/fc-core && pytest fc_core/test/test_sensors.py -x` (~5s) |
| **Alerter quick run** | `cd src/agents/alerter && npm test` (~3-5s) |
| **Bridge quick run** | `node -c src/mission-control/bridge/src/index.js` (<1s) |
| **Pi full suite** | `colcon test --packages-select fc_core` (~30s) |
| **Alerter full suite** | `cd src/agents/alerter && npm test -- --coverage` (~10s) |
| **Estimated runtime (all)** | ~45 seconds end-to-end |

---

## Sampling Rate

- **After every task commit:**
  - Pi tasks: `pytest fc_core/test/test_sensors.py -x` (or `pytest fc_core/test/ -x` for cross-cutting fc_controller changes)
  - Alerter tasks: `npm test`
  - Bridge tasks: `node -c src/mission-control/bridge/src/index.js`
- **After every plan wave:**
  - Wave 1 (26-01 only): `colcon build --packages-select fc_core --symlink-install && pytest fc_core/test/ -x`
  - Wave 2 (26-02 + 26-03 in parallel): both `npm test` (alerter) AND `node -c` (bridge); plus `docker compose config --quiet`
- **Before `/gsd-verify-work`:** Full suite green on all three modules; manual end-to-end smoke captured in `26-SMOKE-EVIDENCE.md`.
- **Max feedback latency:** 30s for any single plan; 60s for the full Wave 2 fan-out.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 26-01-01 | 01 | 1 | D-01, D-02, D-03 | T-26-01, T-26-05 | RED tests assert per-sensor failure isolation + no-stale-publish + frame_id provenance | unit (RED) | `cd src/chambers/fc-core && pytest fc_core/test/test_sensors.py -x ; test $? -ne 0` | ❌ created by this task | ⬜ pending |
| 26-01-02 | 01 | 1 | D-01, D-02, D-03 | T-26-01, T-26-02, T-26-05 | Per-sensor try/except prevents one sensor blocking the other; frame_id stamps provenance on every publish; no stale republish | unit (GREEN) | `cd src/chambers/fc-core && pytest fc_core/test/test_sensors.py -x` | ✅ (after 26-01-01) | ⬜ pending |
| 26-01-03 | 01 | 1 | D-04 enabler (sensor_health freshness) | T-26-04 | Append-only KeyValue extension; quiet-topic republish-on-flip preserves Phase 16 invariant | unit + build | `cd src/chambers/fc-core && pytest fc_core/test/ -x && colcon build --packages-select fc_core --symlink-install` | ✅ (existing test_controller.py) | ⬜ pending |
| 26-02-01 | 02 | 2 | D-02, D-03 (transport) | T-26-06, T-26-08, T-26-09 | Slot-2 subs use VOLATILE QoS (no TRANSIENT_LOCAL replay of stale values); topic strings exact-match producer | static (parse + grep) + container smoke | `node -c src/mission-control/bridge/src/index.js && grep -q "/fc1/temperature_2" src/mission-control/bridge/src/index.js && grep -q "/fc1/humidity_2" src/mission-control/bridge/src/index.js && grep -q "fc\\.temperature_2" src/mission-control/bridge/src/index.js && grep -q "fc\\.humidity_2" src/mission-control/bridge/src/index.js` | n/a (parse check) | ⬜ pending |
| 26-03-01 | 03 | 2 | D-04, D-05, D-06 | T-26-10, T-26-15 | RED tests assert per-sensor isolation, recovery, and snooze grammar boundaries | unit (RED) | `cd src/agents/alerter && npm test ; test $? -ne 0` | ✅ (extends existing test/state.test.js) | ⬜ pending |
| 26-03-02 | 03 | 2 | D-04, D-05, D-06 | T-26-10, T-26-11, T-26-12, T-26-13, T-26-14, T-26-15 | Snooze regex stays anchored `^...$`; sensor_health KeyValue parsing uses strict `=== 'true'`/`=== 'false'`; OR-gate (per RESEARCH OQ3 RESOLVED) catches Pi-side fc_controller silence; cooldown + PENDING→FIRING dedup prevents flapping | unit (GREEN) | `cd src/agents/alerter && npm test` | ✅ | ⬜ pending |
| 26-03-03 | 03 | 2 | D-04 (env plumb) | (config) | env var validated via `parseIntEnv` (throws on non-int → fail-closed boot) | static + container smoke | `grep -q "ALERT_SENSOR_OFFLINE_MIN=\\${ALERT_SENSOR_OFFLINE_MIN:-5}" docker-compose.override.yml && docker compose config --quiet` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

### Phase Requirements → Test Map (from RESEARCH.md)

| Req ID | Behavior | Test Type | Automated Command | Plan/Task |
|--------|----------|-----------|-------------------|-----------|
| D-01 | Slot 1 publishes SHT30 when SHT30 fresh | unit | `pytest fc_core/test/test_sensors.py::test_slot1_uses_sht30_when_present -x` | 26-01-01 / 26-01-02 |
| D-01 | Slot 1 falls back to SCD41 when SHT30 absent | unit | `pytest fc_core/test/test_sensors.py::test_slot1_falls_back_to_scd41 -x` | 26-01-01 / 26-01-02 |
| D-01 (provenance) | Slot 1 frame_id is 'sht30' when SHT30 backed, 'scd41' on fallback | unit | `pytest fc_core/test/test_sensors.py::test_frame_id_provenance -x` | 26-01-01 / 26-01-02 |
| D-02 | Slot 2 publishes SCD41 unconditionally when SCD41 fresh | unit | `pytest fc_core/test/test_sensors.py::test_slot2_publishes_scd41 -x` | 26-01-01 / 26-01-02 |
| D-02 | Slot 2 publishes regardless of SHT30 state | unit | `pytest fc_core/test/test_sensors.py::test_slot2_independent_of_sht30 -x` | 26-01-01 / 26-01-02 |
| D-02 (transport) | Bridge forwards slot-2 to WS + TimescaleDB | static + smoke | grep + `docker compose up -d --build bridge` | 26-02-01 |
| D-03 | No publish when underlying sensor stale | unit | `pytest fc_core/test/test_sensors.py::test_no_stale_publish -x` | 26-01-01 / 26-01-02 |
| D-04 | sht30 alert fires after 5 min silence | unit | `cd src/agents/alerter && npx jest -t "sht30 fires after sensorOfflineMin"` | 26-03-01 / 26-03-02 |
| D-04 | scd41 alert fires after 5 min silence | unit | `cd src/agents/alerter && npx jest -t "scd41 fires after sensorOfflineMin"` | 26-03-01 / 26-03-02 |
| D-04 (env) | Threshold configurable via ALERT_SENSOR_OFFLINE_MIN | static | `grep -q "ALERT_SENSOR_OFFLINE_MIN" docker-compose.override.yml` | 26-03-03 |
| D-05 | sht30 firing does not fire scd41 | unit | `cd src/agents/alerter && npx jest -t "does NOT fire scd41 when sht30 silence"` | 26-03-01 / 26-03-02 |
| D-05 | snooze sht30 mutes sht30 only | unit | `cd src/agents/alerter && npx jest -t "snooze sht30 mutes sht30 only"` | 26-03-01 / 26-03-02 |
| D-06 | Recovery message on sensor resume | unit | `cd src/agents/alerter && npx jest -t "sht30 recovery on freshness flip"` | 26-03-01 / 26-03-02 |
| D-06 | Cooldown reuses criticalCooldownMin | unit | `cd src/agents/alerter && npx jest -t "sht30 repeats after criticalCooldownMin"` | 26-03-01 / 26-03-02 |

---

## Wave 0 Requirements

- [x] `src/chambers/fc-core/fc_core/test/test_sensors.py` — created by Plan 01 Task 1 (RED phase). No separate Wave 0 needed; the RED task IS the Wave 0 work for the Pi side.
- [x] `src/agents/alerter/test/state.test.js` — already exists; Plan 03 Task 1 appends new `describe` blocks (no new file).
- [x] No new framework install — pytest and jest already present in their respective packages.
- [x] `docker-compose.override.yml` — already exists; Plan 03 Task 3 appends one env line.

*All Wave 0 gaps closed by RED-phase tasks at the start of each TDD plan.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end SHT30 unplug → Signal alert | D-04, D-05 | Requires physical hardware (pull I2C wire on fc1) and live Signal channel | (1) `ssh fc1-ts`, pull SHT30 I2C wire (or `i2cset` to bad addr). (2) Wait 5 min. (3) Expect Signal: `[PROBLEM · CRITICAL] FC-1 · SHT30 offline\nLast fresh: <Xm ago>\nOpen: ...`. (4) Reconnect SHT30. (5) Within ~30s expect: `[RECOVERY] FC-1 · SHT30 offline back\n...`. |
| End-to-end SCD41 unplug → Signal alert | D-04, D-05 | Same as above for SCD41 | (1) Cover SCD41 0x62 sensor or unplug Stemma cable. (2) Wait 5 min → Signal `SCD41 offline`. (3) Reconnect → recovery within ~30s. |
| Snooze grammar via Signal text | D-05 | Live Signal-cli round-trip | From farmer's Signal account, send `snooze sht30 4h` → trigger SHT30 silence → expect NO Signal during 4h. Trigger SCD41 silence in parallel → expect SCD41 alert fires (proves D-05 isolation). |
| `ros2 topic echo` shows frame_id | D-01 provenance, D-02 | Requires live Pi DDS graph | `ros2 topic echo /fc1/temperature -n 1` shows `header.frame_id: sht30` (or `scd41` under SHT30-down); `ros2 topic echo /fc1/temperature_2 -n 1` always shows `frame_id: scd41`. |
| Mission Control sensor_health KeyValue surface | D-04 enabler | Requires bridge WS forwarding live | `wscat -c ws://elder-plops-ts:8081 \| grep sensor_health` shows flattened `sht30_fresh` / `scd41_fresh` keys. |

All other behaviors have automated verification.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify; no MISSING references
- [x] Sampling continuity: every task in every plan has automated verify (no 3 consecutive without)
- [x] Wave 0 gaps closed by RED-phase tasks (no separate Wave 0 plan needed)
- [x] No watch-mode flags (`--watch` / `--watchAll`) in any verify command
- [x] Feedback latency < 30s per task; < 60s for Wave 2 fan-out
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** ready (all six checker items addressed in revision pass; manual hardware smoke gated to phase closeout)
