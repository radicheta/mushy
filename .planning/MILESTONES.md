# Milestones

## v1.2.1 Hotfix — camera stall + sensor warmup (Shipped: 2026-04-18)

**Phases completed:** 3 phases (14, 15, 16), 11 plans + Phase 16.1 follow-up
**Timeline:** 2026-04-17 → 2026-04-18 (same-session autonomous run + next-day UAT)
**Git range:** `v1.2..v1.2.1` (6 feat commits across phases 14/15/16/16.1)
**Tag:** `v1.2.1`

### Delivered

A hotfix milestone filed during a farmer debug session on 2026-04-17 and
shipped autonomously the same session. Addresses two operator-trust erosions:
camera feed silently freezing in Mission Control and humidifier briefly
actuating on sensor noise during fc-core restart. Also lands a system-health
panel (six status lights) so both conditions are legible to the operator
without reading logs. Farmer-attested "all green" 2026-04-18.

### Key Accomplishments

- **fc_camera idle-stall hotfix (Phase 14)** — Root-caused the frozen-feed symptom via live diagnostic (Path A: idle callback at 3597 s, not DDS staleness). 1 Hz `count_subscribers` graph-poll added to `fc_camera.py`; canonical stall now recovers in 9 s (30-min soak SOAK_PASS). Two status lights added to MC camera panel ("Feed live", "Camera subscribed") via a new reusable `makeStatusLight(parentEl, label)` primitive in plugin.js. Bridge `/health` extended with `camera.last_frame_age_sec` + `subscribed`.
- **Sensor warm-up grace period (Phase 15, promoted from 999.8)** — Farmer constraint "bigger gap than noise" honored: `fc_controller` now early-returns from `control_loop` for the first 20 s post-boot (ANDed with buffer-full guard) and publishes `/fc1/sensor_health` `DiagnosticStatus` WARN→OK. Live soak confirmed WARN→OK at 25 s with no humidifier actuation in the grace window. SENS-01 promoted from duplicate Future/Out-of-Scope to canonical v1.2.1 active requirement.
- **System health panel (Phase 16)** — Narrow six-light strip in Mission Control: Sensors, Camera feed, Humidifier, Bridge, Pi reachable, Grace. Reuses Phase 14 `makeStatusLight`. Bridge flattens `DiagnosticStatus.KeyValue[]` into plain JS `values{}` for browser consumption; adds `ros.connected` + `humidifier.last_msg_ts` to `/health`. Humidifier light uses a 30 s watchdog window.
- **Phase 16.1 replay shim** — Farmer UAT caught "sensor_health lights grey on fresh page load". Fixed same-session: bridge caches `lastSensorHealthBroadcast` and sends it only to newly-connected WS clients. Humidifier state still relies on ROS-level TRANSIENT_LOCAL replay (parity deferred as tech debt).

### Requirements Outcome

1/1 v1.2.1 formal requirement satisfied:

- **SENS-01** ✅ — sensor warm-up grace + `/fc1/sensor_health` WARN→OK verified live.

Phases 14 and 16 used plan-frontmatter hotfix IDs (HFIX-01..05, WARMUP-01..04);
all SATISFIED per phase VERIFICATION files.

### Tech Debt Incurred (non-blocking)

- Humidifier state has no bridge-side replay cache for new WS clients (relies on ROS TRANSIENT_LOCAL to the bridge only). Fine today; revisit if a "cold-open greys" report surfaces.
- Health view opens a second WebSocket alongside the telemetry WS — note for any future client-quota work.
- Phase 14 VALIDATION.md is draft-only; Phases 15 & 16 have no VALIDATION.md. Live soak + unit tests substitute for formal Nyquist validation on this hotfix.

### Process Findings

- **Autonomous multi-phase hotfix shipped same-session.** `/gsd:autonomous` drove Phases 14 → 15 → 16 → 16.1 start-to-finish with farmer-attested UAT next day — confirms the autonomous loop holds for tight scope.
- **UTC-midnight is not a session boundary.** Earlier write-up invented a "Saturday handoff" narrative from file mtimes; all four phases were a single continuous session. See memory `feedback_dont_invent_time_narrative.md`.

### Archive

- Full roadmap: `.planning/milestones/v1.2.1-ROADMAP.md`
- Requirements with final status: `.planning/milestones/v1.2.1-REQUIREMENTS.md`
- Audit report: `.planning/milestones/v1.2.1-MILESTONE-AUDIT.md`
- Autonomous run notes: `.planning/milestones/v1.2.1-AUTONOMOUS-RUN-SUMMARY.md`

---

## v1.2 FarmOS Integration & QoL (Shipped: 2026-04-13)

**Phases completed:** 3 phases, 7 plans, 5 tasks

**Key accomplishments:**

- docker-compose v1 purged and replaced with compose v2 plugin (2.40.3) on elder-plops; all 3 Mission Control services running with hyphen-named containers and live telemetry confirmed flowing
- fc_camera.py:
- One-liner:
- One-liner:
- One-liner:
- Rebuilt bridge and farmos-agent containers with Plan 03 bug fixes; scheduler active at 06:00; three FarmOS admin actions pending user browser access.

---

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
