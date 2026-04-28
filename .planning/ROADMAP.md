# Roadmap: Mushroom Farm — FC-1 Humidity Control (and beyond)

## Milestones

- ✅ **v1.0 MVP — FC-1 Humidity Control** — Phases 1–8 (shipped 2026-04-11)
- ✅ **v1.1 Tech Debt & Connectivity** — Phases 9–10 (shipped 2026-04-12)
- ✅ **v1.2 FarmOS Integration & QoL** — Phases 11–13 (shipped 2026-04-13)
- ✅ **v1.2.1 Hotfix — camera stall + sensor warmup** — Phases 14–16 (shipped 2026-04-18)
- ◆ **v1.3 Alerts & Unified Farmer Dashboard** — Phases 17–20 (17/18 ✓ 2026-04-18/19; 19/20 externally gated, deferred to v1.5)
- ◆ **v1.4 Vision & Growth Insights** — Phases 21–25 (active 2026-04-19) — CV work + farmer↔robot Signal capture channel (Phase 25 added 2026-04-20); demo-able artifacts at every phase

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 1-8) — SHIPPED 2026-04-11</summary>

- [x] Phase 1: Pi Integration & Environment (5/5 plans) — 2026-03-29
- [x] Phase 2: Safety Hardening (4/4 plans) — 2026-03-30
- [x] Phase 3: Closed-Loop Control (3/3 plans) — 2026-04-04
- [x] Phase 4: Observability & Integration (2/2 plans) — 2026-04-04
- [x] Phase 5: Production Deployment (2/2 plans) — 2026-04-11 (grower-attested)
- [x] Phase 6: WireGuard / Tailscale ROS routing (3/3 plans) — 2026-03-29
- [x] Phase 7: Historical Data & OpenMCT time-series (2/2 plans) — 2026-04-07 (regression fixed 2026-04-11)
- [x] Phase 8: Pi Camera Feed in Mission Control (4/4 plans) — 2026-04-09

Grower verdict 2026-04-11: "better than the timer". Unexpected star of the
show: SCD41 CO2 readings (no prior CO2 instrumentation at the farm).

</details>

<details>
<summary>✅ v1.1 Tech Debt & Connectivity (Phases 9-10) — SHIPPED 2026-04-12</summary>

- [x] Phase 9: Connectivity & Boot Stability (4/4 plans) — 2026-04-11
- [x] Phase 10: Bridge QoS & MJPEG Delivery (2/2 plans) — 2026-04-12

Closed all v1.0 carryover tech debt (TDEBT-01/02/03) and established 4G
cellular connectivity (CONN-01). fc-system-sync ships /etc config via git.

</details>

<details>
<summary>✅ v1.2 FarmOS Integration & QoL (Phases 11-13) — SHIPPED 2026-04-13</summary>

- [x] Phase 11: Compose v2 Upgrade (1/1 plans) — 2026-04-13
- [x] Phase 12: Subscriber-Aware Camera (2/2 plans) — 2026-04-13
- [x] Phase 13: FarmOS Daily Report (4/4 plans) — 2026-04-13

Compose v2 on elder-plops, subscriber-aware camera (idle 1/hr, active 1fps),
FarmOS daily report agent (ROS2 lifecycle node, TimescaleDB aggregation,
camera snapshot). Known gaps: FarmOS admin actions pending (permissions,
FC-1 location), Phase 12 hardware UAT pending.

</details>

<details>
<summary>✅ v1.2.1 Hotfix — camera stall + sensor warmup (Phases 14-16) — SHIPPED 2026-04-18</summary>

- [x] Phase 14: fc_camera idle-mode stall hotfix (5/5 plans) — 2026-04-17
- [x] Phase 15: Sensor warm-up grace period (3/3 plans) — 2026-04-17
- [x] Phase 16: System health panel (3/3 plans + 16.1 replay shim) — 2026-04-18

Filed during a farmer debug session; shipped autonomously same-session with
farmer-attested "all green" on 2026-04-18. See `.planning/milestones/v1.2.1-ROADMAP.md`.

</details>

<details open>
<summary>◆ v1.4 Vision & Growth Insights (Phases 21-25) — ACTIVE</summary>

- [x] **Phase 21: Camera history continuous persistence** (4/4 plans) — 2026-04-19
- [x] **Phase 22: Timeline scrubber + farmer story view** (4/4 plans) — 2026-04-19
- [x] **Phase 23: Time-lapse composition (ffmpeg)** — depends on 21 — 2026-04-27 (CO2 overlay gap: open item)
- [ ] **Phase 24: ML vision events via ComfyUI** — depends on 21; pre-gate: ComfyUI-as-prod hardening
- [x] **Phase 25: Bidirectional Signal — farmer↔robot capture channel** — SPEC locked 2026-04-19 (absorbs retired backlog 999.15); independent of 21→24 chain. Farmer-facing UI label: **Field Notes**. See `.planning/phases/25-bidirectional-signal-farmer-robot-capture-channel/25-SPEC.md`. **Shipped 2026-04-28** — 5/5 plans executed, 7/7 farmer UATs PASS (cold-start smoke deferred); deferred items tracked in `25-05-SUMMARY.md` + backlog Phase 999.20.

Full v1.4 narrative + per-phase scope: `.planning/milestones/v1.4-ROADMAP.md`.

</details>

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Pi Integration & Environment | v1.0 | 5/5 | Complete | 2026-03-29 |
| 2. Safety Hardening | v1.0 | 4/4 | Complete | 2026-03-30 |
| 3. Closed-Loop Control | v1.0 | 3/3 | Complete | 2026-04-04 |
| 4. Observability & Integration | v1.0 | 2/2 | Complete | 2026-04-04 |
| 5. Production Deployment | v1.0 | 2/2 | Complete | 2026-04-11 |
| 6. WireGuard / Tailscale ROS routing | v1.0 | 3/3 | Complete | 2026-03-29 |
| 7. Historical Data & OpenMCT time-series | v1.0 | 2/2 | Complete | 2026-04-07 |
| 8. Pi Camera Feed in Mission Control | v1.0 | 4/4 | Complete | 2026-04-09 |
| 9. Connectivity & Boot Stability | v1.1 | 4/4 | Complete | 2026-04-11 |
| 10. Bridge QoS & MJPEG Delivery | v1.1 | 2/2 | Complete | 2026-04-12 |
| 11. Compose v2 Upgrade | v1.2 | 1/1 | Complete | 2026-04-13 |
| 12. Subscriber-Aware Camera | v1.2 | 2/2 | Complete | 2026-04-13 |
| 13. FarmOS Daily Report | v1.2 | 4/4 | Complete    | 2026-04-13 |
| 14. fc_camera idle-mode stall hotfix | v1.2.1 | 5/5 | Complete    | 2026-04-18 |
| 15. Sensor warm-up grace period | v1.2.1 | 3/3 | Complete    | 2026-04-18 |
| 16. System health panel | v1.2.1 | 3/3 | Complete    | 2026-04-18 |
| 17. Alert engine + Signal | v1.3 | 5/5 | Complete (ALRT-07 → 999.15) | 2026-04-18 |
| 18. Farmer dashboard API (UI delegated to farmOS team) | v1.3 | 1/1 | Complete — `/farmer/summary` live on bridge; farmOS UI owned by Zoy-side | 2026-04-19 |
| 19. FarmOS admin actions | v1.3 | — | Deferred to v1.5 — gated on Zoy/farm-team | — |
| 20. Alert cooldown tuning | v1.3 | — | Deferred to v1.5 — calendar-gated | — |
| 21. Camera history continuous persistence | v1.4 | 4/4 | Complete    | 2026-04-19 |
| 22. Timeline scrubber + farmer story view | v1.4 | 4/4 | Complete — data-surface shipped on elder-plops; farmOS owns UI (Zoy-side) | 2026-04-19 |
| 23. Time-lapse composition (ffmpeg) | v1.4 | 3/3 | Complete    | 2026-04-27 |
| 24. ML vision events via ComfyUI | v1.4 | — | Depends on 21; pre-gate: ComfyUI-as-prod hardening | — |
| 25. Bidirectional Signal — farmer↔robot capture channel | v1.4 | 2/5 | Wave 1 complete (25-01 + 25-02) — receive pipe unblocked, capture persistence backbone GREEN. Waves 2–4 pending. | — |

### Phase 23: Time-lapse composition (ffmpeg)

**Goal:** Daily and on-demand time-lapse mp4s generated automatically from Phase 21 snapshots. Full scope in `.planning/milestones/v1.4-ROADMAP.md`.
**Plans:** 3/3 plans complete

Plans:
- [x] 23-01-PLAN.md — Scaffold timelapse package (Dockerfile, package.json, jest) + pure utility modules (overlay, db, config) with full unit tests; Wave 1; D-01/D-06/D-08/D-10/D-11
- [x] 23-02-PLAN.md — Composer pipeline (composeDay + ffmpeg.js spawn wrapper) with DI unit tests covering frame-count guard, atomic rename, ENOENT-tolerance, path-traversal rejection; Wave 2 (depends on 23-01); D-04/D-05/D-07/D-08/D-10/D-11
- [x] 23-03-PLAN.md — HTTP server (/health, /timelapse, /timelapse/status/:id) + node-cron + docker-compose wiring + live deploy + manual smoke compose + farmer visual checkpoint; Wave 3 (depends on 23-01, 23-02); D-01/D-02/D-03/D-08/D-10

### Phase 24: ML vision events via ComfyUI

**Goal:** ComfyUI-backed detection writes pinning + contamination events to Timescale and fires Signal alerts for high-confidence contamination. Full scope in `.planning/milestones/v1.4-ROADMAP.md`.

### Phase 25: Bidirectional Signal — farmer↔robot capture channel

**Goal:** Farmer sends text, audio, and photos via Signal; the robot stores them, transcribes audio locally (Whisper), replies with an LLM-inferred session tag or clarifying question (Anthropic API). Snooze collapses to single "mute 24h" keyword. Absorbs retired backlog 999.15.

**Farmer-facing UI label:** Field Notes.

**SPEC.md location:** `.planning/phases/25-bidirectional-signal-farmer-robot-capture-channel/25-SPEC.md`. GSD workflows use `phase=25`.

**Dependencies:** independent of Phases 21→24 CV chain. Extends Phase 17 alerter. Follow-up phase (farmOS event writer) captured in SEED-002.

**Plans:** 5 plans

Plans:
- [x] 25-01-PLAN.md — Wave 0: signal-cli pipe unblock (MODE=normal flip + primary re-registration of +59891840205 + farmer trust restore + Wave-0 fixtures + RED skeleton tests + smoke script); R1; autonomous: false
- [x] 25-02-PLAN.md — Wave 1: Capture persistence (deps install + config extension + signal.js fetchAttachment + capture-db.js regular table + capture-history.js + capture.js orchestrator); R2,R7
- [x] 25-03-PLAN.md — Wave 2: whisper-transcribe container (CUDA 12.3 + cuDNN 9 Dockerfile + FastAPI lazy-load + V12 path safety + transcribe-client.js + GPU compose + live smoke); R3
- [x] 25-04-PLAN.md — Wave 3: LLM client + sensor snapshot (llm-client.js with locked prompt shape using claude-sonnet-4-6 + 24h history cap + sensor-snapshot.js with timeout + null-on-failure); R5
- [ ] 25-05-PLAN.md — Wave 4: Integration + UAT (snooze grammar extension + receive-loop fast-path + retention cron + state captureHealth + index.js wiring + farmer UAT 1–7); R4,R6,R7; autonomous: false

## Backlog (parking lot)

These are ideas captured during v1.0/v1.1 execution but not yet scoped into a
milestone. Promote with `/gsd:review-backlog` when ready.

- **Phase 999.1: Edge buffering** — local SQLite/Timescale on Pi with store-and-forward to elder-plops for offline resilience.
- **Phase 999.2: FarmOS integration** — bridge into the farm-wide FarmOS instance for mushroom production tracking. Blocked on farm team completing schema design.
- **Phase 999.3: Alerts & notifications** — Signal bot for humidity/CO2/Pi-offline/actuator-stuck conditions. Foundation already in place (bridge `/health`, WebSocket broadcast, DB).
- **Phase 999.4: Environmental expansion — fan & light telemetry** — GPIO27 fan MOSFET + fan/light state publishers + Mission Control charts.
- **Phase 999.5: Vision — time-lapse & growth monitoring** — ffmpeg time-lapse composition, pinning/maturity detection, contamination alerts. Feeds Phase 999.3 for grower-facing pinning and "ready to pick" notifications.
- **Phase 999.6: Multi-chamber scaling** — parameterize chamber_id, enable FC-2/FC-3.
- **Phase 999.7: Farm rover** — mobile inspection/actuation platform (camera + airgun + misting nozzle) on a ROS2 rover. Depends on 999.5, 999.3, 999.6.
- ~~Phase 999.8~~ — **promoted to Phase 15** (v1.2.1 hotfix) 2026-04-17 at farmer's request.
- **Phase 999.9: PID + time-proportional humidity control** — replace bang-bang with a PID loop that outputs a 0–100% duty cycle, translated by the actuator layer into time-proportional on/off windows (HVAC-style slow PWM on the binary SSR mister). **Empirically justified 2026-04-11:** farmer calibration session proved bang-bang + 180s dwell has a structural regulation ceiling of ~±2% RH — dwell forces a +2.0% overshoot under a ±0.5% band, 4× the band width itself. Narrower bands provide no additional regulation benefit under the current control law. Full system-ID data (rise/decay rates, deadtime, step response, nonlinear gain scheduling implications, recommended time-proportional window length and interim operating band) captured in `.planning/phases/999.9-pid-time-proportional-humidity-control/CALIBRATION-FINDINGS-2026-04-11.md` — feedback from the farmer/operator to the dev team. Touches `fc_controller.py` substantially, new actuator duty-cycle primitive, PID tuning params, test suite expansion. Interim band until this ships: `humidity_tolerance: 0.01` (±1%).
- **Phase 999.10: On-demand camera streaming (4G credit thrift)** — `fc_camera` currently publishes `/fc1/camera/compressed` continuously regardless of viewers. At 1 FPS × ~24 KB/frame that's ~2 GB/day of constant cellular traffic, most of it watching nothing. Farmer flagged 2026-04-11 — this will chew through the 4G hotspot credit. Interim workaround applied same day: `camera_fps` lowered from 1.0 → 0.0167 (~1 frame/min, ~35 MB/day), and `camera_fps` default in `fc_camera.py` changed to float to allow sub-1 values. Proper fix: make `fc_camera` subscriber-aware — idle (or drop to a trickle like 1/min) when `count_subscribers('/fc1/camera/compressed') == 0`, ramp to full configured rate when a Mission Control viewer connects. Bridge already owns the MJPEG client set and could hint via a ROS service call. Touches `fc_camera.py` (subscriber polling or service server), possibly `mission_control_bridge` (viewer-state signaling), `fc_config.yaml` (idle-rate param). Not a v1.0 blocker — the YAML workaround holds until 4G budget pressure forces the proper fix.
- **Phase 999.11: Farmer app (operator + grower UI)** — a dedicated app for the farmer's daily workflow: status glance, historical "story view", camera feed, parameter changes, "flag it" backlog capture. Mission Control (OpenMCT) is the engineer surface; the Farmer app is the operator/grower surface. Mobile-first, offline-tolerant over 4G, role-aware (operator vs grower modes). Captured from lived experience during the 2026-04-11 calibration session where Claude Code acted as an ad-hoc farmer app and exposed every gap. **Biggest lesson from that session:** sensor health must be so prominent it is impossible to ignore — today we calibrated against SCD41 humidity for 40 minutes without noticing SHT30 was offline. Full field notes with workflow moments, UI wishes, pitfall reminders, and a 3-item MVP prioritization are in `.planning/phases/999.11-farmer-app/FARMER-APP-NOTES-2026-04-11.md`. Depends on nothing strictly; composes well with 999.3 (alerts/Signal), 999.5 (vision/time-lapse), 999.10 (on-demand camera).
- **Phase 999.13: Upgrade docker-compose v1 → v2** — elder-plops runs compose 1.29.2 which hit a `ContainerConfig` KeyError during v1.1 bridge deploy (2026-04-12), requiring manual `docker rm -f` + recreate. Compose v2 (`docker compose` plugin) fixes this. Container names change from underscores to hyphens (`mushy_bridge_1` → `mushy-bridge-1`) — grep for hardcoded references first. Low risk, high annoyance reduction.
- **Phase 999.14: Camera history — continuous persistence + MC timeline scrubber** — Two issues surfaced during a farmer debug session 2026-04-17 (fc_camera idle-mode stall + discovery that Phase 12's subscriber-aware bridge means idle-pulse frames are never persisted when no one's watching). Original framing ("just index the existing files") was too narrow: indexing a discontinuous history gives a scrubber with blank hours. Real scope: (1) decide who persists idle frames — bridge stays at trickle subscription, or Pi-side history ring buffer, or dedicated archivist subscriber; (2) index in Timescale (`snapshots` table: camera_id, captured_at, file_path, bytes) alongside `saveSnapshot()` (`src/mission-control/bridge/src/index.js:381`); (3) MC timeline scrubber UI. Full findings and scope discussion in `.planning/phases/999.14-index-camera-snapshots-in-timescale/FINDINGS-2026-04-17.md`. Composes with 999.1 (edge-buffering), 999.5 (time-lapse), 999.11 (farmer app story view).
- ~~Phase 999.15~~ — **absorbed into Phase 25** (v1.4) 2026-04-20 after farmer-driven rescope from "unblock snooze receive" into full capture channel (text + audio + images → local Whisper → Anthropic LLM reply). SPEC: `.planning/phases/25-bidirectional-signal-farmer-robot-capture-channel/25-SPEC.md`.
- **Phase 999.16: Mission Control chart downsampling — preserve truth, not averages** — Farmer flagged 2026-04-20: downsampled history charts show misleading values. Most obvious on the Humidifier chart (binary 0/1 state rendering as 0.2/0.4/0.6 stray values), same mechanism visible as noise spikes on RH/temp/CO2. Root cause is almost certainly `avg(value)` in the bridge's Timescale `time_bucket` history query — averaging a bucket that straddles a 0→1 transition produces fractional output, and averaging continuous series smooths real peaks/dips into noise-looking artifacts. Fix direction: for state/boolean series (humidifier, actuator states, sensor_health bits) use `last(value, ts)` or `max(value)` per bucket; for continuous series (RH, temp, CO2) use a min+max pair per bucket (LTTB-style) or simply a finer bucket. **Farmer explicitly OK with a performance hit for a better graph** — downsampling is currently too aggressive and removes useful detail. Touches bridge history endpoint (Timescale query), possibly OpenMCT plugin rendering if two points per bucket need to be drawn as a vertical line. Acceptance: humidifier chart shows only 0 or 1; RH/temp/CO2 detail at typical zoom matches the raw data shape.
- **Phase 999.17: Mission Control overlay plots — multiple series per graph** — Farmer request 2026-04-20 while reviewing the stacked Humidity/Temperature/CO2/Humidifier layout: wants to drop multiple curves into the same plot area instead of one-series-per-panel. Immediate use case is plotting SHT30 temp and SCD41 temp together (Phase 26 delivers `fc1/temperature` + `fc1/temperature_2`) so the farmer can eyeball sensor drift/agreement directly; same for RH once both slots exist. OpenMCT supports overlay plots natively via the Overlay Plot telemetry object — this may be purely a layout/config task (persist a Mission Control workspace with the desired overlays baked in) rather than a code change. Scope questions for planning: (1) one-off manual overlay layout saved into the OpenMCT config, or a programmatically-provisioned default layout; (2) whether bridge telemetry metadata (units, display ranges) needs tweaks so overlaid series share a sensible Y axis; (3) persistence/export of the farmer's chosen overlays so they survive container rebuilds. Composes with 999.16 (cleaner downsampled curves make overlays actually readable) and Phase 26 (dual slot topics are the first real payoff).
- **Phase 999.12: Weather telemetry enrichment** — poll Open-Meteo API from Mission Control side (sidecar container or bridge addition), write outdoor temp/humidity/pressure/precipitation to TimescaleDB, display alongside fc1 chamber data in Mission Control. Proxy for a local weather station until one is installed. Farmer request from first 24h of live data (2026-04-12): correlate outdoor conditions with chamber behavior (e.g. wet day → humidifier never fires, RH stays above 83%). Must NOT run on Pi — runs on elder-plops alongside existing Mission Control stack. Touches: new container or bridge module, TimescaleDB schema for weather table, Mission Control layout. Composes well with 999.11 (farmer app — weather context in "story view").
- **Phase 999.18: Sensor "Last fresh" wall-clock truth** — Surfaced live 2026-04-25 right after Phase 26 alerts started landing: alert says "Last fresh: 5m ago" for SHT30 even though it had been offline for *weeks*. Root cause: the alerter initializes `sht30LastSeenMs = nowMs` at boot (`src/agents/alerter/src/state.js:52-53`), so when the alerter boots into a state where the sensor is already offline, it has no record of when the sensor was actually last alive — it only measures "time since alerter started observing." Two fix shapes scoped during the same session: (a) **alerter-only quick fix** — initialize `*LastSeenMs = null`, drop the "Last fresh:" line when null or say "since alerter boot — true age unknown"; (b) **data-truthful fix (recommended)** — add `sht30_last_fresh_ns` / `scd41_last_fresh_ns` KeyValues to `fc_controller`'s `sensor_health` payload (controller already has `_last_sht30_timestamp`), alerter reads from sensor_health instead of computing locally. Survives alerter restarts; reflects the only process that actually knows the truth. Touches `src/chambers/fc-core/fc_core/fc_controller.py` + `src/agents/alerter/src/state.js` + `message.js` + Pi redeploy. Acceptance: when SHT30 has been offline for >X hours and alerter is freshly booted, the alert message reports a duration ≥ X (not "5m ago").
- **Phase 999.21: Timelapse resolution bump** — Farmer feedback 2026-04-28 after watching the first composed timelapse (`/data/timelapse/fc1/2026-04-27.mp4`, 250 frames, 554 KB): "resolution is a bit low, but other than that it's good." Three knobs to investigate before picking the fix path: (1) `fc_camera.py` capture resolution — the source frames; bumping affects live MC view and 4G credit too. (2) JPEG quality on the per-frame snapshots that ffmpeg consumes. (3) ffmpeg encode settings in the timelapse container (resolution, bitrate, codec). Cheapest fix is probably ffmpeg-side if source frames are already higher than what's being encoded. Composes with 999.10 (subscriber-aware camera lets us bump capture resolution without 4G cost during idle hours).
- **Phase 999.20: Alerter multi-farmer routing + group participation** — Surfaced 2026-04-28 during Phase 25 UAT-6 follow-up. Two related gaps: (a) **Reply routing** — `signalClient.send()` always targets `SIGNAL_RECIPIENT` (farmer #1). Whitelist now accepts farmer #2 (zoy, +59898018597) and farmer #3 (+12019734942) via new `SIGNAL_ADDITIONAL_SENDERS` env (commit pending), but if zoy DMs the bot, the LLM reply lands on farmer #1's phone. Fix: route replies to `envelope.source` (the actual sender) instead of a fixed recipient — touches `src/agents/alerter/src/capture.js:146` and the signal client's `send()` signature. (b) **Group chat participation** — there is a "Mushroom Farm" Signal group where all three farmers coordinate; most farm comms happen there, not in DMs. Bot should be able to listen + reply in that group. signal-cli supports group IDs via `groupId` in the dataMessage. Scope: receive-loop must whitelist the group ID (new env `SIGNAL_GROUP_ID`), reply path must send to the group (`signalClient.sendToGroup()`), and capture rows should record group context (new column `group_id` on `signal_capture` for analytics — distinguish "DM with farmer X" vs "group thread"). Open question: does the bot reply to every group message, only when @mentioned, or only for explicit commands? Default proposal: only commands (`mute`, slash-commands) + when its name is mentioned, to avoid spam. Composes with the deferred-items already logged for Phase 25 (degraded-flag persistence on LLM-failure path, llm_session_tag extraction, multi-envelope context).
- **Phase 999.19: Alert link → real farmer destination** — Surfaced 2026-04-25: alerter `DASHBOARD_URL` linked to `/farmer` on the bridge, but Phase 18 only built `/farmer/summary` (a JSON API for farmOS to consume) — no HTML page at `/farmer` ever existed. Farmer tapped the link from Signal and got "Cannot GET /farmer." Patched same session by repointing to OpenMCT (`http://100.96.10.66:8080/`) which is reachable on the tailnet and shows live dashboards, but per `project_phase18_22_farmos_proxy_architecture` the long-term farmer destination is the farmOS "story view" (Zoy-side, page path TBD). Decision needed when farmOS story view is ready: switch DASHBOARD_URL to that page so the alert link lands on the farmer-friendly UI, not the operator-facing OpenMCT. Trivial config change — `src/agents/alerter/src/config.js` + `docker-compose.override.yml`. Acceptance: tapping the alert link from the farmer's phone lands on the farmer dashboard (whatever its final URL), not OpenMCT.

### Phase 26: Dual sensor publishing + offline alarms — SHT30/SCD41 slot topics + Signal alerts

**Goal:** SHT30 and SCD41 publish on separate slot topics (slot 1 silent-fallback per D-01; slot 2 SCD41-only per D-02), and Signal alerts fire when either physical sensor goes silent for ≥5 min (D-04/D-05) with symmetric recovery messages (D-06). Closes the 2026-04-11 incident class where a 40-min unnoticed SHT30 outage cost a calibration session.
**Requirements**: D-01..D-06 (CONTEXT.md decisions used as the de-facto requirement set; no formal REQ-IDs assigned)
**Depends on:** Phase 25
**Plans:** 3 plans

Plans:
- [ ] 26-01-PLAN.md — Pi-side dual publishers + freshness (fc_sensors.py refactor, fc_controller.py sensor_health KeyValue extension, pytest test_sensors.py); Wave 1; D-01/D-02/D-03
- [ ] 26-02-PLAN.md — Bridge slot-2 forwarding (VOLATILE-QoS subs for fc1/temperature_2 & fc1/humidity_2 → WS broadcast + TimescaleDB); Wave 2 (depends on 26-01); D-02/D-03
- [ ] 26-03-PLAN.md — Alerter sht30/scd41 alert types + snooze grammar + ALERT_SENSOR_OFFLINE_MIN env (state.js, rules.js, index.js, message.js, snooze.js, config.js, jest tests, docker-compose.override.yml); Wave 2 (depends on 26-01); D-04/D-05/D-06

---
*Roadmap created 2026-03-28. v1.2.1 shipped 2026-04-18.*
