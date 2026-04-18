# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0 — MVP FC-1 Humidity Control

**Shipped:** 2026-04-11
**Phases:** 8 | **Plans:** 25 | **Timeline:** 14 days (2026-03-28 → 2026-04-11)

### What Was Built

- Closed-loop humidity control on FC-1 Pi: SHT30/SCD41 → bang-bang hysteresis controller with 180s dwell guard → MOSFET on GPIO27 → humidifier. Running under `fc-core.service` systemd unit.
- Mission Control (OpenMCT) with live WebSocket telemetry + TimescaleDB-backed historical charts via `/history/:topic` REST, served by a Node.js bridge that replaced the original rosbridge_suite Python stack.
- Pi camera feed: `fc_camera` ROS2 node publishing `/fc1/camera/compressed`, bridge MJPEG endpoint + 15-min snapshot archive, OpenMCT custom view provider.
- Git-based Pi deploy pipeline (`scripts/pi-deploy/deploy.sh` + `fc-update.service` boot oneshot) pulling the `fc1/prod` branch into `~/mushroom_farm_ws/mushy-repo/`.
- CycloneDDS unicast over Tailscale for ROS2 DDS across the farm VPN, replacing the originally-planned plain-WireGuard path when farm connectivity proved unreliable.
- Safety hardening: non-blocking sensor error handling, rolling-median spike rejection, configurable humidifier pin, correct test assertions, stale-data safe-fail.

### What Worked

- **Audit-driven closure.** The final `/gsd:audit-milestone` pass caught four phases without VERIFICATION.md files and two cross-phase integration gaps (ACTR-03 QoS mismatch, CAM-03 stale subscriber) that would otherwise have shipped silently. Runtime verification via SSH to fc1-ts was cheap and revealing.
- **Scope elasticity during execution.** Phases 6 (WireGuard/Tailscale), 7 (historical data), and 8 (camera) were all added after the initial v1.0 roadmap but integrated cleanly into the milestone. Phase boundaries held.
- **SCD41 as side-quest.** Adding SCD41 primarily as a temp/humidity fallback for SHT30 accidentally delivered the farm's highest-impact v1.0 feature (CO2 visibility). Taking "free" sensor data during a deploy turned out to matter more than the planned primary function.
- **Grower attestation instead of metric.** "Better than the timer" is a qualitative bar that was much faster to achieve agreement on than a quantitative soak-test threshold would have been.

### What Was Inefficient

- **Compose-file drift.** A minimal `/docker-compose.yml` was created during the 2026-03-28 elder-plops migration; Phase 07 then edited `src/docker-compose.yml` (stale copy) while the runtime used the root. Historical data was silently broken for weeks. The Phase 07 verifier never caught it because it read the file the plan edited, not the file `docker-compose up -d` actually used.
- **Docs drift.** `OPERATIONS.md`, `docs/pi-setup/dev-workflow.md`, and `.planning/PROJECT.md` all described an rsync deploy pipeline long after `deploy.sh` had switched to git. Memory `feedback_deploy_method.md` perpetuated the lie. Cost: multiple wrong recommendations mid-session before a manual correction.
- **Phase VERIFICATION.md was optional.** 4 of 8 completed phases reached "done" without a VERIFICATION.md. Going back and writing them retroactively during audit closure was slower than writing them at phase-end would have been.
- **SUMMARY.md frontmatter conventions were not uniform.** Some phases used `requirements-completed: [REQ-01, REQ-02]`, others didn't. This broke automated accomplishments extraction during `/gsd:complete-milestone` and required manual curation of the MILESTONES.md entry.
- **Stale Docker images.** Both `mushy_openmct_1` and `mushy_bridge_1` ran pre-Phase-07 images for weeks because `docker-compose up -d` without `--build` silently reuses the cached tag. The Node.js bridge was in the repo but never reached the runtime.

### Patterns Established

- **Verify against the runtime, not the plan target.** When a phase touches infra (compose files, env vars, deploy scripts), verification must `curl` the endpoint, `docker inspect` the running image, or `systemctl show` the unit — never just read the file the plan edited. Saved as memory `feedback_verify_runtime_compose.md`.
- **Git-based Pi deploy + boot-time auto-pull.** `scripts/pi-deploy/deploy.sh` + `scripts/pi-deploy/fc-update.service` is the canonical pattern for any ROS2 Pi deploy target. Saved as memory `feedback_deploy_method.md`.
- **Mission Control naming.** Call OpenMCT "Mission Control" in grower-facing docs and conversation. Saved as memory `feedback_naming.md`.
- **Signal for farm notifications.** Not Telegram, not Slack. Saved as memory `project_signal_alerts.md`.

### Key Lessons

1. **Two compose files is a trap.** Having `/docker-compose.yml` and `src/docker-compose.yml` diverge silently cost weeks of broken historical data. One canonical compose file per environment; if you must have two, delete one or mark it `DEPRECATED` at the top.
2. **`docker-compose up -d` without `--build` is an invisible image-freeze.** Any phase that changes an image's source must rebuild explicitly. Consider adding `pull_policy: build` or a `--build` habit to deploy scripts.
3. **Retroactive verification catches the things the phase verifier missed.** The milestone-closure audit is not redundant with per-phase verification — it has a different perspective and sees cross-phase integration the per-phase verifier can't.
4. **Side-effect features can dominate planned features in grower value.** The farm's prior instrumentation gap defined which of v1.0's deliverables was most valuable, and that was not knowable at scoping time. Leave room for "free" sensors/capabilities even when they're not the primary goal — they're often the real win.
5. **"human_needed" VERIFICATION.md is a deferred liability.** Phases 03, 04, 07 all had `status: human_needed` and nobody actually did the human verification until the milestone audit. Either build a checkpoint that forces it, or drop the status and accept code-level verification.

### Cost Observations

- Model mix: primarily Opus (this session); earlier phases used a mix of Opus and Sonnet per GSD profile `balanced`. No hard measurement captured.
- Sessions: multiple across the 14-day window; final milestone closure compressed most of the paperwork into one session on 2026-04-11.
- Notable: one long session (this one) recovered from the historical-data regression, wrote 4 retroactive VERIFICATION.md files, refreshed REQUIREMENTS/PROJECT/docs, and ran the full audit → complete-milestone pipeline. Audit catching the stale compose file saved weeks of future confusion.

---

## Milestone: v1.1 — Tech Debt & Connectivity

**Shipped:** 2026-04-12
**Phases:** 2 | **Plans:** 6 | **Timeline:** 2 days (2026-04-11 → 2026-04-12)

### What Was Built

- fc-core boot race fix — ExecStartPre polls tailscale0, NRestarts=0 on cold boot
- 4G cellular path for fc1 — MiFi at farm, ROS-over-cellular via Tailscale, dual-location verified
- fc-system-sync early-boot service — root oneshot syncing `scripts/pi-deploy/*` → `/etc/` on boot, with cmp-based idempotency and same-boot wpa_cli reconfigure
- Bridge QoS aligned — TRANSIENT_LOCAL on humidifier subscription closes ACTR-03 from v1.0
- CycloneDDS phantom peer eliminated — repo config synced to Tailscale, LeaseDuration 5s guard

### What Worked

- **Tight scope.** 4 requirements, 2 phases, 2 days. Zero scope creep. The cleanest milestone so far — the v1.0 audit pre-identified exactly what needed fixing.
- **Phase 09 emerged a bonus plan (09-04).** The fc-system-sync mechanism wasn't in the original 3-plan phase but was necessary to safely cut over wifi without risking SSH access. It became the most valuable v1.1 deliverable — future config changes ship via `git push` with no SSH or physical access.
- **Repo/runtime drift caught early this time.** The v1.0 lesson about verifying runtime state (not plan targets) paid off immediately: 09-01 caught a stale CYCLONEDDS_URI in the repo during deploy and hotfixed it before the farm cold boot.
- **TDEBT-02 was already resolved by Phase 09.** The phantom peer at 192.168.1.193 disappeared when Phase 09 restarted fc-core with the Tailscale CycloneDDS config. Plan 10-02 only needed to sync the repo and add a proactive LeaseDuration guard — saved significant debugging time.

### What Was Inefficient

- **09-03 physical verification items deferred.** WAN-blip recovery test and <30s dashboard timing require another farm visit. These are regression checks — the underlying mechanisms work — but they leave acceptance criteria formally open.
- **REQUIREMENTS.md traceability never updated during execution.** All four requirements still showed "Pending" in the traceability table despite all being satisfied per SUMMARY.md files. The archival step had to fix this retroactively.
- **STATE.md drifted.** Progress bar showed 0%, milestone showed v1.0, current focus showed Phase 09 — all stale. The CLI's STATE.md update only patched `last_activity` because the field format didn't match expectations.

### Patterns Established

- **fc-system-sync git-ops pattern.** For single-link Pis: commit config → boot pulls → fc-system-sync stages → netplan generate → wpa_cli reconfigure. Never drops the current link (additive merge + auto-fallback). Reusable for any Pi where SSH is the only access path.
- **Interface-wait pattern in systemd.** ExecStartPre inline bash loop polling `ip link show <iface>` with 1s cadence and 30s timeout. Generic for any ROS2 service binding to a VPN interface.
- **QoS-aware rclnodejs subscription.** Construct `rclnodejs.QoS` inside `main()` (after `init()`), pass as `{ qos: obj }` 3rd arg before callback. Required for any DDS topic with non-default QoS.

### Key Lessons

1. **The best debugging is prevention by earlier phases.** TDEBT-02 (phantom peer) was resolved as a side effect of Phase 09's fc-core restart, not by 10-02's explicit fix. When a later phase discovers its bug is already fixed, that's a signal the dependency graph is working.
2. **An emergent plan (09-04) can be the milestone's highest-value deliverable.** fc-system-sync wasn't scoped until mid-execution but became the mechanism that makes all future Pi config changes safe and remote. Don't resist scope additions when they solve a real problem cleanly.
3. **STATE.md is fragile to format drift.** The GSD CLI's field-matching is brittle — any manual edits to STATE.md format cause partial update failures. Keep STATE.md machine-written; edit other docs manually.

### Cost Observations

- Model mix: Opus for both sessions (discuss/plan and execute for each phase)
- Sessions: 2 main sessions (Phase 09 on 2026-04-11, Phase 10 on 2026-04-12)
- Notable: Phase 10 plans executed in ~3 minutes total — the smallest plans in the project so far. The research phase correctly identified that TDEBT-02 was already resolved and scoped accordingly.

---

## Milestone: v1.2.1 — Hotfix: camera stall + sensor warmup

**Shipped:** 2026-04-18
**Phases:** 3 (14, 15, 16) + 16.1 follow-up | **Plans:** 11

### What Was Built

- fc_camera idle-stall fix: 1 Hz `count_subscribers` graph-poll in `fc_camera.py` (9s recovery on canonical stall, 30-min soak PASS).
- Two camera-panel status lights in Mission Control ("Feed live" + "Camera subscribed") via a new reusable `makeStatusLight(parentEl, label)` primitive.
- Bridge `/health` extended with `camera.last_frame_age_sec`, `camera.subscribed`, `ros.connected`, `humidifier.last_msg_ts`.
- Sensor warm-up grace period: 20s controller early-return + `/fc1/sensor_health` DiagnosticStatus WARN→OK, satisfying SENS-01.
- Six-light system health panel in Mission Control consuming `/fc1/sensor_health` + `/health` signals.
- Phase 16.1 replay shim: bridge caches `lastSensorHealthBroadcast` and replays to new WS clients on connect.

### What Worked

- **Autonomous loop held end-to-end.** `/gsd:autonomous` drove discuss→plan→execute across Phases 14/15/16 in a single session, with Phase 16.1 follow-up added after farmer UAT surfaced the cold-open greys. Farmer-attested "all green" the next day with no scope expansion needed.
- **Primitive reuse across phases.** `makeStatusLight` from Phase 14 (camera panel) was reused unchanged by Phase 16 (six-light strip). Cross-phase integration check found zero API drift — the primitive landed with the right signature on first try.
- **Diagnostic before patch.** Phase 14 Plan 01 was a live no-op probe that distinguished idle-callback starvation (Path A) from DDS staleness (Path B). Patching happened against a confirmed root cause, not a guessed one — the 9s recovery is direct evidence the fix targets the actual mechanism.
- **Farmer constraint made explicit.** "Bigger gap than noise" (captured in memory `feedback_gap_over_noise.md`) drove the grace-gate design: publish WARN/empty, never spiky values. Design question answered before it was asked.

### What Was Inefficient

- **Cold-open sensor_health greys slipped past Phase 16 verification.** Phase 16 SMOKE_PASS came from a warm WebSocket — the farmer hit the cold-open path on hard refresh and saw grey lights. Caught in HUMAN-UAT, fixed in 16.1 the same session. Verification should have included a "hard refresh after controller publishes WARN then OK" flow.
- **MILESTONES.md auto-extraction still noisy.** `gsd-tools milestone complete` produced 15 garbage bullets from summary-frontmatter scraping (same failure mode as v1.0). Had to manually curate the entry. The parser evidently doesn't know how to skip summary sub-headers.
- **STATE.md field drift.** The `gsd-tools` CLI warned it couldn't find "Last Activity Description" in STATE.md — the file format has drifted from the tool's expectations. Non-blocking but accumulating.
- **Humidifier replay parity not shipped.** sensor_health got a replay shim (16.1); humidifier state still relies only on ROS-level TRANSIENT_LOCAL replay to the bridge. Deferred as tech debt; future cold-open may surface the same greyness.

### Patterns Established

- **1 Hz graph-poll for ROS callback-starvation fixes.** When an idle subscriber-aware node goes dark, a `create_timer(1.0, ...)` running `count_subscribers` beats waiting on publish-driven callbacks.
- **Server-computed `_age_sec` fields.** Bridge now returns integer seconds computed against server clock instead of sending raw timestamps — eliminates client clock-skew interpretation and makes ages directly comparable to thresholds like `< 10`.
- **`makeStatusLight(parentEl, label) -> {setGreen,setRed,setGrey,destroy}`.** Stable primitive for any grower-facing status indicator. Keep the signature stable; lights cheap to add.
- **Replay-on-connect shim for WS broadcasts that matter on cold open.** Cache `last*Broadcast` at broadcast time; on `wss.on('connection')`, replay to that single socket before the first live message arrives. Don't rebroadcast to everyone.

### Key Lessons

1. **Cold-open paths are distinct from warm-reconnect paths.** Hard-refresh or first-visit is not equivalent to "reconnect after restart" — a WS reconnect may still beat the next publish, but a cold load of a page starts with nothing. Verification of status-light features must include the cold-open flow explicitly.
2. **Autonomous run ≠ single-session narrative.** UTC-midnight split a continuous autonomous run across two calendar days; earlier drafts invented a "Saturday morning handoff" from file mtimes that didn't happen. Memory `feedback_dont_invent_time_narrative.md` captures this.
3. **"Frozen image" symptoms hide callback-frequency bugs, not network bugs.** The intuitive hypothesis was DDS staleness; the actual cause was a subscriber-poll callback firing every 3597s instead of every 1s. The diagnostic phase earned its keep.
4. **Grey is an actionable color.** The six-light panel treats grey as "unknown / not yet reported" rather than green-by-default. Farmer-trusted because wrong-looking green would be worse than honest grey — reinforces `feedback_gap_over_noise.md`.

### Cost Observations

- Model mix: Opus throughout (autonomous loop under `balanced` profile).
- Sessions: 1 main autonomous session (2026-04-17 evening) + 1 UAT close-out (2026-04-18 morning).
- Notable: 3 phases + 1 follow-up shipped in a single session. Hotfix milestone cadence — "small, surgical, shipped same-day" — is viable when the diagnostic is done first.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 8 | 25 | Initial project; established GSD workflow, git-based Pi deploy, Mission Control stack |
| v1.1 | 2 | 6 | Tech debt closure; fc-system-sync git-ops pattern; tight scope from audit-driven requirements |
| v1.2 | 3 | 7 | FarmOS beachhead (farmos_agent), subscriber-aware camera, compose v2 |
| v1.2.1 | 3 | 11 | Hotfix cadence; autonomous multi-phase run; reusable status-light primitive; replay-on-connect pattern |

### Top Lessons (Verified Across Milestones)

1. **Verify against the runtime, not the plan target.** v1.0: compose-file drift broke historical data for weeks. v1.1: CYCLONEDDS_URI drift caught during deploy and hotfixed before cold boot. The lesson held and saved time the second time.
2. **Retroactive verification catches cross-phase integration gaps.** v1.0: audit found ACTR-03 QoS mismatch and CAM-03 phantom peer. v1.1: these became the entire milestone scope, proving the audit was worth the effort.
3. **Side-effect fixes accumulate.** v1.0: SCD41 CO2 was a side-effect win. v1.1: Phase 09's fc-core restart resolved TDEBT-02 as a side-effect, saving Phase 10 debugging time.

---
*Last updated: 2026-04-18 at v1.2.1 milestone completion.*
