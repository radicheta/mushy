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

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 8 | 25 | Initial project; established GSD workflow, git-based Pi deploy, Mission Control stack |

### Top Lessons (Verified Across Milestones)

1. *(pending v1.1)* — verify whether the "two compose files is a trap" and "`--build` is an invisible trap" lessons hold when v1.1 touches different infra.

---
*Last updated: 2026-04-11 at v1.0 milestone completion.*
