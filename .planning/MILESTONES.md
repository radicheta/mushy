# Milestones

## v1.5.0.1 Resilience Hotfix (Shipped: 2026-05-07 PARTIAL)

**Phases shipped:** 2 (27.1, 27.2) + 27.3 + 27.4 MOOTED by transport switch
**Plans:** 5 total (27.1=4, 27.2=1)
**Timeline:** 2026-05-01 → 2026-05-07 (~6 days)
**Tag:** `v1.5.0.1`
**Pattern:** hotfix milestone (cf. v1.2.1) — single-incident-driven, narrow scope

### Delivered

Hotfix triggered by the 2026-05-02 blackout + DERP-relay incident. Mid-flight architectural detour: fc1 microSD failed during diagnosis; fc1 was rebuilt on home-LAN wifi with a kernel-WireGuard tunnel through pfSense (172.16.10.0/24); DDS switched from `tailscale0` to `wg0`. Transport switch absorbed SAMP entirely (CPU saturation gone, fc1 load avg 5+ → 0.41) and parked NET (netplan reconciliation was a farm-4G snapshot that no longer applies until fc1 returns). Edge buffering + fc-core systemd hardening shipped on the new transport.

### Key Accomplishments

- **Phase 27.1 — Edge buffering + replay-on-reconnect** — `fc_buffer` ROS node on fc1 (sqlite WAL, 24h retention, http server on `wg0` IP `172.16.10.5:8765`) + bridge replay-poller backfilling on demand. Idempotent ingest via `UNIQUE (topic, time)`. BUF-01..03 attested live; BUF-04 induced-dropout recipe retired (no longer reproduces post-transport-switch); natural-event attestation deferred to **999.36**.
- **Phase 27.2 — fc-core systemd hardening** — `Restart=always` + `StartLimit*` + explicit `After=/Wants=wg-quick@wg0.service` + 60×1s IPv4-on-wg0 `ExecStartPre` loop. SYS-04 cold-reboot scenario PASS 2026-05-07 (41s boot → fc-core active, zero manual). SYS-04 wg0-down-at-boot scenario deferred to **999.28** (lab LAN gated).
- **Architectural detour: DDS transport switch** — fc1↔elder-plops moved off `tailscale0` (DERP-relay flakiness under CGNAT) to `wg0` (kernel-WG via pfSense). Eliminated the tailscaled CPU saturation that had originally motivated Phase 27.3. Tailscaled disabled on fc1.

### Deferred / Tech Debt Carried

- **BUF-04** natural-event attestation → 999.36 (system too stable to attest organically; needs operator-induced 10–30 min outage from elder-plops side).
- **SYS-04 scenario 2** (wg0-down-at-boot) → 999.28 (chicken-and-egg over wg0 itself; gated on lab LAN access).
- **Bridge buffer-replay cursor advance bug** — defeats backfill on reconnect (recovery used manual psql staging during the 2026-05-07 11h gap). Structural fix is a 1-line removal at bridge `index.js:613`. Tracked in memory.
- **PID bumpless re-engage hardcoded `last_output=0.15`** at `fc_controller.py:973` — fixed downstream in Phase 29 plan 29-07 (commit `e95a599`).
- **Manual fc1 netplan edits** — `mossrock-west` SSID added by hand at lab 2026-05-07 then committed (`789a699`); edit-then-commit ordering re-surfaces the underlying anti-pattern when fc1 returns to the farm.
- **microSD wear from fc_buffer SQLite WAL** — gated on USB-SSD hardware procurement.
- **Phase 27.3 / 27.4** — both mooted in current form; re-promote to backlog when load conditions / farm location change.

### Process Lessons (memory)

- `feedback_fc1_remote_action_preflight_protocol.md` — gating checklist for reboots/network-config/transport-down actions.
- `feedback_verify_executor_deviation_text.md` — gsd-executor agents misattribute benign warnings as root causes.

---

## v1.4 Vision & Growth Insights (Shipped: 2026-05-01)

**Phases shipped:** 5 (21, 22, 23, 25, 26) + Phase 24 deferred behind backlog 999.26
**Plans:** 19 total (21=4, 22=4, 23=3, 25=5, 26=3)
**Timeline:** 2026-04-19 → 2026-05-01 (~12 days)
**Tag:** `v1.4`

### Delivered

CV pipeline foundation (continuous camera persistence, time-lapse composition, farmer story view via farmOS hand-off), bidirectional Signal "Field Notes" channel for farmer↔robot capture (text + audio + photos with local Whisper + Anthropic LLM reply), and dual-sensor visibility closing the 2026-04-11 incident class where a 40-min unnoticed SHT30 outage cost a calibration session. Phase 24 (ML vision via ComfyUI) explicitly deferred behind a camera-coverage prerequisite — single-camera footprint = demo, not field utility.

### Key Accomplishments

- **Phase 21 — Camera history continuous persistence** — Bridge becomes the always-on persister regardless of viewer presence. New Timescale `snapshots` hypertable with 365-day retention + 30-day grace. `/camera/history` endpoint + `/health` extension + Mission Control "Snapshots" status chip. 11/11 must-haves verified.
- **Phase 22 — Timeline scrubber + farmer story view** — Mushy delivers the data surface (`/camera/frame` + burnt-overlay sidecar with sensor values); farmOS owns the UI per Zoy-side hand-off (CLAUDE-SYNC.md addendum committed in farmos repo `933ea85`). 11/11 must-haves verified.
- **Phase 23 — Time-lapse composition** — Nightly ffmpeg pipeline composes per-day mp4s with timestamp + RH overlay. First real artifact: `/data/timelapse/fc1/2026-04-26.mp4` (287 frames, h264). On-demand `/timelapse` endpoint. Farmer "looks good" 2026-04-27.
- **Phase 25 — Bidirectional Signal (Field Notes)** — Farmer DMs the robot text/audio/photos; whisper-transcribe container (CUDA, FastAPI) handles audio locally; Anthropic LLM composes contextual reply with 24h sensor-history snapshot; signal-cli pipe unblocked via primary re-registration on the 4G router SIM. 7/7 farmer UATs PASS 2026-04-28.
- **Phase 26 — Dual sensor publishing + offline alarms** — SHT30 and SCD41 publish on separate slot topics (`fc1/temperature`, `fc1/temperature_2`, etc.) with per-sensor freshness in `sensor_health`. Signal alerts fire on either physical sensor going silent for ≥5 min with symmetric recovery. UAT-8 PASS 2026-04-29 — farmer eyeballed the slot-1/slot-2 RH overlay and confirmed SCD41 clipping at 100%, exactly the failure mode dual-publish was built to surface.

### Deferred / Tech Debt Carried

- **Phase 24** — explicitly deferred 2026-05-01 behind new backlog item **999.26** (roaming or multi-cam coverage). Phase scope preserved in `.planning/milestones/v1.4-ROADMAP.md` for re-promotion when 999.26 ships.
- **Phase 25 deferred items** (5) — see `25-deferred-items.md`: D-03 LLM-failure degraded-flag persistence, llm_session_tag column never populated, multi-envelope context window, config.test.js DASHBOARD_URL leak, HuggingFace cache not on a named volume. Backlog: 999.20 (multi-farmer routing + group participation).
- **Phase 23** — CO2 overlay gap (open item); 999.21 timelapse resolution bump filed.
- **Phase 26** — SCD41 RH known to clip at 100% — SHT30 remains RH source of truth in any future control or alert logic. Process lesson: plan-26-02 contract-tested bridge half but missed the UI surface (allowlist + plugin) — patched same session via commit `2b5ae75`.
- **Cross-milestone carry from v1.3:** Phases 19 (FarmOS admin actions, Zoy-gated) and 20 (alert cooldown tuning, calendar-gated) deferred to v1.5.
- **Older-phase documentation gaps acknowledged** (pre-v1.4): VERIFICATION/UAT artifacts for Phases 11/12/13/16/17/23 — see STATE.md Deferred Items.

### Process Findings

- **Lighter-check audit mode is appropriate for milestones without a formal REQ-ID set.** v1.4 used inline goals in `v1.4-ROADMAP.md` rather than a top-level REQUIREMENTS.md; the 3-source cross-reference machinery was therefore inapplicable. Captured in `.planning/v1.4-MILESTONE-AUDIT.md` (option 2 audit).
- **Phase-26 process miss** — plan template needs a "user-visible surface" check: contract-testing the bridge half is necessary but not sufficient when an OpenMCT allowlist + plugin extension are required for the farmer to see the data. Captured in memory `project_phase26_sht30_happy_path_unverified.md`.

### Archive

- Full roadmap snapshot: `.planning/milestones/v1.4-ROADMAP.md`
- Audit report: `.planning/milestones/v1.4-MILESTONE-AUDIT.md`

---

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
