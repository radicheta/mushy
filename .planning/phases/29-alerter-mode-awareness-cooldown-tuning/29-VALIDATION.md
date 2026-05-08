---
phase: 29
slug: alerter-mode-awareness-cooldown-tuning
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-05-08
---

# Phase 29 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Frameworks** | jest 29.x (alerter + bridge — Node), pytest 7.x (fc_core — Python/rclpy) |
| **Config files** | `src/agents/alerter/package.json` (jest), `src/mission-control/bridge/package.json` (jest), `src/chambers/fc-core/setup.cfg` (pytest) |
| **Quick run command (alerter)** | `cd src/agents/alerter && npx jest` |
| **Quick run command (bridge)** | `cd src/mission-control/bridge && npx jest` |
| **Quick run command (controller)** | `cd src/chambers/fc-core && pytest fc_core/test/test_validate_params.py -x` |
| **Full suite command** | `cd src/agents/alerter && npx jest && cd ../../mission-control/bridge && npx jest && cd ../../chambers/fc-core && pytest fc_core/test/` |
| **Estimated runtime** | ~25 seconds (alerter ~6s + bridge ~3s + pytest ~12s + buffer) |

All frameworks already installed in repo — no Wave 0 framework install required.

---

## Sampling Rate

- **After every task commit:** Run the framework-scoped quick command for the file just edited (alerter / bridge / controller).
- **After every plan wave:** Run the full suite command above.
- **Before `/gsd-verify-work`:** Full suite must be green.
- **Max feedback latency:** 25 seconds.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 29-01-01 | 01 | 0 | ALRT-08, ALRT-09 | T-29-01 / T-29-02 / T-29-03 | Bridge param-set allowlist rejects out-of-range/non-integer/unknown-mode keys before they reach rclnodejs SetParameters. | unit (jest) | `cd src/mission-control/bridge && npx jest test/control_param.test.js` | ✅ | ⬜ pending |
| 29-01-02 | 01 | 0 | ALRT-08, ALRT-09 | — | N/A — fixtures are test infrastructure, no production surface. | smoke (node -e) | `cd src/agents/alerter && node -e "..."` (inline shape probe) | ✅ creates fixtures | ⬜ pending |
| 29-02-01 | 02 | 1 | ALRT-08, ALRT-09 | T-29-04 / T-29-05 / T-29-06 / T-29-07 | Bridge JSON-in-String parse is wrapped in try/catch, malformed payloads dropped not broadcast; NaN-coercion explicit on `t_target`. | smoke (parse + grep) + jest | `node -c src/mission-control/bridge/src/index.js && cd src/mission-control/bridge && npx jest` | ✅ no new tests; smoke gate covers regressions | ⬜ pending |
| 29-03-01 | 03 | 1 | ALRT-08, ALRT-09 | T-29-08 / T-29-09 / T-29-10 / T-29-11 | rclpy `_validate_params` rejects out-of-range and malformed alerter dotted-keys atomically (Pitfall 4 batch atomicity); republish at `__init__` (Pitfall 1). | unit (pytest) | `cd src/chambers/fc-core && pytest fc_core/test/test_validate_params.py -v -k "alerter or pi_offline or sensor_offline or heartbeat_hour or max_sends or pinning_alerter_cooldown_independent or atomic_rollback or pending_republish"` | ✅ extends existing test class | ⬜ pending |
| 29-03-02 | 03 | 1 | ALRT-08, ALRT-09 | — | YAML defaults bound by validator ranges from 29-03-01. | smoke (yaml.safe_load) | `python3 -c "import yaml; ..."` (inline) | ✅ | ⬜ pending |
| 29-04-01 | 04 | 2 | ALRT-08, ALRT-09 | T-29-12 / T-29-13 / T-29-14 | resolveEffectiveConfig short-circuits to STALE/COLD on missing-mode / WS-disconnect (D-03); mode_update resets dedup but preserves lastFiredAt (D-09). | unit (jest) | `cd src/agents/alerter && npx jest test/state.test.js` | ✅ depends on 29-01-02 fixtures | ⬜ pending |
| 29-04-02 | 04 | 2 | ALRT-08, ALRT-09 | — | onMessage routes 3 new envelopes; bootstrap-only env config documented. | unit (jest) + node smoke | `cd src/agents/alerter && npx jest && node -e "const c=require('./src/config').load({}); ..."` | ✅ | ⬜ pending |
| 29-05-01 | 05 | 2 | ALRT-08, ALRT-09 | T-29-15 / T-29-16 / T-29-17 | isRhOob suspended on STALE freshness (D-03 state 2); isHumidifierStuck suppressed when wsConnected=false or humidifierLastMsgTs stale (D-04 / 999.39). | unit (jest) | `cd src/agents/alerter && npx jest test/rules.test.js` | ✅ depends on 29-01-02 fixtures | ⬜ pending |
| 29-05-02 | 05 | 2 | ALRT-08, ALRT-09 | — | formatProblem(pi) carries Last-sample summary when fields.lastKnown is provided; omits cleanly when null. | unit (jest) | `cd src/agents/alerter && npx jest test/message.test.js` | ✅ | ⬜ pending |
| 29-06-01 | 06 | 3 | ALRT-10 | T-29-18 / T-29-19 | Operator gate (human-verify checkpoint) reviews tuning recommendations before commit; range bounds (29-03) cap worst case. | manual (operator review of analysis doc) | n/a — checkpoint:human-verify | n/a — produces 29-COOLDOWN-TUNING.md | ⬜ pending |
| 29-06-02 | 06 | 3 | ALRT-10 | — | YAML still parses; pytest validator confirms tuned values within accepted ranges. | smoke (yaml.safe_load + pytest) | `python3 -c "import yaml; ..." && cd src/chambers/fc-core && pytest fc_core/test/test_validate_params.py -k alerter` | ✅ | ⬜ pending |
| 29-07-01 | 07 | 4 | ALRT-08, ALRT-09, ALRT-10 | T-29-20 / T-29-21 / T-29-22 | Live deploy verifies bridge subscriptions log + alerter consumes envelopes within 60s of bridge restart (TRANSIENT_LOCAL replay). | smoke (ssh + ros2 topic + docker logs) | `ssh pi@172.16.10.5 'ros2 topic list ...' && docker logs mushy-bridge ... && docker logs mushy-alerter ...` | n/a — live system | ⬜ pending |
| 29-07-02 | 07 | 4 | ALRT-08, ALRT-09, ALRT-10 | T-29-21 | Smoke 2 (bridge-stopped window) confirms isHumidifierStuck does NOT fire — operator-gated before band-aid revert in Smoke 3. | manual (operator-gated checkpoint) | n/a — checkpoint:human-verify | n/a — live system | ⬜ pending |
| 29-07-03 | 07 | 4 | — | T-29-22 | ROADMAP grep verifies 999.22 + 999.39 marked resolved; no other lines changed. | smoke (grep) | `grep -c "RESOLVED by Phase 29" .planning/ROADMAP.md` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Sampling continuity:** every task above has either an `<automated>` command or a checkpoint:human-verify gate. No 3-consecutive-task automated gap. Wave 0 → Wave 4 monotonically increases the test surface; once the fixtures from 29-01-02 land they unlock all Wave 2 jest commands.

---

## Wave 0 Requirements

Wave 0 (plan 29-01) creates the fixture files that unlock Wave 2 (29-04, 29-05) automated tests. No framework install required (jest + pytest already in tree).

- [ ] `src/agents/alerter/test/fixtures/effective-config.js` — exports `BASE_ENV`, `makeFreshEffective`, `makeStaleEffective`, `makeColdEffective`. Required by 29-04 state.test.js (15 tests) and 29-05 rules.test.js (9 tests).
- [ ] `src/agents/alerter/test/fixtures/bridge-messages.js` — exports `currentModeMsg`, `alerterOverridesMsg`, `alerterGlobalsMsg`. Required by 29-04 state.test.js.
- [ ] `src/mission-control/bridge/src/control_param.js` extended ALLOWLIST — required by 29-03 controller-side validator tests for mirroring range bounds.

When 29-01 ships, executor flips `wave_0_complete: true` in this frontmatter.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Mode-swap awareness on live system (mode change → alerter uses new band ≤5s later) | ALRT-08 acceptance | Requires live ROS service call + multi-process synchronization across DDS + bridge + alerter; cannot meaningfully unit-test the cross-process latency. | 29-07 Smoke 1 — operator runs `ros2 service call /fc_controller/set_mode ...` and inspects `docker logs mushy-alerter` for `[mode_update]` log line within 5 seconds. |
| Offline-blindness reproduction (bridge stopped → no false `humidifier stuck` PROBLEM in 35min window) | ALRT-09 / 999.39 acceptance | Requires real bridge container stop and real wall-clock window; jest tests cover the gate logic, but the END-TO-END pathology is observable only on the live alerter consuming live WS. | 29-07 Smoke 2 — operator runs `docker compose stop bridge`, waits stuck_min+5min, greps logs for `humidifier.*stuck` (must be empty); inspects pi_offline message body for `Last sample:` line. |
| Cooldown tuning recommendation review (does the analysis match operator intuition?) | ALRT-10 acceptance | Tuning is partly farmer-judgment; data analysis informs but does not decide. | 29-06 Task 1 checkpoint — operator reads `29-COOLDOWN-TUNING.md` and either approves or revises before commit. |
| Bandaid revert on healthy system (ALERT_SENSOR_OFFLINE_MIN=5 doesn't false-alarm) | ALRT-09 follow-through | 5-minute observation window of live healthy sensors. | 29-07 Smoke 3 — operator monitors logs for 5min after .env edit + docker compose up alerter. |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies / operator-gated checkpoints.
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (Wave 0 fixtures unlock Wave 2 jest gates).
- [x] Wave 0 covers all MISSING references (effective-config + bridge-messages fixtures).
- [x] No watch-mode flags (jest run-once; pytest -x).
- [x] Feedback latency < 30s (alerter+bridge+pytest = ~25s).
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-05-08
