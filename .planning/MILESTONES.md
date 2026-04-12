# Milestones

## v1.1 Tech Debt & Connectivity (Shipped: 2026-04-12)

**Phases completed:** 2 phases, 6 plans, 13 tasks
**Timeline:** 2026-04-11 → 2026-04-12 (2 days)
**Git range:** 39 commits (2 feat, 4 fix)
**Tag:** `v1.1`

### Delivered

Closed all four v1.0 carryover tech debt items and established reliable 4G
cellular connectivity to fc1 at the farm. The Pi is now reachable from
elder-plops over Tailscale via a 4G MiFi hotspot, boots cleanly without
restart loops, and Mission Control accurately replays humidifier state on
bridge restart.

### Key Accomplishments

- **fc-core boot race eliminated** — ExecStartPre polls for `tailscale0` interface with 30s timeout; `NRestarts=0` confirmed on real cold boot at the farm. Repo-to-`/etc` drift caught and hotfixed in the same session.
- **4G cellular path for fc1** — Pi associates with mossrock-lab MiFi at -25 dBm; ROS telemetry flows end-to-end over cellular via Tailscale. Dual-location verification: operator phone at farm + elder-plops at main infra, both seeing live data simultaneously.
- **fc-system-sync early-boot service** — root oneshot that stages `scripts/pi-deploy/*` into `/etc/` on every boot. Future wifi/systemd config changes ship via `git push fc1/prod` with no SSH or physical access. Includes `cmp`-based idempotency and `wpa_cli reconfigure` for same-boot reload.
- **Bridge QoS aligned** — Humidifier subscription upgraded to TRANSIENT_LOCAL QoS matching fc_controller publisher. Last-known state replays on bridge restart with no blank gap in Mission Control.
- **CycloneDDS phantom peer cleaned** — Repo config synced from WireGuard/wg0 to Tailscale/tailscale0; LeaseDuration 5s added as proactive guard against future phantom peer stalls.

### Requirements Outcome

4/4 v1.1 requirements fully satisfied:
- TDEBT-01 ✅, TDEBT-02 ✅, TDEBT-03 ✅, CONN-01 ✅

Deferred to future: SHT30 physical reinstall (sensor redundancy, SCD41 fallback works).

### Archive

- Full roadmap: `.planning/milestones/v1.1-ROADMAP.md`
- Requirements with final status: `.planning/milestones/v1.1-REQUIREMENTS.md`

---

## v1.0 MVP — FC-1 Humidity Control (Shipped: 2026-04-11)

**Phases completed:** 8 phases, 25 plans
**Timeline:** 2026-03-28 → 2026-04-11 (14 days)
**Git range:** 171 commits, 30 feat commits
**Tag:** `v1.0`

### Delivered

A closed-loop humidity control system running on the FC-1 Pi at the farm,
replacing the prior timer-based solution. Grower attested on 2026-04-11:
**"better than the timer"** — passes with enthusiasm.

### Key Accomplishments

- **Humidity control loop on FC-1** — SHT30 (now with SCD41 fallback) → bang-bang controller with hysteresis and 3-min dwell → MOSFET on GPIO27 → humidifier. `fc-core.service` under systemd, running continuously with multi-day uptime.
- **Live CO2 visibility** — SCD41 CO2 readings streamed to Mission Control. The farm had zero CO2 instrumentation before v1.0; this became the farmer's favorite feature and the highest-impact v1.0 deliverable despite being scoped as a side-effect.
- **Mission Control (OpenMCT) stack** — Node.js bridge + TimescaleDB ingestion + `/history/:topic` REST + live WebSocket broadcast + OpenMCT plugin with custom fruiting-chamber type and 24h-Fixed time conductor default.
- **Pi camera feed** — `fc_camera` ROS2 node publishing `/fc1/camera/compressed` at 1Hz; bridge serves MJPEG at `/camera/mjpeg` and saves 15-min snapshots under `/data/snapshots/fc1/YYYY-MM-DD/`.
- **CycloneDDS unicast over Tailscale** — ROS2 domain 69 peers discover via explicit unicast config (`tailscale0` interface, Peer addresses). Replaced WireGuard-primary path to survive farm connectivity instability.
- **Git-based Pi deploy pipeline** — `scripts/pi-deploy/deploy.sh` + `fc-update.service` systemd oneshot auto-pulls `fc1/prod` on every boot and rebuilds `fc_core` via colcon. Replaces the original rsync plan, which never actually shipped.
- **Safety hardening** — non-blocking sensor error handling, rolling-median spike rejection, configurable humidifier pin, test assertions on actuator state (not pin number). All from Phase 02.

### Requirements Outcome

29/31 v1 requirements fully satisfied. 2 carry tech debt into v1.1:

- **ACTR-03 QoS mismatch** — bridge subscribes VOLATILE against a TRANSIENT_LOCAL publisher. Data flows, but last-state replay on bridge restart is lost.
- **CAM-03 live MJPEG delivery** — endpoint works, snapshots flow, but live stream intermittent due to a phantom CycloneDDS subscriber at `192.168.1.193` consuming delivery slots.

Plus a cosmetic fc-core boot race on `tailscale0` interface availability (self-heals) and an SHT30 physical-reinstall task.

### Process Findings (for future milestones)

- **Verifier must check the live compose, not the file the plan edited.** Phase 07 verified `src/docker-compose.yml` while the runtime used the repo-root `/docker-compose.yml`. Historical data silently broke for weeks as a result. See memory `feedback_verify_runtime_compose.md`.
- **`docker-compose up -d` without `--build` is an invisible trap.** Both the bridge and openmct images were stale since Phase 07 and nobody noticed because `up -d` reuses the cached tag.
- **Phase SUMMARY.md frontmatter conventions are not uniform.** Some phases use `requirements-completed`, some don't. This broke the auto-accomplishments extraction during `/gsd:complete-milestone` — had to curate by hand.

### Archive

- Full roadmap: `.planning/milestones/v1.0-ROADMAP.md`
- Requirements with final status: `.planning/milestones/v1.0-REQUIREMENTS.md`
- Audit report: `.planning/milestones/v1.0-MILESTONE-AUDIT.md`

---
