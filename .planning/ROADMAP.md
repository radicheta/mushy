# Roadmap: Mushroom Farm — FC-1 Humidity Control (and beyond)

## Milestones

- ✅ **v1.0 MVP — FC-1 Humidity Control** — Phases 1–8 (shipped 2026-04-11)
- ✅ **v1.1 Tech Debt & Connectivity** — Phases 9–10 (shipped 2026-04-12)
- 🚧 **v1.2 FarmOS Integration & QoL** — Phases 11–13 (in progress)

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

### 🚧 v1.2 FarmOS Integration & QoL (In Progress)

**Milestone Goal:** Connect chamber telemetry to FarmOS as the farm's system of record; add subscriber-aware camera streaming to stop bleeding 4G credit; upgrade elder-plops to compose v2.

- [x] **Phase 11: Compose v2 Upgrade** — Replace docker-compose v1 with compose v2 plugin on elder-plops; verify all services and fix any hardcoded container name references (completed 2026-04-13)
- [ ] **Phase 12: Subscriber-Aware Camera** — fc_camera idles at trickle rate when no Mission Control viewers are connected; ramps to configured FPS when subscribers appear
- [ ] **Phase 13: FarmOS Daily Report** — FC-1 asset provisioned in FarmOS; daily camera snapshot and environment summary (humidity, CO2, temp, duty cycle) posted as an observation log entry

## Phase Details

### Phase 11: Compose v2 Upgrade
**Goal**: elder-plops runs the compose v2 plugin and the full Mission Control stack is healthy under it
**Depends on**: Nothing (independent infrastructure task)
**Requirements**: INFRA-01, INFRA-02, INFRA-03
**Success Criteria** (what must be TRUE):
  1. `docker compose version` prints a v2.x version on elder-plops; the old `docker-compose` v1 binary is no longer the active tool
  2. `docker compose up -d` starts bridge, openmct, and timescale without errors and all containers reach healthy/running state
  3. Live telemetry flows end-to-end: Mission Control shows current fc1 humidity, CO2, and humidifier state after a fresh `up -d`
  4. No hardcoded container names break — any scripts or bridge code that referenced v1 underscore names (`mushy_bridge_1`) are updated to v2 hyphen names or made name-independent
**Plans:** 1/1 plans complete
Plans:
- [x] 11-01-PLAN.md — Install compose v2, recreate stack, update docs with v2 names/commands

### Phase 12: Subscriber-Aware Camera
**Goal**: fc_camera conserves 4G bandwidth by idling when no viewers are watching; Mission Control gets full-rate feed the moment someone connects
**Depends on**: Nothing (self-contained fc_camera.py change)
**Requirements**: CAM-01, CAM-02, CAM-03
**Success Criteria** (what must be TRUE):
  1. When no subscriber is connected to `/fc1/camera/compressed`, fc_camera publishes at idle rate (1 frame/min or less) — verifiable by watching topic frequency with `ros2 topic hz`
  2. When Mission Control bridge connects as a subscriber, fc_camera automatically ramps up to the configured active FPS without any manual intervention
  3. When Mission Control is closed and the subscriber disconnects, fc_camera drops back to idle rate automatically
  4. The MJPEG stream in Mission Control is smooth and uninterrupted during the active period — no visible gap or stutter at the moment of rate transition
**Plans**: TBD
**UI hint**: yes

### Phase 13: FarmOS Daily Report
**Goal**: FC-1 exists as an asset in FarmOS and receives a daily observation log containing a camera snapshot and environment summary
**Depends on**: Phase 12 (daily snapshot uses fc_camera; idle-rate trickle provides the scheduled capture)
**Requirements**: FMOS-01, FMOS-02, FMOS-03
**Success Criteria** (what must be TRUE):
  1. FC-1 appears as a structure asset in FarmOS (port 8082 on elder-plops) with correct name, location, and metadata — visible in the FarmOS UI
  2. Once per day a new observation log entry appears on the FC-1 asset containing an attached camera snapshot image from that day
  3. The same observation entry includes a text summary with avg/min/max humidity, CO2, and temperature for the day plus humidifier duty cycle and any anomaly flags — all values drawn from TimescaleDB
  4. The daily report service runs on elder-plops (not the Pi) and survives a service restart without creating duplicate entries for the same day
**Plans**: TBD

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
| 11. Compose v2 Upgrade | v1.2 | 1/1 | Complete    | 2026-04-13 |
| 12. Subscriber-Aware Camera | v1.2 | 0/? | Not started | - |
| 13. FarmOS Daily Report | v1.2 | 0/? | Not started | - |

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
- **Phase 999.8: Sensor warm-up grace period** — delay bang-bang actuator control at fc-core startup until sensors stabilize. Observed 2026-04-11 (farmer calibration session): every restart produces a ~30s spike on first sensor read (e.g. 18.7°C/77.2% → 21.8°C/64.4% → settled 21.4°C/66%). Contaminates tick-gain/bounce measurements and can trigger unwanted humidifier ON that gets dwell-locked for 3min. Suggested: `control_loop` early-return until `_humidity_buffer` is full AND ≥20s wall-clock elapsed since boot; new `startup_grace_period` param. Touches `fc_controller.py`, `fc_config.yaml`, `test_controller.py`. Not a v1.0 blocker — workaround is "ignore first minute after restart".
- **Phase 999.9: PID + time-proportional humidity control** — replace bang-bang with a PID loop that outputs a 0–100% duty cycle, translated by the actuator layer into time-proportional on/off windows (HVAC-style slow PWM on the binary SSR mister). **Empirically justified 2026-04-11:** farmer calibration session proved bang-bang + 180s dwell has a structural regulation ceiling of ~±2% RH — dwell forces a +2.0% overshoot under a ±0.5% band, 4× the band width itself. Narrower bands provide no additional regulation benefit under the current control law. Full system-ID data (rise/decay rates, deadtime, step response, nonlinear gain scheduling implications, recommended time-proportional window length and interim operating band) captured in `.planning/phases/999.9-pid-time-proportional-humidity-control/CALIBRATION-FINDINGS-2026-04-11.md` — feedback from the farmer/operator to the dev team. Touches `fc_controller.py` substantially, new actuator duty-cycle primitive, PID tuning params, test suite expansion. Interim band until this ships: `humidity_tolerance: 0.01` (±1%).
- **Phase 999.10: On-demand camera streaming (4G credit thrift)** — resolved in Phase 12.
- **Phase 999.11: Farmer app (operator + grower UI)** — a dedicated app for the farmer's daily workflow: status glance, historical "story view", camera feed, parameter changes, "flag it" backlog capture. Mission Control (OpenMCT) is the engineer surface; the Farmer app is the operator/grower surface. Mobile-first, offline-tolerant over 4G, role-aware (operator vs grower modes). Captured from lived experience during the 2026-04-11 calibration session where Claude Code acted as an ad-hoc farmer app and exposed every gap. **Biggest lesson from that session:** sensor health must be so prominent it is impossible to ignore — today we calibrated against SCD41 humidity for 40 minutes without noticing SHT30 was offline. Full field notes with workflow moments, UI wishes, pitfall reminders, and a 3-item MVP prioritization are in `.planning/phases/999.11-farmer-app/FARMER-APP-NOTES-2026-04-11.md`. Depends on nothing strictly; composes well with 999.3 (alerts/Signal), 999.5 (vision/time-lapse), 999.10 (on-demand camera).
- **Phase 999.12: Weather telemetry enrichment** — poll Open-Meteo API from Mission Control side (sidecar container or bridge addition), write outdoor temp/humidity/pressure/precipitation to TimescaleDB, display alongside fc1 chamber data in Mission Control. Proxy for a local weather station until one is installed. Farmer request from first 24h of live data (2026-04-12): correlate outdoor conditions with chamber behavior (e.g. wet day → humidifier never fires, RH stays above 83%). Must NOT run on Pi — runs on elder-plops alongside existing Mission Control stack. Touches: new container or bridge module, TimescaleDB schema for weather table, Mission Control layout. Composes well with 999.11 (farmer app — weather context in "story view").
- **Phase 999.13: Upgrade docker-compose v1 → v2** — resolved in Phase 11.

---
*Roadmap created 2026-03-28. v1.1 shipped 2026-04-12. v1.2 roadmap added 2026-04-12.*
