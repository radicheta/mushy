# Mushroom Farm MVP: Humidity Control on FC-1

## What This Is

A closed-loop humidity control system for fruiting chamber 1 (FC-1) running on Raspberry Pi, replacing the current timer-based solution with active sensor feedback and actuator control. Integrates with the existing ROS2 system and is production-ready for single-chamber operation.

## Core Value

**A working, production-ready humidity control loop that's better than the current timer solution and ready to ship to growers.**

> **Current State (2026-06-14): v1.11 SHIPPED** — Extraction prereqs + 2025-paper backfill
> (Phases 53/54/54.1/55/55B). The 2025-notebook backfill pipeline is end-to-end with a
> commit-time CSV fidelity cross-check whose live re-smoke caught the 2026-06-07 POY-as-KOY
> silent misattribution. Full 73-page corpus run stays parked (Phase-55/GA2, Cycle-2 farmer
> sign-off). Next: v1.12 Farm-Agent Python port. Detail: `.planning/milestones/v1.11-ROADMAP.md`.
> NOTE: the per-milestone sections below this point are stale (last full review 2026-05-03,
> pre-v1.7) and pending a dedicated PROJECT.md reconciliation alongside the REQUIREMENTS.md drift.

## Current Milestone: v1.12 Farm-Agent Python Port

**Goal:** Rewrite the live ~16k-LOC JS alerter/extraction stack (`src/agents/alerter/`) as a Python stack — Signal I/O, multimodal extractor, draft state machine, and farmOS commit path — validated against the live corpus and cut over in a single switch, with clean Foray-ready module seams.

**Target features:**
- Python Signal I/O layer (signal-cli send/receive, envelope routing, quote threading) — folds in the Phase-50 wire-level quote-rendering bugs deferred from v1.9
- Python multimodal extractor (audio+image+text fusion → schema-aware draft with per-field provenance; confidence + ask-back)
- Python draft state machine + commit path (idempotent upsert-by-stable-identity; v1.11 fidelity hard gate preserved)
- Python farmOS write client (asset/log creates + patches, field-scoped image route, retries)
- Pre-cutover parity/validation gate against the live corpus (Node-vs-Python output match before flip)
- Foray-ready module seams + tenant primitive (separable units so SEED-010 carve-out is near-free later)

**Strategy decisions (locked 2026-06-14 with Santi):**
- **Big-bang rewrite** — build full Python stack, validate against corpus, single prod cutover (no dual-stack period).
- **Port + opportunistic cleanup** — fold in the Phase-50 quote-rendering bugs and fix obvious wrongs as encountered; not strict 1:1 parity.
- **Foray-ready seams** — clean module boundaries + tenant primitive for the eventual Apache-2.0 Foray extraction.

**Key context / constraints:**
- The Node alerter is LIVE in prod (Signal alerts + draft commits). A pre-cutover parity/validation gate against the live corpus is mandatory ([[feedback_unit_tests_dont_catch_wiring]], [[feedback_real_data_before_ship_gate_pass]]).
- `src/farmos-agent/` is already Python — reference, not re-port.
- Must not regress the v1.11 fidelity hard gate (commit-time CSV cross-check) or v1.10 upsert-by-stable-identity guarantees.
- Shared-Timescale prod-leak hazard ([[project_backfill_confirmed_drafts_leak_to_prod_via_live_watchdog]]) applies to any shadow/validation runs.

**Out of scope (carry):**
- The full Foray repo extraction itself (separate milestone; this only sets up the seams)
- v1.13 auto-commit narrowing (depends on v1.11 confirm corpus)
- The 2 open 55B follow-ons (receipt dup false-positive, D-03 image-on-session) unless trivially folded in
- `fc_core` / Mission Control / camera / VPS hub (stay Node/ROS; only the alerter slice ports)

## Requirements

### Validated

Existing codebase provides:

- ✓ ROS2 Jazzy node framework for fruiting chamber control
- ✓ Docker containerization and orchestration
- ✓ I2C humidity/temperature sensing (SHT30 on 0x44 originally, with documented SCD41 fallback on 0x62 when SHT30 is absent — currently in fallback mode)
- ✓ OpenMCT Mission Control bridge (Node.js, historical + live)
- ✓ Configuration system (fc_config.yaml)
- ✓ GPIO and hardware abstraction layer

### Validated in Phase 01 (Hardware & Environment)

- ✓ Humidity/temperature sensor reading on FC-1 (SHT30 on I2C 0x44 when plugged, SCD41 on 0x62 as documented fallback — currently fallback)
- ✓ Publish sensor data to ROS topics `fc1/humidity` and `fc1/temperature`
- ✓ Humidifier actuator via MOSFET on GPIO27 with pull-down for safe-default-OFF
- ✓ Deploy pipeline: `scripts/pi-deploy/deploy.sh` fast-forwards `fc1/prod` on the Pi's `~/mushroom_farm_ws/mushy-repo/` checkout, runs colcon build, restarts `fc-core.service`. `fc-update.service` systemd oneshot also pulls `fc1/prod` on every boot.
- ✓ Live telemetry visible on Mission Control dashboard

### Validated in Phase 02 (Safety Hardening)

- ✓ Non-blocking sensor error handling (SENS-03)
- ✓ Config cleaned up for I2C sensors + MOSFET hardware (SENS-04)
- ✓ Rolling median spike rejection in humidity_callback (SENS-05)
- ✓ Humidifier GPIO pin configurable from fc_config.yaml (ACTR-02)
- ✓ Test assertions fixed and passing (TEST-01)

### Validated in Phase 03 (Closed-Loop Control)

- ✓ Closed-loop bang-bang control with hysteresis (CTRL-01)
- ✓ Configurable setpoint, deadband, dwell time, staleness timeout (CTRL-02)
- ✓ Minimum dwell time guard prevents rapid actuator cycling (CTRL-03)
- ✓ Stale sensor data detection triggers safe state (CTRL-04)
- ✓ Sensor failure drives humidifier OFF, not frozen last state (CTRL-05)

### Validated in Phase 04 (Observability & Integration)

- ✓ Actuator state published on `fc1/actuators/humidifier` with TRANSIENT_LOCAL QoS (ACTR-03) — bridge now also subscribes with TRANSIENT_LOCAL QoS (fixed in Phase 10, TDEBT-01)
- ✓ Humidifier GPIO activates/deactivates via control loop on FC-1 (ACTR-01)
- ✓ Humidity published correctly on `fc1/humidity` in 0.0–1.0 range (SENS-02)
- ✓ Mission Control dashboard extended with CO2 and humidifier state charts (D-04, D-05)
- ✓ SCD41 CO2 sensor integrated, publishing on `fc1/co2`
- ✓ Full soak test — Pi ran continuously for ~24h on current boot and ~5 days across the deploy window (TEST-02, DEPL-01 verified 2026-04-11)

### Validated in v1.1 (Tech Debt & Connectivity)

- ✓ Bridge QoS aligned — humidifier subscription TRANSIENT_LOCAL, last-state replays on bridge restart (TDEBT-01) — v1.1
- ✓ Phantom CycloneDDS peer eliminated — repo config synced to Tailscale, LeaseDuration 5s guard (TDEBT-02) — v1.1
- ✓ fc-core cold boot clean — ExecStartPre polls tailscale0, NRestarts=0 confirmed at farm (TDEBT-03) — v1.1
- ✓ 4G cellular connectivity — fc1 on mossrock-lab MiFi, ROS-over-cellular via Tailscale, dual-location verified (CONN-01) — v1.1
- ✓ fc-system-sync early-boot service — git-shipped /etc config with netplan + wpa_cli reload, future wifi changes via `git push fc1/prod` — v1.1

### Validated in v1.2.1 (Hotfix — camera stall + sensor warmup)

- ✓ fc_camera idle-stall fix — 1 Hz graph-poll on `count_subscribers('/fc1/camera/compressed')`; canonical stall recovery in 9s (HFIX-01..05) — v1.2.1
- ✓ Sensor warm-up grace period — fc_controller early-returns for first 20s post-boot; `/fc1/sensor_health` WARN→OK (SENS-01) — v1.2.1
- ✓ System health panel — six-light strip in Mission Control (Sensors, Camera feed, Humidifier, Bridge, Pi reachable, Grace) via `makeStatusLight` primitive — v1.2.1
- ✓ Replay shim for sensor_health on new WS connect (Phase 16.1) — v1.2.1

### Current State

**v1.0 MVP shipped 2026-04-11.** Grower attested "better than the timer".
**v1.1 Tech Debt & Connectivity shipped 2026-04-12.** All carryover tech debt
closed; fc1 reliably reachable over 4G cellular.
**v1.2 FarmOS Integration & QoL shipped 2026-04-13.** Compose v2 on elder-plops,
subscriber-aware camera, FarmOS daily report (`farmos_agent`).
**v1.2.1 Hotfix shipped 2026-04-18.** Camera idle-stall fix (9s recovery),
sensor warm-up grace, six-light system health panel.
**v1.3 Alerts & Unified Farmer Dashboard shipped 2026-04-19.** Phases 17 (Signal
alerter) + 18 (`/farmer/summary` JSON for farmOS). Phases 19/20 deferred (Zoy/
calendar gates).
**v1.4 Vision & Growth Insights shipped 2026-05-01.** Continuous camera
persistence (Phase 21), timeline scrubber data surface (Phase 22), nightly
time-lapse composition (Phase 23), bidirectional Signal "Field Notes" capture
channel with local Whisper + Anthropic LLM reply (Phase 25), dual-sensor
SHT30/SCD41 slot topics + offline alarms (Phase 26). Phase 24 (ML vision)
deferred behind backlog 999.26 (camera-coverage prerequisite).
**v1.5.0.1 Resilience hotfix shipped 2026-05-07.** Phase 27.1 edge buffering
(fc_buffer + bridge replay-poller) live over the new wg0 kernel-WG transport;
Phase 27.2 fc-core systemd hardening (cold-reboot SYS-04 scenario 1 PASS, 41s).
27.3 + 27.4 mooted by the transport switch. BUF-04 + SYS-04 scenario 2 deferred
to backlog (999.36, 999.28). See `.planning/milestones/v1.5.0.1-ROADMAP.md`.
See `.planning/MILESTONES.md`.

## Current State: v1.6 SHIPPED 2026-05-10/11 — VPS hub + outage/recovery stack

Phase 32 (VPS WireGuard hub) + Phase 33 (heartbeat receiver + Signal Tier 1) + Phase 999.43.1 (ntfy Tier 2) + Phase 34 (uptime-kuma outside-in) + Phase 35 (age-encrypted Tier A backup) all live. Milestone scaffolding deferred (Phase 32 ran ahead); retroactive snapshot at `.planning/milestones/v1.6-ROADMAP.md`. Companion 2026-05-11 backlog sweep closed 10 items.

**v1.5 archives:**
- `.planning/milestones/v1.5-ROADMAP.md` / `v1.5-REQUIREMENTS.md`
- `.planning/v1.5-MILESTONE-AUDIT.md` (status: tech_debt — no critical blockers)

## Queued Milestone: v1.9 Inoc-Session Correctness (scaffolded 2026-05-22, planning deferred until v1.8 ships)

**Goal:** Make the canonical multi-parent inoc session work end-to-end — capture → extract → confirm → commit → surface — using the 2026-05-22 paper-log session as the live ship gate.

**Why now:** May 22 exposed that Phase 38's "95.8% schema conformance" eval set didn't include the most common inoc shape: N children from M>1 parents in one session. 10 of 11 bags fell on the floor on the live session. This is *the* canonical shape at the farm ([[project_inoc_shape_multi_parent_batch]]), not an edge case.

**Target features:**
- Multi-source extraction fusion (audio+image+text → one draft with per-field provenance; flag conflicts)
- Groups-shape inoc draft (`{groups: [{parent, species, qty, child_block_names[]}]}`)
- B5-compliant block-name minting (SEQ per-session, sourced from paper-log photo per 2026-05-22 clarification note in farmos repo `8daea5b`)
- Session-as-entity (anonymous `fungi` asset; secondary parent on each child block)
- Per-bag commit fan-out (N seeding logs + 1 session asset, idempotent)
- Session-shaped confirm preview (compact group table; farmer compares to notebook/shelf)
- Real-session eval corpus (≥3 sessions; May 22 as named regression guard)

**Schema source-of-truth (locked):**
- `/mnt/slime-kingdom/shared/farmos/.planning/notes/2026-05-11-session-chat.md` (B1–B7 + C1–C5 lock)
- `/mnt/slime-kingdom/shared/farmos/.planning/notes/2026-05-22-b5-seq-clarification.md` (B5 SEQ disambiguation)

**Ship gate:** Santi forwards May 22 audio+photo → pipeline emits 11 correctly-named blocks (`260522_SHI_1..3`, `260522_KOY_4..11`) with right parents and a session asset → farmer YES → all 11 logs land in farmOS dev → lineage walks return clean.

**Out of scope (deferred):**
- Harvest-session shape (same structural concern; gets its own milestone)
- Multi-session-per-day SEQ disambiguation (defer until it happens; flagged in clarification note)
- Phase 45 (NORTH-STAR commit_failed ack) — that's v1.8; here the relaxed-for-Santi posture holds ([[feedback_hard_rules_relaxed_when_farmer_is_santi]])
- Phase 42 SHI-on-sawdust full lifecycle pilot (still calendar-deferred)
- QR scan binding flow (locked schema's v1.0 path; multimodal-only is the v1.6+ commitment)

**Sequencing:** Phase planning starts only after v1.8 (Phases 44 + 45) ships. Scaffolding-only now to make the shape concrete and zoy-side-visible.

---

## Prior Milestone Frame: v1.7 Multimodal Signal → FarmOS Events (superseded — kept for context)

**Goal:** Ship the multimodal extraction pipeline (photo + voice + text → LLM → farmOS event writes) that exercises and validates the 2026-05-11 schema lock, ending with one SHI-on-sawdust block driven end-to-end through farmOS by Signal alone.

**Why now:** the farmOS schema (C1–C5 conventions + B1–B7 mushroom-specifics + P1–P5 SHI-pilot scope) was locked 2026-05-11 by a joint session with Zoy (farmos repo `d4e5a30`). Pilot scope P3 explicitly names the multimodal pipeline as the validation driver — so this milestone exercises and validates the schema in one stroke. Closes the "long-arc" UX vision behind Phase 25 (SEED-006): the farmer's freeform Signal stream becomes their entire farmOS interface; no bookkeeping tax.

**Target features:**
- Schema-aware LLM extraction (JSON-mode against locked contracts; confidence + ask-back)
- Farmer-in-the-loop confirmation (YES/NO/EDIT idempotent commit)
- FarmOS write path (auth, retries, idempotency; asset creates + log creates per B7)
- Multi-source ingestion (synthetic + historical paper logs + audio recordings per P3)
- Multi-farmer routing (999.20 — reply to envelope.source; group-thread participation)
- SHI-on-sawdust pilot end-to-end (sterilize → archive_spent per P4)
- Signal pre-gate: signal-cli primary re-registration (unblock deviceId=2)

**Schema source-of-truth (read before planning):**
- `/mnt/slime-kingdom/shared/farmos/.planning/notes/2026-05-09-fungi-schema-strawman.md`
- `/mnt/slime-kingdom/shared/farmos/.planning/notes/2026-05-11-session-chat.md`

**Out of scope (deferred / carry):**
- ML vision (contamination, pin emergence) — needs 999.26 camera coverage first
- farmOS UI / admin (Zoy side)
- Multi-chamber expansion (999.6)

**v1.6 carries (slot opportunistically if free):**
- MC active-experiment widget (bridge already broadcasts; UI gap from Phase 31)
- Schedule gap-mode default param (D-08 side-finding from Phase 30)
- 999.19 alert link → farmOS story view
- ALRT-10 cooldown tuning (calendar gate ≥2 weeks alerter data, likely satisfied)
- Operator id_ed25519 SPOF (Phase 35 deferred — encrypts critical backup)

<details>
<summary>Previous milestone goals (v1.5 frame)</summary>

## Parent Milestone Frame: v1.5 — Analog Humidity Control & Condensation/Evaporation Forcing

**Goal:** Replace bang-bang humidifier control with PID + time-proportional
duty cycle, exposed to the farmer as named modes (`fruiting`, `pinning`) with
experimental `force-condensation` / `force-evaporation` override modes for
forcing experiments. Closes the structural ±2% RH ceiling proven empirically
2026-04-11 and unifies three previously-independent backlog pains (999.9 PID,
999.22 alerter source-of-truth, 999.23 dynamic target) into one coherent
mode primitive.

**Target features:**
- PID + time-proportional duty cycle on the existing relay (slow-PWM)
- Mode primitive: named bundles of `(target_RH, band, duty-cycle behavior)`
- Two baseline modes: `fruiting`, `pinning`; manual switch via ROS service / farmer app
- Runtime config delivery infrastructure (SEED-001 absorbed) — modes change without redeploy
- Alerter reads current mode from controller (closes 999.22)
- Time-of-day mode scheduling (closes 999.23)
- Experimental modes for condensation / evaporation forcing (timed, auto-revert)
- Carry from v1.3: alert cooldown tuning (Phase 20)

**Calibration data already on disk:**
`.planning/phases/999.9-pid-time-proportional-humidity-control/CALIBRATION-FINDINGS-2026-04-11.md`

**Carry deferred to v1.6:** Phase 19 (FarmOS admin actions, Zoy-gated).

</details>

### Out of Scope

- Temperature control — no actuator in v1 scope; revisit when hardware changes
- CO2-triggered ventilation — routed to `/gsd:explore` for v2.0 themes
- Multi-chamber scaling / FC-2 — single-chamber until v2.0+
- PID humidity control — bang-bang with ±1% band is the interim; 999.9 has calibration data
- SHT30 physical reinstall — SCD41 fallback works; sensor redundancy is nice-to-have
- OpenMCT UI enhancements — Mission Control functional; farmer app (999.11) is the next UI surface

## Context

**Current State:**
- v1.0 shipped 2026-04-11 (Phases 01–08). v1.1 shipped 2026-04-12 (Phases 09–10).
- fc-core running continuously on fc1 Pi at the farm over 4G cellular (mossrock-lab MiFi)
- Bang-bang humidity control with ±1% RH operating band, 180s dwell, SCD41 as active sensor
- Mission Control (OpenMCT) stack on elder-plops: bridge + TimescaleDB + camera feed
- Bridge QoS aligned, CycloneDDS config synced to Tailscale, no phantom peers
- fc-system-sync ships /etc config via git — wifi/systemd changes need only `git push fc1/prod`
- Camera at 1 frame/min (4G credit conservation workaround; proper fix is 999.10)
- SHT30 physically disconnected — SCD41 on 0x62 is the sole humidity/temp/CO2 source

**Hardware Setup:**
- Fruiting chamber 1 (FC-1) with Raspberry Pi 4 (Ubuntu 24.04 aarch64)
- SHT30 humidity/temperature sensor on I2C 0x44 (physically disconnected as of 2026-04-11 — fc_sensors falls back to SCD41 for humidity when SHT30 is absent)
- SCD41 CO2/temp/humidity sensor on I2C 0x62 (currently the active humidity source)
- MOSFET for humidifier control on GPIO27 with pull-down resistor
- USB webcam at /dev/video0 (640x480 @ 1fps)
- No dedicated temperature or ventilation actuator in v1 scope

**Production Pressure:**
- Current solution: timer-based humidification (no feedback)
- Need: alternative control method ready for production use
- Goal: ship improved solution even if not feature-complete
- Flexibility: can defer non-MVP features without blocking release

**Development Environment:**
- ROS2 Jazzy with colcon build system
- Python-based nodes
- Simulation mode available for testing without hardware
- Existing test framework and patterns in codebase

## Constraints

- **Hardware**: Single chamber (FC-1 only) for MVP — multi-chamber deferred
- **Timeline**: Production-driven (ASAP) — acceptable to ship incomplete features if core loop works
- **Dependencies**: Must integrate with existing ROS2 system, not fork/replace
- **Reliability**: Must be stable enough for grower operation (better than timer)
- **Compatibility**: Runs on Raspberry Pi with existing GPIO and sensor setup

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Single-chamber MVP (FC-1 only) | Keep scope manageable for quick delivery; multi-chamber scaling is separate concern | ✓ Good — shipped in 14 days |
| Use existing ROS infrastructure | Avoid reinventing; integrate with proven system | ✓ Good — CycloneDDS over Tailscale works well |
| SSR-10A for humidifier (not MOSFET) | Switches 220V AC zapatilla; MOSFET freed for fan | ✓ Good — reliable, GPIO17 |
| Bang-bang with dwell guard | Better than timer; PID deferred to 999.9 | ⚠️ Revisit — ±2% RH structural ceiling; PID needed for tighter control |
| Tailscale over WireGuard | Simpler mesh, survives farm connectivity instability | ✓ Good — 4G cutover was seamless |
| fc-system-sync git-ops deploy | Ship /etc config via git, no SSH needed for wifi/systemd changes | ✓ Good — v1.1 pattern; proven on 4G cutover |
| SCD41 as primary sensor (SHT30 fallback offline) | SCD41 provides humidity + CO2; SHT30 physically disconnected | ⚠️ Revisit — single sensor SPOF, but CO2 is high-value |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (e.g., after Phase 1 completes):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After this milestone completes:**
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid? (especially Temp/CO2 control timing)
4. Update Context with production learnings

---

*Last updated: 2026-06-14 — v1.12 Farm-Agent Python Port milestone opened (Current Milestone section added; v1.7 frame demoted; full section reconciliation still pending)*
