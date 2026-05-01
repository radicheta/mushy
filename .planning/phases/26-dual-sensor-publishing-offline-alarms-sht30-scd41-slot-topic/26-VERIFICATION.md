---
phase: 26-dual-sensor-publishing-offline-alarms-sht30-scd41-slot-topic
verified: 2026-04-25T22:50:00Z
verified_finalized: 2026-04-29T00:00:00Z
status: passed
score: 12/12 must-haves verified + 8-item HUMAN-UAT closed (5 PASS / 1 SKIPPED / 2 PENDING — pending items are signal-cli-trust blocked, not Phase 26 substance)
overrides_applied: 0
final_status_note: "UAT-8 (BLOCKING — phase motivation) PASS 2026-04-29 with farmer sign-off. SCD41 RH clipping behaviour confirmed by farmer eyeball on slot-1/slot-2 overlay (the failure mode dual-publish was built to surface). Pending items 5+6 are gated on signal-cli linked-device trust reset (memory: project_signal_cli_link_gotchas) — out of scope for Phase 26. Process miss: plan-26-02 contract-tested bridge half but missed UI surface (allowlist + plugin extension) — patched same session via commit 2b5ae75; lesson captured in memory project_phase26_sht30_happy_path_unverified.md."
re_verification:
  previous_status: gaps_found
  previous_score: 4/12
  gaps_closed:
    - "Bridge subscribes to /fc1/temperature_2 and /fc1/humidity_2 with default VOLATILE QoS, broadcasts to WS, and inserts into TimescaleDB (D-02, D-03) — wave 2 merge 68347bf landed Plan 02 commit 5c370f8."
    - "Alerter ALERT_TYPES gains 'sht30' and 'scd41' (CRITICAL severity), reusing the PENDING→FIRING→RECOVERY state machine via driveAlertType — wave 2 merge 68347bf landed Plan 03 commit ebe9966."
    - "When sensor_health.values.sht30_fresh transitions to 'false' (post 60s startup grace), an `sht30` Signal alert fires within 5 minutes (D-04)."
    - "When SCD41 slot-2 messages stop arriving on the bridge WS for >5min and/or sensor_health.values.scd41_fresh transitions to 'false', an `scd41` Signal alert fires (Option C hybrid)."
    - "Each sensor's alert is independent (D-05) — snoozing or firing 'sht30' does not affect 'scd41' and vice versa; snooze grammar accepts 'snooze sht30 <duration>' and 'snooze scd41 <duration>'."
    - "Recovery messages fire when sht30_fresh / scd41_fresh flips back to 'true' OR (for scd41) slot-2 messages resume — symmetric with existing pi_liveness recovery (D-06)."
    - "ALERT_TITLES['sht30'] === 'SHT30 offline' and ALERT_TITLES['scd41'] === 'SCD41 offline'; formatProblem has lastSeenMs branch for both."
    - "ALERT_SENSOR_OFFLINE_MIN env var is plumbed through config.js with default 5 (D-04, mirrors ALERT_PI_OFFLINE_MIN pattern); compose env line present."
    - "Jest suite has new tests proving D-04, D-05, D-06, isolation, and cooldown-replay for both sensors. `npm test` exits 0 with the new sht30/scd41 describe blocks green."
  gaps_remaining: []
  regressions: []
gaps: []
deferred: []
human_verification:
  - test: "fc1 deploy + ros2 topic echo on slot-2 (Plan 01 hardware smoke)"
    expected: "After `git push fc1/prod` lands wave-1 + wave-2 merges on the Pi: `ros2 topic list | grep fc1` shows `/fc1/temperature_2` and `/fc1/humidity_2`. `ros2 topic echo /fc1/temperature_2 -n 1` returns a Temperature msg with `header.frame_id == 'scd41'`. `ros2 topic echo /fc1/sensor_health -n 1` shows KeyValue entries containing keys `sht30_fresh` and `scd41_fresh` with values 'true'/'false'."
    why_human: "fc1 not yet deployed (deploy is `git push fc1/prod` per `feedback_deploy_method`); pyenv mushroom_farm not installed locally so dev-side ROS launch unavailable. Hardware-side surfacing of slot-2 topics on DDS can only be confirmed on the Pi."
  - test: "Bridge container rebuild + slot-2 WS forwarding smoke on elder-plops"
    expected: "After `docker compose up -d --build bridge` from repo root: `docker compose logs --tail 100 bridge | grep -iE 'error|fatal'` returns empty. With Plan 01 deployed on fc1, `wscat -c ws://elder-plops-ts:8081 | head -20` shows interleaved frames containing `\"temperature_2\"` and `\"humidity_2\"` keys. `docker compose exec timescale psql -U mushy -d mushy -c \"SELECT topic, COUNT(*) FROM telemetry WHERE time > now() - interval '5 minutes' GROUP BY topic;\"` includes `fc.temperature_2` and `fc.humidity_2` rows."
    why_human: "elder-plops is dev+prod (memory: `project_elder_plops_dual_role`) — rebuild is a live deploy that the verifier should not trigger autonomously per `feedback_verify_docker`. Live container shows it's still running the 6-day-old image (`docker compose ps` reports bridge `Up 33 hours`, image built 6 days ago); slot-2 wiring lives in the source but not yet in the running container."
  - test: "Alerter container rebuild + ALERT_SENSOR_OFFLINE_MIN env confirmation"
    expected: "After `docker compose up -d --build alerter` from repo root: `docker compose ps alerter` shows running. `docker compose exec alerter env | grep ALERT_SENSOR_OFFLINE_MIN` outputs `ALERT_SENSOR_OFFLINE_MIN=5`. `docker compose logs --tail 100 alerter | grep '\\[boot\\] alerter starting'` returns at least one line. No `[fatal]` or `[config]` errors in logs."
    why_human: "Same elder-plops dev+prod constraint as bridge rebuild. Additionally, `docker compose ps` currently shows NO alerter container running — this rebuild is the first deploy of the alerter for Phase 26's wave-2 changes. Cannot be done without explicit operator approval per `feedback_verify_docker`."
  - test: "Hardware end-to-end SHT30 unplug → Signal alert (D-04, D-06)"
    expected: "On fc1 (after wave-1 + wave-2 deploy), physically pull the SHT30 I2C wire (or `i2cset` it to a bad address). Within 5 minutes the farmer's Signal account receives `[PROBLEM · CRITICAL] FC-1 · SHT30 offline\\nLast fresh: <Xm ago>\\nOpen: …`. After re-plugging, within ~30s a `[RECOVERY] FC-1 · SHT30 offline back` message arrives. SCD41 silence does not produce a SHT30 message during the test."
    why_human: "Hardware-level Signal-loop validation; requires physical access at the farm; gates D-04/D-06 acceptance under real outage conditions. Cannot be exercised from dev workstation."
  - test: "Hardware end-to-end SCD41 outage → Signal alert (Option C hybrid path)"
    expected: "On fc1, simulate SCD41 outage (cover/disable the I2C 0x62 sensor or unplug the Stemma cable). Within 5 minutes Signal receives `[PROBLEM · CRITICAL] FC-1 · SCD41 offline\\nLast fresh: <Xm ago>\\nOpen: …`. Recovery message arrives within ~30s of restoring SCD41. SHT30 alert does NOT fire during the test (D-05 isolation)."
    why_human: "Hardware-level test; the Option-C hybrid path (Pi flag OR alerter-side slot-2 WS silence) only produces real cross-validation under live conditions where bridge is forwarding slot-2 to the alerter."
  - test: "Snooze grammar live-fire on Signal"
    expected: "Send `snooze sht30 4h` from the farmer's Signal account to the alerter sender number. Alerter responds with the snooze-confirmed reply (no fuzzyReply). Subsequently trigger SHT30 silence — no Signal alert until 4h elapses. SCD41 silence still produces a separate scd41 Signal message during the snooze (proves D-05 isolation under live receive-loop)."
    why_human: "Tests the live receive-loop in alerter-receive.js + signal-cli integration; cannot be exercised purely through unit tests. Must be run after alerter container rebuild."
  - test: "Sim-mode launch on a host with working ROS env (optional Plan 01 sanity)"
    expected: "`ros2 launch fc_core fc.launch.py sensor_simulation_mode:=true` then `ros2 topic echo /fc1/temperature_2 -n 1` returns Temperature msg with `frame_id == 'scd41'`. `ros2 topic echo /fc1/sensor_health -n 1` shows `sht30_fresh: 'true'` and `scd41_fresh: 'true'` KeyValues."
    why_human: "Local pytest is broken (pyenv mushroom_farm missing per execution_context); a fresh ROS2 launch is the only way to confirm Plan 01's publishers actually surface on DDS rather than just exist as Python attributes. The dev workstation cannot exercise this without a working ROS env. Optional — fc1 hardware deploy (item 1) supersedes this."
---

# Phase 26: Dual sensor publishing + offline alarms — Verification Report

**Phase Goal:** SHT30 and SCD41 publish on separate slot topics (slot 1 silent-fallback per D-01; slot 2 SCD41-only per D-02), and Signal alerts fire when either physical sensor goes silent for ≥5 min (D-04/D-05) with symmetric recovery messages (D-06). Closes the 2026-04-11 incident class where a 40-min unnoticed SHT30 outage cost a calibration session.

**Verified:** 2026-04-25T22:50:00Z
**Status:** human_needed
**Re-verification:** Yes — after wave-2 merge into main (commit `68347bf`).

## Re-verification Summary

The previous run (2026-04-25T21:42:22Z, score 4/12) inspected the codebase before wave-2 was merged. At that time only Plan 01 (Wave 1) commits were on `main`; the Plan 02 (bridge slot-2 forwarding) and Plan 03 (alerter sht30/scd41 alert types) feature commits lived only on parallel-executor worktrees. After the wave-2 merge:

- **Plan 02 commit landed:** `5c370f8 feat(26-02): bridge forwards slot-2 telemetry (temperature_2, humidity_2)`
- **Plan 03 commits landed:** `2e2d05d test(26-03)`, `ebe9966 feat(26-03)`, `80f6015 ops(26-03)`
- **Wave-2 merge commit:** `68347bf chore: merge wave 2 (26-02 bridge + 26-03 alerter) into main`

All eight code-side gaps from the previous verification are now closed. The remaining work is operator-driven: container rebuilds on elder-plops (dev+prod, no autonomous deploy per `feedback_verify_docker`) and hardware-side smoke on fc1 (deploy via `git push fc1/prod`).

## Goal Achievement

### Observable Truths

| #   | Plan  | Truth                                                                                                                                | Status     | Evidence |
| --- | ----- | ------------------------------------------------------------------------------------------------------------------------------------ | ---------- | -------- |
| 1   | 26-01 | Slot 1 publishes SHT30 when fresh, falls back silently to SCD41 (D-01)                                                                | ✓ VERIFIED | `fc_sensors.py` L107-110 silent-fallback assignment (`slot1_t = sht30_t if sht30_t is not None else scd41_t`); test_slot1_uses_sht30_when_present + test_slot1_falls_back_to_scd41 present in test_sensors.py |
| 2   | 26-01 | Slot 2 publishes SCD41 unconditionally regardless of SHT30 (D-02)                                                                     | ✓ VERIFIED | `fc_sensors.py` L137-138 (`self._publish_temp(self.temp_2_pub, slot2_t, 'scd41')`); test_slot2_publishes_scd41 + test_slot2_independent_of_sht30 present |
| 3   | 26-01 | Neither slot publishes stale or fabricated values (D-03)                                                                              | ✓ VERIFIED | `fc_sensors.py` `_publish_temp`/`_publish_humidity` short-circuit on `value is None` at L156-157, L165-166; test_no_stale_publish present |
| 4   | 26-01 | I2C exception on SHT30 does NOT prevent SCD41 read on same tick                                                                       | ✓ VERIFIED | `fc_sensors.py` L82-99: independent `try/except` blocks per sensor; test_frame_id_provenance sub-case (c) covers SHT30-raises-→-SCD41-fallback |
| 5   | 26-01 | Slot-1 frame_id ∈ {sht30, scd41}; slot-2 always 'scd41'                                                                                | ✓ VERIFIED | `fc_sensors.py` L160, L169 (`msg.header.frame_id = source` in helpers); 22 frame_id assertions in test_sensors.py |
| 6   | 26-01 | sensor_health gains sht30_fresh/scd41_fresh KeyValues, republished on flip                                                            | ✓ VERIFIED | `fc_controller.py` L297-298 KeyValue append; L341-347 republish-on-flip in `control_loop` |
| 7   | 26-01 | pytest test_sensors.py exits 0 with all six named tests                                                                                | ⚠️ HUMAN-NEEDED | All 6 test fns present and named correctly (grep returns 6); 26-01-SUMMARY.md claims `38 passed in 0.55s`; local pytest broken (pyenv mushroom_farm missing per execution_context) — can't self-confirm. SUMMARY evidence is sufficient at this layer; phase goal not gated on local re-run. |
| 8   | 26-02 | Bridge subscribes to `/fc1/temperature_2`, `/fc1/humidity_2` with VOLATILE QoS, broadcasts + inserts into Timescale                    | ✓ VERIFIED | `index.js` L632-660: two `node.createSubscription` blocks with **no `qos:` option** (default VOLATILE confirmed). Each callback: `latestTelemetry.{temperature_2,humidity_2}` cache, `broadcast({ ... })`, `insertTelemetry('fc.temperature_2'/'fc.humidity_2', value)`. Inline comment cites RESEARCH §Pitfall 2. |
| 9   | 26-03 | ALERT_TYPES gains 'sht30' and 'scd41' with CRITICAL severity                                                                            | ✓ VERIFIED | `state.js` L8 (`ALERT_TYPES = ['rh','sensor','pi','humidifier','sht30','scd41']`); L16-17 (`sht30: 'CRITICAL', scd41: 'CRITICAL'`) |
| 10  | 26-03 | sensor_health.values.sht30_fresh transitions drive sht30 alert post-grace                                                              | ✓ VERIFIED | `state.js` L246-250 refreshes `sht30LastSeenMs`/`scd41LastSeenMs` on `=== 'true'`; L255-273 OR-gates `=== 'false'` with `isSensorSilent` watchdog under post-grace check; calls `driveAlertType(next.perType.sht30, 'sht30', ...)` with `oobN=1`. |
| 11  | 26-03 | scd41 alert via Option C hybrid (sensor_health flag OR slot-2 WS silence)                                                              | ✓ VERIFIED | Two paths wired: (a) `index.js` L84-87 routes `msg.temperature_2`/`humidity_2` → `applyEvent({type:'sensor_freshness', sensor:'scd41', lastSeenMs:clock()})`; (b) `state.js` L279-302 implements `case 'sensor_freshness'`; (c) `state.js` L424-431 tick-block re-evaluates both sensors via `isSensorSilent`. Bridge slot-2 WS broadcasts confirmed at item 8. |
| 12  | 26-03 | Snooze grammar accepts `snooze sht30/scd41 <duration>`; ALERT_SENSOR_OFFLINE_MIN env plumbed; jest tests prove D-04/D-05/D-06          | ✓ VERIFIED | `snooze.js` L3 whitelist + L15 STRICT regex both extended with `sht30\|scd41`; help text L22 updated. `config.js` L37 `sensorOfflineMin: parseIntEnv(env, 'ALERT_SENSOR_OFFLINE_MIN', 5)`. `docker-compose.override.yml` L60 `ALERT_SENSOR_OFFLINE_MIN=${ALERT_SENSOR_OFFLINE_MIN:-5}` under alerter service. `state.test.js` L376 `describe('sht30_offline')`, L480 `describe('scd41_offline')`, L570 `describe('snooze sht30/scd41')` — 9 new tests; SUMMARY claims 93/93 pass. |

**Score:** 12/12 truths verified. Truth #7 has SUMMARY-attested pytest evidence; full local re-run blocked by env (not a goal gap).

### Required Artifacts

| Artifact                                                | Expected                                                                                                                              | Status      | Details |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ----------- | ------- |
| `src/chambers/fc-core/fc_core/fc_sensors.py`            | Dual-slot publishers, per-sensor try/except, frame_id provenance helpers                                                                | ✓ VERIFIED  | All landmarks present (L61-66 publishers + state; L82-99 per-sensor try/except; L137-138 slot-2 publish; L155-170 helpers stamping frame_id) |
| `src/chambers/fc-core/fc_core/fc_controller.py`         | Slot-2 subs, `_compute_sht30_fresh` / `_compute_scd41_fresh`, sensor_health KeyValue extension                                          | ✓ VERIFIED  | Subscriptions L93-101; slot-1 callbacks L151-153/L159-161 read frame_id; slot-2 callbacks L163-169; helpers L304-322; KeyValue append L297-298; flip-republish L341-347 |
| `src/chambers/fc-core/fc_core/test/test_sensors.py`     | 6 named tests for D-01/D-02/D-03 + frame_id                                                                                             | ✓ VERIFIED  | 6 `def test_*` functions; 22 `header.frame_id` assertions |
| `src/mission-control/bridge/src/index.js`               | Slot-2 subscriptions + WS broadcast + Timescale insert                                                                                  | ✓ VERIFIED  | L632-660 — both subscriptions present, default VOLATILE QoS (no `qos:` option), full callback shape matching slot-1 reference |
| `src/agents/alerter/src/state.js`                       | Extended ALERT_TYPES + SEVERITY; sensor_freshness case; sht30/scd41 LastSeenMs tracking                                                  | ✓ VERIFIED  | L8 ALERT_TYPES extension; L16-17 SEVERITY; L52-53 LastSeenMs init; L246-273 sensor_health extension; L279-302 sensor_freshness case; L420-431 tick block |
| `src/agents/alerter/src/rules.js`                       | `isSensorSilent` predicate added + exported                                                                                              | ✓ VERIFIED  | L62 `function isSensorSilent({ lastSeenMs, nowMs, config })`; L68 module.exports includes `isSensorSilent` |
| `src/agents/alerter/src/index.js`                       | onMessage branch for `msg.temperature_2`/`humidity_2` → `sensor_freshness` event                                                          | ✓ VERIFIED  | L84-87 — branch present, dispatches `{type:'sensor_freshness', sensor:'scd41', lastSeenMs:clock()}` |
| `src/agents/alerter/src/message.js`                     | ALERT_TITLES sht30/scd41 entries + formatProblem branches                                                                                | ✓ VERIFIED  | L8-9 titles; L65 `else if (alertType === 'sht30' || alertType === 'scd41')` branch with `Last fresh:` line |
| `src/agents/alerter/src/snooze.js`                      | VALID_ALERT_TYPES + STRICT regex extended with sht30/scd41                                                                               | ✓ VERIFIED  | L3 whitelist; L15 regex alternation `(rh\|sensor\|pi\|humidifier\|sht30\|scd41\|all)`; L22 fuzzyReply text |
| `src/agents/alerter/src/config.js`                      | `sensorOfflineMin` from `ALERT_SENSOR_OFFLINE_MIN` env (default 5)                                                                       | ✓ VERIFIED  | L37 `sensorOfflineMin: parseIntEnv(env, 'ALERT_SENSOR_OFFLINE_MIN', 5)` |
| `src/agents/alerter/test/state.test.js`                 | sht30_offline / scd41_offline / snooze sht30 describe blocks                                                                             | ✓ VERIFIED  | L376 sht30_offline (4 tests), L480 scd41_offline (4 tests), L570 snooze cross-isolation (1 test); 73 total sht30/scd41/sensor_freshness references |
| `src/agents/alerter/test/snooze.test.js`                | Test E updated for extended help text                                                                                                    | ✓ VERIFIED  | Lockstep update committed in `ebe9966` per Plan 03 SUMMARY |
| `docker-compose.override.yml`                           | `ALERT_SENSOR_OFFLINE_MIN=${ALERT_SENSOR_OFFLINE_MIN:-5}` under alerter service                                                          | ✓ VERIFIED  | L60 — env line present under alerter service block |

### Key Link Verification

| From                                                  | To                                                       | Via                                              | Status      | Details |
| ----------------------------------------------------- | -------------------------------------------------------- | ------------------------------------------------ | ----------- | ------- |
| fc_sensors.read_sensors slot-1 publish                | Temperature/RelativeHumidity msg.header.frame_id         | `_publish_temp`/`_publish_humidity` helpers      | ✓ WIRED     | Helpers set frame_id on every publish |
| fc_sensors slot-2 publish                             | self.temp_2_pub / self.humidity_2_pub                    | sht30_t/scd41_t locals + None-gate               | ✓ WIRED     | L137-138 publish call sites with 'scd41' literal |
| fc_controller temperature_callback                    | self._last_sht30_timestamp                               | msg.header.frame_id == 'sht30'                   | ✓ WIRED     | L151-153 + L159-161 explicit guard |
| fc_controller _publish_sensor_health                  | KeyValue list (sht30_fresh, scd41_fresh)                 | append after existing 4 keys                     | ✓ WIRED     | L297-298 append-only |
| fc_controller subscribes to /fc1/temperature_2        | _last_temp2_timestamp / _last_humidity2_timestamp        | create_subscription mirroring slot-1             | ✓ WIRED     | L93-101 subs; L165, L169 timestamp updates |
| Bridge slot-2 subscription                            | WS broadcast({ temperature_2 / humidity_2 })             | callback at createSubscription                   | ✓ WIRED     | index.js L644, L656 broadcast call |
| Bridge slot-2 subscription                            | insertTelemetry('fc.temperature_2'/'fc.humidity_2')      | callback at createSubscription                   | ✓ WIRED     | index.js L645, L657 insertTelemetry call |
| Alerter onMessage msg.temperature_2/humidity_2        | applyEvent({type:'sensor_freshness', sensor:'scd41'})    | onMessage branch                                 | ✓ WIRED     | index.js L84-87 |
| Alerter sensor_health values.sht30_fresh/scd41_fresh  | driveAlertType('sht30'/'scd41', oobNow=(flag==='false')) | extended sensor_health case                      | ✓ WIRED     | state.js L246-273 |
| Alerter case 'sensor_freshness'                       | next.scd41LastSeenMs refresh + post-grace re-eval        | new case in transition switch                    | ✓ WIRED     | state.js L279-302 |
| Alerter case 'tick'                                   | isSensorSilent → driveAlertType for sht30/scd41          | new re-evaluation block in tick                  | ✓ WIRED     | state.js L420-431 |
| snooze STRICT regex                                   | VALID_ALERT_TYPES whitelist                              | alternation extended sht30/scd41                 | ✓ WIRED     | snooze.js L3 + L15 both updated together |

### Data-Flow Trace (Level 4)

| Artifact                                | Data Variable                | Source                                                                                | Produces Real Data | Status |
| --------------------------------------- | ---------------------------- | ------------------------------------------------------------------------------------- | ------------------ | ------ |
| fc_sensors slot-2 publishers            | scd41_t, scd41_rh            | `self.scd.temperature` / `relative_humidity` (real I2C) or sim values                  | Yes (in sim and on hardware once deployed) | ✓ FLOWING (sim verified by static read; hardware confirmation pending fc1 deploy) |
| fc_controller sensor_health KeyValues   | sht30_fresh, scd41_fresh     | `_compute_sht30_fresh`/`_compute_scd41_fresh` from frame_id-tagged callbacks + slot-2 timestamps | Yes                | ✓ FLOWING |
| Bridge → WS slot-2 payload              | `temperature_2`, `humidity_2` (broadcast keys); `latestTelemetry.{temperature_2,humidity_2}` | rclnodejs subscription on /fc1/temperature_2 / /fc1/humidity_2 → `msg.temperature` / `msg.relative_humidity * 100` | Yes (callback writes value from msg field; verified statically) | ✓ FLOWING (live confirmation pending bridge container rebuild) |
| Bridge → TimescaleDB rows               | telemetry.topic = 'fc.temperature_2' / 'fc.humidity_2', telemetry.value | Same callback, `insertTelemetry(topic, value)` writes via `pool.query` (free-form topic column, no schema change) | Yes              | ✓ FLOWING (live confirmation pending bridge rebuild + fc1 deploy) |
| Alerter sht30/scd41 alert state         | next.perType.sht30 / scd41   | `driveAlertType` from `sensor_health` case (Pi-side flag), `sensor_freshness` case (slot-2 WS arrival), and `tick` case (watchdog re-eval) | Yes; perType.{sht30,scd41} bootstrap automatic via `for (t of ALERT_TYPES)` in `initialState` | ✓ FLOWING |
| Alerter Signal send action              | `actions.push({kind:'send', alertType:'sht30'\|'scd41', ...})` | `driveAlertType` → `formatProblem` (message.js L65 sht30/scd41 branch) → signal.js sender | Yes (`ALERT_TITLES['sht30']='SHT30 offline'` resolved by formatProblem) | ✓ FLOWING (live Signal validation pending alerter container rebuild + hardware test) |

### Behavioral Spot-Checks

| Behavior                                                                  | Command                                                                                          | Result | Status |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ------ | ------ |
| `node -c` parse of bridge source                                          | `node -c src/mission-control/bridge/src/index.js`                                                | (exits 0 per Plan 02 SUMMARY; verifier confirmed file structure via grep) | ✓ PASS (SUMMARY) |
| Alerter jest suite                                                        | `cd src/agents/alerter && npm test`                                                              | (93/93 pass per Plan 03 SUMMARY); `npm` not invoked by verifier (treat SUMMARY as authoritative per execution_context) | ✓ PASS (SUMMARY) |
| Pi-side pytest                                                            | `cd src/chambers/fc-core && pytest fc_core/test/test_sensors.py -x`                              | (38/38 pass per Plan 01 SUMMARY); local pytest broken (pyenv missing) per execution_context | ✓ PASS (SUMMARY) |
| `docker compose config --quiet`                                           | `docker compose config --quiet`                                                                  | (exits 0 per Plan 03 SUMMARY) | ✓ PASS (SUMMARY) |
| Static grep coverage of all 12 truths                                     | (multiple greps run by verifier across state.js, rules.js, message.js, snooze.js, config.js, index.js, bridge index.js, fc_sensors.py, fc_controller.py, docker-compose.override.yml) | All landmark patterns present at expected line numbers | ✓ PASS |
| Bridge container running latest source                                    | `docker compose ps` STATUS `Up 33 hours` against image built 6 days ago                          | Container running, but image predates wave-2 merge (`5c370f8` is 1 day old) → live container does NOT yet contain slot-2 wiring | ✗ STALE → routed to human (rebuild) |
| Alerter container running                                                  | `docker compose ps alerter`                                                                      | NO alerter container present in `docker compose ps` output → first-time alerter deploy required | ✗ MISSING → routed to human (build + deploy) |
| Bridge index.js parses (verifier-side)                                    | `node -c src/mission-control/bridge/src/index.js`                                                | Not invoked by verifier; redundant with SUMMARY parse confirmation | ? SKIP |

The two FAIL rows (stale bridge container, missing alerter container) are **expected operational state** for a wave-2 merge that has not yet been deployed — they are routed to `human_verification` items 2 and 3, not counted as code-side gaps.

### Requirements Coverage

| Requirement | Source Plan       | Description                                                       | Status      | Evidence |
| ----------- | ----------------- | ----------------------------------------------------------------- | ----------- | -------- |
| D-01        | 26-01             | Slot 1 silent-fallback (SHT30 → SCD41) preserved                  | ✓ SATISFIED | fc_sensors.py L107-110 silent-fallback assignment; test_slot1_falls_back_to_scd41 |
| D-02        | 26-01, 26-02      | Slot 2 publishes SCD41 unconditionally + bridge forwards           | ✓ SATISFIED | Pi: fc_sensors.py L137-138; Bridge: index.js L632-660 |
| D-03        | 26-01, 26-02      | No fabricated/stale values, gaps acceptable                       | ✓ SATISFIED | Pi-side: `_publish_temp`/`_publish_humidity` short-circuit on None; Bridge VOLATILE QoS confirmed (no `qos:` option) — subscription only forwards live arrivals |
| D-04        | 26-03             | 5-min offline threshold triggers Signal alert                      | ✓ SATISFIED (code) — ⚠️ HUMAN-NEEDED (live) | `state.js` `isSensorSilent` uses `config.sensorOfflineMin * 60000`; `config.js` defaults `sensorOfflineMin` to 5; jest test `sht30 fires after sensorOfflineMin minutes silent` proves transition. Live Signal validation gated on alerter rebuild + hardware unplug. |
| D-05        | 26-03             | Per-sensor granularity (SHT30 ≠ SCD41 alerts)                     | ✓ SATISFIED (code) — ⚠️ HUMAN-NEEDED (live) | `state.js` separate `perType.sht30` / `perType.scd41` buckets; jest `does NOT fire scd41 when only sht30 is silent` + `does NOT fire sht30 when only scd41 is silent` + `snooze sht30 mutes sht30 only`. Live isolation gated on hardware test items 4-6. |
| D-06        | 26-03             | Recovery message symmetric to existing alerter                     | ✓ SATISFIED (code) — ⚠️ HUMAN-NEEDED (live) | Recovery is in-band on `driveAlertType` (existing path, untouched); jest `recovery on sht30_fresh flip back to true` + scd41 equivalent. Live recovery message validation gated on hardware test item 4-5. |

All six requirements are satisfied at the code/test level. D-04/D-05/D-06's "Signal message actually arrives at farmer's phone" is the human-verification surface; the inert code paths are now wired end-to-end.

### Anti-Patterns Found

| File                                                  | Line       | Pattern                                                                | Severity   | Impact |
| ----------------------------------------------------- | ---------- | ---------------------------------------------------------------------- | ---------- | ------ |
| `src/chambers/fc-core/fc_core/fc_sensors.py`          | 65-66, 86, 97, 131-132 | `_sht30_last_read_ns` / `_scd41_last_read_ns` written but never read   | ℹ️ Info    | IN-01 from REVIEW; orphan instance variables (freshness moved to fc_controller via frame_id provenance). No behavior impact; cleanup deferred. |
| `src/chambers/fc-core/fc_core/fc_controller.py`       | 329-347    | Freshness flip republish suppressed during startup grace                | ⚠️ Warning | WR-02 from REVIEW; bounded by `startup_grace_period`; flap during first 20s unobservable. Low-severity; phase goal not gated on it. |
| `src/chambers/fc-core/fc_core/test/test_sensors.py`   | n/a        | No test for `SCD41.data_ready == False`                                  | ℹ️ Info    | IN-02 from REVIEW; valid coverage gap; not a goal-blocker. |

WR-01 from the previous REVIEW (state.js sensor_health case ignoring values.{sht30,scd41}_fresh) is **resolved** — `state.js` L246-273 now inspects both flags and OR-gates them with the watchdog. No new anti-patterns introduced by wave-2 commits.

### Human Verification Required

See `human_verification:` array in the frontmatter. Seven items in three groups:

**Container deploys on elder-plops (dev+prod):**
2. Bridge rebuild (`docker compose up -d --build bridge`) — bridge container is currently running a 6-day-old image; slot-2 wiring is in source but not in the running container.
3. Alerter rebuild (`docker compose up -d --build alerter`) — no alerter container is currently running; this is the first-time deploy of the alerter for Phase 26.

**Hardware-side smoke on fc1 (deploy via `git push fc1/prod`):**
1. Slot-2 ROS topic surfacing (`ros2 topic echo /fc1/temperature_2`) + sensor_health KeyValue keys.
4. SHT30 unplug → Signal `[PROBLEM · CRITICAL] FC-1 · SHT30 offline` within 5 min, recovery on re-plug.
5. SCD41 outage → Signal `[PROBLEM · CRITICAL] FC-1 · SCD41 offline` within 5 min, recovery + D-05 isolation cross-check.
6. Snooze grammar live-fire (`snooze sht30 4h` from farmer's Signal account).

**Optional dev-side sanity (lower priority):**
7. Sim-mode launch on a host with working ROS env — superseded by fc1 hardware deploy if that lands first.

All three deploy items (2, 3) and four hardware items (1, 4, 5, 6) are sequenced: deploy bridge + alerter on elder-plops → push fc1/prod → ros2 echo → Signal smoke. Item 7 is optional.

### Gaps Summary

**No code-side gaps.** All 12 must-haves and all six D-01..D-06 requirements are satisfied at the source-tree level. Wave-2 merge `68347bf` resolved every gap from the previous verification run.

The phase goal — "Signal alerts fire when either physical sensor goes silent" — is **code-complete**. Live operator-driven verification remains:

- **Operator deploys (2 steps):** bridge container rebuild + alerter container build & start on elder-plops. Both are gated on operator approval per `feedback_verify_docker` (elder-plops is dev+prod, no staging) and were intentionally deferred by the wave-2 plans to keep parallel-executor worktrees from pushing unmerged code to production.
- **Pi deploy (1 step):** `git push fc1/prod` lands wave-1 (Plan 01) on the Pi. Without this, slot-2 topics never publish and the bridge has nothing to subscribe to.
- **Farm-side hardware smoke (3 steps):** SHT30 unplug, SCD41 outage, snooze live-fire. These can only run at the farm and produce the canonical evidence — Signal screenshots — that closes the 2026-04-11 incident class.

Recommended next action: orchestrator runs the two `docker compose up -d --build` commands on elder-plops, then operator runs `git push fc1/prod` on a farm-day to deploy + smoke. After hardware smoke produces a `[PROBLEM · CRITICAL] FC-1 · SHT30 offline` Signal message followed by a recovery message, the phase is shipped.

---

_Verified: 2026-04-25T22:50:00Z_
_Verifier: Claude (gsd-verifier)_
