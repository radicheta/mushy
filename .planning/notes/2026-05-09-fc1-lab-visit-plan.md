# 2026-05-09 fc1 Lab Visit — Plan

**Date:** Saturday 2026-05-09 (morning)
**Goal:** Close out Phase 30 + Phase 31 deploy + UAT in one on-lab session, recover camera, surface a short discussion list with the farmer.

## Context

- Phase 30 (time-of-day mode scheduling) — code-complete, tests GREEN, deploy + Layer 1/Layer 2 smoke + farmer attestation pending. See `30-03-PLAN.md` Tasks 2–4.
- Phase 31 (experimental forcing modes) — code-complete, +84 new test cases GREEN, deploy + 6 UAT scenarios pending. See `31-04-PLAN.md` Task 3.
- Camera offline since [date — confirm on arrival]; needs physical inspection + restart.
- Memory `feedback_fc1_remote_action_preflight_protocol` applies to every reboot/network/transport-down action.

## Pre-arrival checklist

- [ ] Confirm fc1 reachable over wg0 (`ssh 172.16.10.5`); if not, escalate to ethernet + memory `project_2026_05_07_fc1_reboot_unrecoverable` recovery recipe.
- [ ] Confirm bridge healthy on elder-plops (`docker compose ps`, `/health` returns 200).
- [ ] Pull fresh main on fc1: `git -C /home/santi/mushroom_farm_ws fetch origin main` (sanity check; deploy.sh will do this for real).
- [ ] Snapshot Timescale state pre-deploy (`select count(*) from telemetry where time > now() - interval '1h'`) — baseline for delta after deploy.

## On-arrival sequence (ordered)

### 1. Camera back online (do first — visible signal of "we're here")
- [ ] Physical inspection: power LED, ribbon-cable seat, lens free of condensation
- [ ] `journalctl -u fc-core -n 200 | grep -i camera`
- [ ] Verify `fc1/camera/frame` topic publishing: `ros2 topic hz /fc1/camera/frame`
- [ ] Bridge `/snapshot` endpoint serves a recent frame
- [ ] Mission Control / farmOS shows live feed
- [ ] If hardware-fault: file under 999.x; do NOT block lab visit on camera

### 2. Deploy Phase 30 + Phase 31 together
- [ ] Operator preflight per memory `feedback_fc1_remote_action_preflight_protocol`
- [ ] `git push fc1/prod` (from elder-plops or local)
- [ ] On fc1: `bash scripts/pi-deploy/deploy.sh` — builds `fc_msgs` (new srvs!) + `fc_core`, restarts service
- [ ] On elder-plops: `docker compose up -d --build bridge` — picks up `control_experiment.js`, `control_param.js` allowlist, DB migrations
- [ ] On elder-plops: rebuild + restart alerter image (Signal command parser)
- [ ] Verify all green: fc-core service active, bridge `/health` 200, alerter container running

### 3. Phase 30 smoke (Plan 30-03 Tasks 2–3)
- [ ] **Layer 1 hot-apply:** `POST /control/param` with a 2-window schedule; observe 30s tick → mode swap on boundary; check `current_mode` topic shows `source='scheduler'`.
- [ ] **Layer 2 persist:** `POST /control/persist`; restart fc-core; confirm `runtime_overrides.yaml` survived and schedule reloaded.
- [ ] **Backward-compat:** Set `schedule_windows` back to `"[]"`; confirm controller falls back to single-mode (`active_mode`-driven) behavior.
- [ ] Capture `30-03-SMOKE.md` with timestamps + log evidence.

### 4. Phase 31 UAT (Plan 31-04 Task 3 — six scenarios)
1. **Happy path** — `/force-condensation 5` over Signal; observe 100% duty for 5 min; auto-revert to prior mode; `fc_experiments` row populated with non-NaN delta_rh.
2. **Hard cap** — try `/force-condensation 200`; expect rejection (cap = 120).
3. **Single-experiment lockout** — start one, try to start another; expect `experiment_in_progress`.
4. **Cancel** — start a 30 min experiment, send `/cancel-experiment`; immediate revert; row populated with `end_reason='cancelled'`.
5. **Boot-recovery (D-09 — load-bearing)** — start a 30 min `force-condensation`, then physically reboot fc1 mid-experiment; on boot, controller MUST come up in safe baseline (not force-condensation), DB row marked `truncated_by_restart`. **This is the safety scenario; do NOT skip.**
6. **Phase 30 interaction (D-08)** — set a schedule with a near-term boundary, then start a force-experiment that spans the boundary; scheduler MUST be suppressed during experiment; on revert, scheduler re-aligns within 30s.

### 5. Farmer attestation
- [ ] Farmer (radicheta@gmail.com) reviews live system; reply `"approved"` / `"approved with notes"` / `"issues: ..."`.
- [ ] Attestation captured in commit message or `30-03-SUMMARY.md` / `31-04-SUMMARY.md`.

### 6. Lifecycle (only if both phases attested clean)
- [ ] `/gsd-audit-milestone`
- [ ] `/gsd-complete-milestone v1.5`
- [ ] `/gsd-cleanup`

## Discussion items for the farmer (handful)

These are not test items — they are decisions/seeds we want operator input on while we're there with chamber access:

1. **Forced condensation — operational fit.**
   - Phase 31 ships `force-condensation` (100% duty, timed). What's the actual experimental workflow? Single 15 min burst before pinning entry? Multi-hour saturation?
   - Default duration we picked is 15 min (cap 120). Right ballpark or wrong?
   - Are there chamber states (e.g. mid-fruiting flush) where operator wants `force-condensation` BLOCKED for safety?

2. **Negative vapour pressure / VPD — is it a real ask?**
   - SEED-004 reserves `T_target` field for VPD-anchored control. Phase 31 `force-evaporation` (0% duty) is the closest we have to "drive VPD up."
   - Open question: does the farmer want **closed-loop VPD targeting**, or is **timed force-evaporation** sufficient for the experiments they have in mind?
   - Closed-loop VPD requires temperature sensing AND time. We have temp sensing. We don't have temp control.
   - Decide: file VPD-targeted control as a v1.6 milestone, or close 999.33 as "covered by Phase 31 force-evap"?

3. **Camera coverage gap (999.26).**
   - While at the chamber: confirm what camera coverage is actually needed. Single overhead? Side angle? Multi-camera (Pi Zero remote-I/O memory `project_multi_chamber_pi_zero`)?
   - This unblocks Phase 24 (ML vision events) re-scoping.

4. **Schedule profile — first real-world value.**
   - Phase 30 ships the primitive. What's the FIRST schedule the farmer would run in practice? (e.g. fruiting 06:00–22:00, pinning 22:00–06:00? Or shorter pinning windows?)
   - Capture as the v0 farmOS schedule UI seed — gives the farmOS / Zoy work concrete shape.

5. **BUF-04 natural event evidence (memory `project_buf04_natural_event_evidence_sweep`).**
   - System has been too stable to attest BUF-04 organically. While we're physically at the chamber: schedule a 10–30 min controlled outage from elder-plops side? Closes v1.5.0.1 retroactive item.

## Failure scenarios to deliberately exercise

Beyond Phase 31 UAT-5 (boot-recovery), opportunistically test these while we have physical access:

- [ ] **fc-core service kill mid-control** — `sudo systemctl kill fc-core`; verify systemd `Restart=always` recovers within bounded retry window (memory `project_blackout_2026_05_02_fc_core_stuck` regression check).
- [ ] **Tailscale flap** — `sudo systemctl restart tailscaled` on fc1; verify wg0 stays up (memory `project_fc1_link_architecture_options`); buffer-replay engages on bridge side.
- [ ] **Bridge restart mid-experiment** — start a 30 min experiment; restart bridge container; confirm `experiment_event` topic re-subscribes (TRANSIENT_LOCAL replay) and DB row eventually closes.
- [ ] **Schedule edit while in-mode-transition** — POST a new schedule mid-transition; confirm validator + controller don't deadlock.
- [ ] **Bad schedule JSON** — POST malformed `schedule_windows`; confirm 400 from bridge AND controller `on_set_parameters_callback` rejection.

## Risks & escalation

- **fc1 unreachable** → ethernet at lab + memory `project_2026_05_07_fc1_reboot_unrecoverable` recipe.
- **`fc_msgs` build fails on fc1** → check colcon log; new srvs (`StartExperiment`, `CancelExperiment`) require CMakeLists wiring (already in 31-01 commit, verify present).
- **Bridge migration fails** → `fc_experiments` table create is `IF NOT EXISTS`-idempotent (Phase 27.1 pattern). If fails, capture log + roll back bridge image.
- **Farmer flags issue during UAT** → capture detail, do NOT silently retry; file a deferred item or new phase per memory `feedback_run_verifications_yourself`.

## Out-of-scope for this visit

- New phase planning (30+31 only).
- VPD closed-loop work (depends on item 2 above).
- Mission Control UI for experiments (Phase 28 D-20 — farmOS owns UI).
- Multi-chamber / Pi Zero remote-I/O work.

---

*Visit plan author: Claude*
*Author check-in: ship Saturday morning, one fc1 on-lab session*
