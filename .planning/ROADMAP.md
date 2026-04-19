# Roadmap: Mushroom Farm — FC-1 Humidity Control (and beyond)

## Milestones

- ✅ **v1.0 MVP — FC-1 Humidity Control** — Phases 1–8 (shipped 2026-04-11)
- ✅ **v1.1 Tech Debt & Connectivity** — Phases 9–10 (shipped 2026-04-12)
- ✅ **v1.2 FarmOS Integration & QoL** — Phases 11–13 (shipped 2026-04-13)
- ✅ **v1.2.1 Hotfix — camera stall + sensor warmup** — Phases 14–16 (shipped 2026-04-18)

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
| 19. FarmOS admin actions | v1.3 | — | Gated on Zoy/farm-team (FC-1 asset + farmos_agent perms) | — |
| 20. Alert cooldown tuning | v1.3 | — | Gated on 17 live ≥1 week | — |

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
- **Phase 999.15: signal-cli receive-side for linked secondary device** — alerter's snooze receive loop is blocked on `bbernhard/signal-cli-rest-api:0.200-dev` returning HTTP 400 on `/v1/receive` for linked accounts (discovered 2026-04-18 during Phase 17 farmer UAT). Receive-loop and snooze grammar code are complete and pass 10 unit tests against the fake server — only the real API endpoint is non-functional in linked-device mode. Resolution paths: (a) re-provision the alerter as a **primary** Signal account on a dedicated SIM (full captcha/SMS/PIN flow — messy, see `project_signal_cli_link_gotchas.md`), or (b) upgrade signal-cli-rest-api to a version that supports `/v1/receive` for linked accounts. Farmer can already send snooze commands from their phone; they just don't reach the state machine yet. Low priority — alerter ships core PROBLEM/RECOVERY/HEARTBEAT value without it.
- **Phase 999.12: Weather telemetry enrichment** — poll Open-Meteo API from Mission Control side (sidecar container or bridge addition), write outdoor temp/humidity/pressure/precipitation to TimescaleDB, display alongside fc1 chamber data in Mission Control. Proxy for a local weather station until one is installed. Farmer request from first 24h of live data (2026-04-12): correlate outdoor conditions with chamber behavior (e.g. wet day → humidifier never fires, RH stays above 83%). Must NOT run on Pi — runs on elder-plops alongside existing Mission Control stack. Touches: new container or bridge module, TimescaleDB schema for weather table, Mission Control layout. Composes well with 999.11 (farmer app — weather context in "story view").

---
*Roadmap created 2026-03-28. v1.2.1 shipped 2026-04-18.*
