# Phase 31 — Verification

**Phase:** 31 — Experimental forcing modes (force-condensation, force-evaporation)
**Status:** human_needed (code complete; live deploy + farmer attestation pending)
**Commit range:** `f4178cf` → `a8726f4` (4 commits, all on `main`)

## Plan-by-plan status

| Plan | Wave | Code | Tests on elder-plops | Deploy/UAT |
|------|------|------|----------------------|------------|
| 31-01 (srv defs + force-mode config) | 1 | DONE | 10/10 pytest PASS (pure YAML) | colcon build deferred to fc1 |
| 31-02 (controller wiring) | 2 | DONE | rclpy unavailable on elder-plops; ast.parse clean | full pytest + smoke deferred to fc1 |
| 31-03 (bridge endpoints + DB + subscriber) | 2 | DONE | 48/48 jest PASS (full bridge suite 234/236; 2 pre-existing burn_bar/jimp failures unrelated) | docker rebuild + curl smoke deferred |
| 31-04 (Signal parser + receive-loop dispatch + deploy verify) | 3 | DONE | 26/26 jest PASS (full alerter suite 212/213; 1 pre-existing config env-leak unrelated) | UAT scenarios 1-6 deferred |

## What was code-verified

- 10 pytest tests in `test_force_modes_config.py` — pure-YAML config sanity locks force-mode invariants (force_duty values, wide-open bands, defend_side, t_target NaN, baseline-modes-no-force_duty).
- 48 jest tests in `control_experiment.test.js` + `experiment_event_subscriber.test.js` — HTTP validate/handlers, DB migration idempotency, INSERT/UPDATE flow, NULL-safe delta_rh, defensive paths.
- 26 jest tests in `experiment_commands.test.js` — Signal grammar (case, whitespace, range, passthrough) + receive-loop dispatch (start/cancel/4xx/network-error/help-reply/snooze-isolation).
- Static greps satisfied across fc_controller.py, control_experiment.js, receive-loop.js (counts in respective SUMMARY.md files).
- `node --check` on bridge index.js + `python3 -m ast` on fc_controller.py — syntax clean.
- `scripts/pi-deploy/deploy.sh` confirmed to already build `fc_msgs fc_core` — no edit needed.

## What requires human checkpoint (BLOCKING for phase close)

### Live deploy
1. fc1: `git pull origin fc1/prod && colcon build --packages-select fc_msgs fc_core && sudo systemctl restart fc-core` — picks up new srv defs + controller wiring.
2. elder-plops: `docker-compose up -d --build bridge` — picks up new control_experiment.js + index.js wiring + fc_experiments DB migration.
3. alerter: rebuild (likely included in bridge rebuild or separate `docker-compose up -d --build alerter` depending on stack layout).

### UAT (per Plan 31-04 §Task 3)
1. **Happy path (`/force-condensation 1`)** → Signal ack + 60s auto-revert + DB row with `end_reason='timeout'`.
2. **Hard cap (`/force-condensation 200`)** → Signal help reply, no DB row.
3. **Lockout (rapid `/force-condensation` × 2)** → second reply contains `experiment_in_progress`.
4. **Cancel (`/force-evaporation 30` + `/cancel-experiment` after 10s)** → row has `end_reason='cancelled'`, actual_min ≈ 0.17.
5. **Boot recovery (D-09, LOAD-BEARING):** start experiment, wait 5s, restart fc-core. Verify (a) active_mode='fruiting' on restart, (b) WARN log "BOOT-RECOVERY", (c) experiment_event 'truncated', (d) row closed with `end_reason='truncated_by_restart'`.
6. **Phase 30 interaction (D-08):** with schedule active and clock straddling a boundary, verify scheduler suppression during experiment + re-alignment after revert.

Scenario 5 is the load-bearing attestation per CONTEXT D-09. Plan 31-02 Task 6 unit tests provide the in-code regression guard, but live attestation is required before phase close.

## Threats / Pre-existing issues observed

- **Pre-existing burn_bar test failures** (2/236) on bridge — `node_modules/@jimp/core/src/index.ts` library issue, not Phase 31 related. Verified via `git stash` baseline run.
- **Pre-existing config.test.js Test A failure** on alerter — `DASHBOARD_URL`-style env var leakage. Confirmed pre-existing via `git stash` baseline.

Neither is a Phase 31 regression.

## Routing decision

`status: human_needed` — orchestrator should route to operator for fc1 deploy + UAT scenarios. No autonomous fc1 action attempted (per phase posture established in Phase 30; CONTEXT D-09 boot-recovery attestation requires controlled restart with operator preflight).
