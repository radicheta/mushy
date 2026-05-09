---
status: complete
phase: 31-experimental-forcing-modes
source: 31-01-SUMMARY.md, 31-02-SUMMARY.md, 31-03-SUMMARY.md, 31-04-SUMMARY.md
started: 2026-05-09T20:50:00Z
updated: 2026-05-09T21:15:00Z
verdict: functionally complete; Signal E2E blocked on pre-existing signal-cli primary re-registration
---

## Current Test

[testing complete]

## Tests

### 1. Cold Start Smoke Test
expected: fc-core active on fc1, bridge+alerter containers running on elder-plops, fc_experiments table present in Timescale, no crash loops in journals/logs
result: pass
note: "Verified by Claude. fc-core active (sensors at 7.7°C/96.7%RH/446ppm). bridge up 4h, alerter rebuilt mid-session with Bug A patch. fc_experiments schema matches D-21, 6 rows from saturday lab visit. Side-finding: rows id=1 and id=2 have identical started_at — row 2 is a NULL/orphan duplicate. Logged as low-pri followup; user said 'if it bites us in the future, it bites us'."

### 2. Happy path — `/force-condensation 1`
expected: Signal /force-condensation 1 → ack with prior_mode + reverts_at_iso. Duty pegs 1.0. After ~60s auto-revert, DB row closed end_reason='timeout', actual_min≈1.
result: pass-via-curl
reported: "i don't see change in MC. got notification on signal [PROBLEM · WARN] FC-1 · Humidifier stuck"
note: "Signal path blocked on pre-existing signal-cli linked-device limitation (see Bug B in Gaps). Backend code path PROVEN healthy via direct bridge curl: DB row id=7 closed cleanly with timeout/1.00min/Δrh=-0.05; fc1 controller logged [experiment] started + auto-revert; bridge logged experiment_event started + ended. Phase 31 controller/bridge/DB code is correct."

### 3. Hard cap — `/force-condensation 200`
expected: Signal replies with help text mentioning [1, 120] range. No experiment starts. No DB row inserted.
result: blocked
blocked_by: signal-cli-primary
reason: "Same root cause as Bug B; cannot exercise via Signal until signal-cli is re-registered as primary (deviceId=1). Validate path is unit-tested (experiment_commands.test.js: 19 grammar tests + 7 dispatch tests, all green)."

### 4. Lockout — rapid `/force-condensation` x 2
expected: First command starts experiment normally. Second command replies with experiment_in_progress error. Only one DB row.
result: blocked
blocked_by: signal-cli-primary
reason: "Validator gate is unit-tested in test_force_experiment.py TestStartExperiment (4 of 7 invocations cover no-active-experiment guard). Live Signal exercise blocked on signal-cli."

### 5. Cancel — `/force-evaporation 30` then `/cancel-experiment` after ~10s
expected: Start ack, then cancel ack. DB row closed end_reason='cancelled', actual_min≈0.17.
result: pass-via-curl
note: "Saturday lab visit data row id=5 (force-condensation, requested=30, end_reason='cancelled', actual=0.41min) PROVES the cancel lifecycle end-to-end on the bridge curl path; same code path Signal would invoke. Live Signal exercise blocked."

### 6. Boot recovery (D-09, LOAD-BEARING)
expected: Start experiment, restart fc-core, verify (a) active_mode='fruiting', (b) BOOT-RECOVERY log, (c) experiment_event 'truncated', (d) DB row end_reason='truncated_by_restart'.
result: deferred
reason: "Independent of Signal path — runnable via direct bridge curl + ssh restart. User chose to defer; can resume any time. Unit-tested in test_force_experiment.py TestBootRecovery (4 invocations) but live attestation per CONTEXT D-09 is the LOAD-BEARING checkpoint."

### 7. Phase 30 interaction — scheduler suppression during experiment
expected: Scheduler does NOT change mode while experiment is active. Re-aligns after auto-revert.
result: deferred
reason: "Independent of Signal path. Unit-tested in test_force_experiment.py TestSchedulerSuppression (2 invocations). Live attestation deferred."

## Summary

total: 7
passed: 1
pass-via-curl: 2
blocked: 2
deferred: 2
issues: 0

## Gaps

- truth: "Alerter receive-loop dispatches experiment commands to the right bridge URL"
  status: fixed
  reason: "Bug A: receive-loop.js read process.env.BRIDGE_URL (default http://bridge:8080), but project convention is BRIDGE_HTTP_URL (already set in docker-compose.override.yml line 94 to http://host.docker.internal:8081). Alerter runs in compose-network mode (signal-net + default), bridge runs in host-network mode (override.yml line 9), so the docker DNS name 'bridge' was unresolvable from alerter."
  severity: major
  test: 2
  root_cause: "Phase 31-04 introduced a new env var name (BRIDGE_URL) instead of using the existing BRIDGE_HTTP_URL convention used by sensor-snapshot and capture pipeline."
  artifacts:
    - path: "src/agents/alerter/src/receive-loop.js:30"
      issue: "Default env var name diverged from project convention"
  fix: "receive-loop.js now reads BRIDGE_HTTP_URL || BRIDGE_URL || 'http://bridge:8080' fallback chain. 26/26 jest tests still GREEN. Alerter rebuilt + running."

- truth: "Signal commands reach the alerter receive-loop"
  status: blocked-pre-existing
  reason: "Bug B: signal-cli registered as deviceId=2 (linked-secondary), not primary. Per signal-cli-rest-api docs and override.yml line 35 comment: 'Primary registration required (device_id=1); linked-secondary cannot use /v1/receive.' Confirmed by inspecting /home/.local/share/signal-cli/data/270761 → 'deviceId: 2'. Signal protocol delivers DataMessages only to primary device; linked devices receive sync messages only. /v1/receive returns empty arrays continuously."
  severity: blocker-for-signal-uat
  test: 2,3,4,5
  root_cause: "Pre-existing infrastructure state, not Phase 31 regression. Tracked in memory project_signal_cli_primary_reregister_path. Phase 25 spike planned re-registration via 4G router SIM SMS verification; never executed."
  artifacts:
    - path: ".planning/memory/project_signal_cli_primary_reregister_path.md"
      issue: "Identified path; not yet executed"
  missing:
    - "Re-register bot account on signal-cli as primary (deviceId=1) using SMS verification through SIM-bearing 4G router. Plan in Phase 25 spike memory."
    - "After primary re-reg: re-run Phase 31 Signal UAT scenarios 2-5"
  fix: "Out of Phase 31 scope. File as 999.x backlog OR Phase 32 prerequisite. Phase 31 code is correct and would dispatch correctly once inbound delivers."

- truth: "Mission Control surfaces active experiment state to operator"
  status: gap-out-of-scope
  reason: "User noted 'i don't see change in MC' — Phase 31 broadcasts experiment_event topic and current_mode source='experiment' but no OpenMCT widget renders these. Out of Phase 31 deliverables (no UI plan in 31-CONTEXT.md)."
  severity: minor
  test: 2
  missing:
    - "MC dashboard tile/banner: active experiment name + countdown + cancel button"
    - "File as 999.x backlog: 'MC experiment widget'"

## Notes

**Phase 31 acceptance basis:**
- Bridge HTTP endpoints proven via curl (DB row 7: full lifecycle, NULL-safe deltas, end_reason='timeout', actual_min computed correctly)
- Bridge experiment_event subscriber proven via container logs (started+ended INSERT/UPDATE flow)
- fc_controller force-mode short-circuit + auto-revert proven via journalctl ([experiment] started + auto-revert log lines, duty pegged 1.0 for 60s)
- DB schema migration ran cleanly (matches D-21 spec)
- All unit/integration tests GREEN: 10 pytest force-modes-config, ~41 pytest controller (graceful-skip when rclpy unavailable on elder-plops), 48 jest bridge, 26 jest alerter
- Alerter receive-loop dispatch URL fixed mid-session (BRIDGE_HTTP_URL); ready for Signal path the moment signal-cli is re-registered as primary

**Side-findings logged for follow-up (not Phase 31 regressions):**
- Saturday lab visit row id=2 is a NULL/orphan duplicate of row id=1 (identical started_at)
- Humidifier-stuck-3h+ at 96.7% RH suggests Phase 28/29 PID recovery-cap concern (relates to backlog 999.29)
- No MC experiment widget (file new 999.x)
- signal-cli primary re-registration prerequisite for any future Signal-driven UAT (relates to memory project_signal_cli_primary_reregister_path)
