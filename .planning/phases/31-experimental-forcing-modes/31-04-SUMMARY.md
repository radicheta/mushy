# Plan 31-04 Summary — Signal command parser + receive-loop dispatch + deploy verification

**Status:** code complete, jest 26/26 PASS for new tests, full alerter suite 212 pass / 1 pre-existing failure (config.test.js Test A, unrelated env-leak issue). UAT scenarios 1-6 deferred to live fc1 deploy + farmer attestation.

## What was built

### `src/agents/alerter/src/experiment_commands.js` (NEW)

- `parseExperimentCommand(text)` — strict slash-prefixed grammar:
  - `/force-condensation [N]` and `/force-evaporation [N]` — N integer in [1, 120], defaults to 15.
  - `/cancel-experiment` — no args; trailing args rejected for clarity.
  - Case-insensitive command prefix; canonical name returned lowercase.
  - Whitespace tolerant; non-string input rejected as passthrough.
- Returns `{ok:true, kind:'start', name, duration_minutes}` | `{ok:true, kind:'cancel'}` | `{ok:false, reply:string}` (malformed) | `{ok:false, reply:null}` (passthrough).
- Out-of-range N replies with multi-line help text mentioning the `[1, 120]` range.

### `src/agents/alerter/src/receive-loop.js`

- New factory params: `bridgeUrl` (default `process.env.BRIDGE_URL || 'http://bridge:8080'`) and `fetchImpl` (default `globalThis.fetch`, test seam).
- `dispatchExperiment(exp)` helper inside `createReceiveLoop`:
  - `kind:'start'` → POST `/control/experiment` with `{name, duration_minutes}`. On 200/ok: ack with `<name> started for <N> min; reverts at <iso> (prior=<mode>)`. On 4xx: ack with bridge's error message. On network throw: ack with generic 'experiment dispatch failed; check bridge logs'.
  - `kind:'cancel'` → POST `/control/cancel-experiment` empty body. Same response pattern with `cancelled (ended_at=...)` ack.
  - All paths swallow exceptions internally — receive-loop tick never dies on a single dispatch failure (Pitfall 4 preserved).
- Experiment-command branch inserted IMMEDIATELY AFTER the whitelist gate and BEFORE the snooze fast-path (D-15). `continue`s out of the per-envelope loop on both ok-paths and reply-paths.

### `src/agents/alerter/test/experiment_commands.test.js` (NEW)

- 19 grammar tests covering: defaults, both names, lower/upper bounds, out-of-range (0, 121, negative, non-integer, garbage), `/cancel-experiment` happy + trailing-args, case-insensitive prefix, passthrough variants (no slash, snooze prefix, freeform, unknown `/force-` variant), whitespace trim, exports validation.
- 7 receive-loop dispatch tests covering: start+ack, cancel+ack, 4xx propagation, network-error fallback ack, invalid-command help reply (no POST), `/force-*` does NOT trigger snooze dispatch, freeform passthrough preserved.

### `scripts/pi-deploy/deploy.sh`

**No changes needed.** Verified: deploy.sh runs `colcon build --packages-select fc_msgs fc_core` — both packages are explicitly named, so the two new srv definitions in fc_msgs and the controller-side wiring in fc_core are picked up automatically.

## Verification

- `cd src/agents/alerter && npx jest test/experiment_commands.test.js`: **26/26 PASS**.
- `npx jest` (full suite): 212 PASS, 1 pre-existing fail (`config.test.js Test A` — DASHBOARD_URL env leak, exists on baseline pre-Phase-31 commit, NOT a regression).
- Static greps satisfied: `parseExperimentCommand` in receive-loop 2, `/control/experiment` 1, `/control/cancel-experiment` 1, `dispatchExperiment` 2.
- `node --check src/agents/alerter/src/receive-loop.js` (implicit via jest run) — clean.

## Deferred — Task 3 UAT scenarios (BLOCKING HUMAN CHECKPOINT)

Per phase posture (no autonomous fc1 remote action), live UAT and farmer attestation are deferred. The 6 UAT scenarios require:
1. fc1 reboot/restart authority (preflight checklist per memory `feedback_fc1_remote_action_preflight_protocol`).
2. Live Signal channel access (farmer is the operator).
3. Bridge image rebuild on elder-plops + DB inspection.

UAT scenarios to run on next live session:

1. **Happy path (`/force-condensation 1`):** Signal → ack → 60s auto-revert → `fc_experiments` row populated end-to-end (`end_reason='timeout'`, `actual_min ≈ 1.0`, baseline_rh + final_rh + delta_rh non-null).
2. **Hard cap (`/force-condensation 200`):** Signal reply with help text; no DB row written.
3. **Lockout (rapid `/force-condensation` × 2):** second reply contains `experiment_in_progress`.
4. **Cancel (`/force-evaporation 30` then `/cancel-experiment` after 10s):** ack received; row has `end_reason='cancelled'`, `actual_min ≈ 0.17`.
5. **Boot recovery (D-09, LOAD-BEARING):** start `/force-condensation 30`; wait 5s; `sudo systemctl restart fc-core`. Verify (a) active_mode='fruiting' on restart; (b) WARN log "BOOT-RECOVERY: active_mode='force-condensation'"; (c) experiment_event 'truncated' published; (d) DB row closed with `end_reason='truncated_by_restart'`.
6. **Phase 30 interaction (D-08):** with schedule `[fruiting 06-22, pinning 22-06]` and clock at 21:55, fire `/force-condensation 10`. Wait until 22:00 (5 min into experiment). Verify scheduler did NOT swap to pinning. Wait for auto-revert; within 30s after revert, scheduler aligns active_mode → pinning.

Boot-recovery (Scenario 5) is the load-bearing attestation — failure here is a BLOCKER. Plan 31-02 Task 6 unit tests provide the in-code regression guard.

## Phase 31 Wave Status

| Plan | Wave | Status |
|------|------|--------|
| 31-01 | 1 | SHIPPED (10 pytest PASS; colcon deferred) |
| 31-02 | 2 | SHIPPED (code complete; pytest deferred to fc1) |
| 31-03 | 2 | SHIPPED (48 jest PASS; live smoke deferred) |
| 31-04 | 3 | SHIPPED-CODE (26 jest PASS; UAT deferred) |

Phase 31 is **code-complete**. Live deployment + farmer UAT is the remaining gate before phase closeout.
