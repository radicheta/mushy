# Roadmap: Mushroom Farm — FC-1 Humidity Control (and beyond)

## Milestones

- ✅ **v1.0 MVP — FC-1 Humidity Control** — Phases 1–8 (shipped 2026-04-11). See `.planning/milestones/v1.0-ROADMAP.md` for full details.
- 🔧 **v1.1 Tech Debt & Connectivity** — Phases 9–10 (active). Closes v1.0 carryover bugs and establishes reliable farm connectivity.

## Phases

- [ ] **Phase 09: Connectivity & Boot Stability** - 4G hotspot for reliable farm access; fc-core.service cold-boot fix
- [ ] **Phase 10: Bridge QoS & MJPEG Delivery** - Humidifier last-state replay on bridge restart; live MJPEG stream free of phantom-peer stalls

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

Tech debt carried to v1.1: ACTR-03 bridge QoS, CAM-03 phantom CycloneDDS
subscriber, fc-core boot race on tailscale0 interface, SHT30 physical
reinstall. See `.planning/milestones/v1.0-MILESTONE-AUDIT.md`.

</details>

## Phase Details

### Phase 09: Connectivity & Boot Stability
**Goal**: fc1 Pi is reliably reachable from elder-plops at the farm via 4G hotspot, and fc-core.service starts cleanly on every cold boot without restart loops
**Depends on**: Nothing (first v1.1 phase; also unblocks Phase 10 verification)
**Requirements**: CONN-01, TDEBT-03
**Success Criteria** (what must be TRUE):
  1. `ros2 topic echo /fc1/humidity` on elder-plops returns a reading within 5 seconds after the Pi's WAN connection is via 4G hotspot
  2. Pi recovers and Tailscale mesh reconnects automatically after a simulated WAN blip (hotspot toggled off then on), without manual intervention on either host
  3. `journalctl -u fc-core.service` on a fresh Pi cold boot shows zero automatic restarts — service reaches `active (running)` state on the first attempt
  4. Mission Control dashboard (elder-plops browser) is reachable and shows live telemetry within 30 seconds of the Pi completing boot at the farm
**Plans**: 3 plans
Plans:
- [x] 09-01-PLAN.md — Systemd boot race fix (TDEBT-03): add tailscaled ordering + ExecStartPre poll to fc-core.service, deploy to fc1/prod
- [x] 09-02-PLAN.md — 4G WAN path bring-up (CONN-01): associate Pi wlan0 with MiFi, verify Tailscale over cellular, WAN-blip test, runbook doc
- [x] 09-03-PLAN.md — Physical verification (CONN-01 + TDEBT-03): cold-boot plug-pull, dual-location ROS test, Mission Control 30s criterion, write 09-VERIFICATION.md

### Phase 10: Bridge QoS & MJPEG Delivery
**Goal**: Mission Control accurately replays the last humidifier state on bridge restart, and the live camera feed delivers continuous frames without phantom-peer stalls
**Depends on**: Phase 09 (Pi must be reachable to verify MJPEG and DDS delivery end-to-end)
**Requirements**: TDEBT-01, TDEBT-02
**Success Criteria** (what must be TRUE):
  1. Restarting the bridge container (`docker compose restart bridge`) causes the Mission Control humidifier-state chart to immediately show the correct last-known state — no blank gap or stale pre-restart value
  2. The `/camera/mjpeg` endpoint delivers a continuous stream (visible frame updates every ~1 second) for at least 60 seconds without stalling during normal operation
  3. `journalctl -u fc-core.service` on the Pi shows no repeated write-retry or peer-unreachable log lines referencing `192.168.1.193` after the CycloneDDS peer cleanup is deployed
**Plans**: TBD
**UI hint**: yes

## Progress Table

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 09. Connectivity & Boot Stability | 4/4 | Complete    | 2026-04-11 |
| 10. Bridge QoS & MJPEG Delivery | 0/? | Not started | - |

## Backlog (parking lot)

These are ideas captured during v1.0 execution but not yet scoped into a
milestone. Promote with `/gsd:review-backlog` when ready.

- **Phase 999.1: Edge buffering** — local SQLite/Timescale on Pi with store-and-forward to elder-plops for offline resilience.
- **Phase 999.2: FarmOS integration** — bridge into the farm-wide FarmOS instance for mushroom production tracking. Blocked on farm team completing schema design.
- **Phase 999.3: Alerts & notifications** — Signal bot for humidity/CO2/Pi-offline/actuator-stuck conditions. Foundation already in place (bridge `/health`, WebSocket broadcast, DB).
- **Phase 999.4: Environmental expansion — fan & light telemetry** — GPIO27 fan MOSFET + fan/light state publishers + Mission Control charts.
- **Phase 999.5: Vision — time-lapse & growth monitoring** — ffmpeg time-lapse composition, pinning/maturity detection, contamination alerts. Feeds Phase 999.3 for grower-facing pinning and "ready to pick" notifications.
- **Phase 999.6: Multi-chamber scaling** — parameterize chamber_id, enable FC-2/FC-3.
- **Phase 999.7: Farm rover** — mobile inspection/actuation platform (camera + airgun + misting nozzle) on a ROS2 rover. Depends on 999.5, 999.3, 999.6.
- **Phase 999.8: Sensor warm-up grace period** — delay bang-bang actuator control at fc-core startup until sensors stabilize. Observed 2026-04-11 (farmer calibration session): every restart produces a ~30s spike on first sensor read (e.g. 18.7°C/77.2% → 21.8°C/64.4% → settled 21.4°C/66%). Contaminates tick-gain/bounce measurements and can trigger unwanted humidifier ON that gets dwell-locked for 3min. Suggested: `control_loop` early-return until `_humidity_buffer` is full AND ≥20s wall-clock elapsed since boot; new `startup_grace_period` param. Touches `fc_controller.py`, `fc_config.yaml`, `test_controller.py`. Not a v1.0 blocker — workaround is "ignore first minute after restart".
- **Phase 999.11: Farmer app (operator + grower UI)** — a dedicated app for the farmer's daily workflow: status glance, historical "story view", camera feed, parameter changes, "flag it" backlog capture. Mission Control (OpenMCT) is the engineer surface; the Farmer app is the operator/grower surface. Mobile-first, offline-tolerant over 4G, role-aware (operator vs grower modes). Captured from lived experience during the 2026-04-11 calibration session where Claude Code acted as an ad-hoc farmer app and exposed every gap. **Biggest lesson from that session:** sensor health must be so prominent it is impossible to ignore — today we calibrated against SCD41 humidity for 40 minutes without noticing SHT30 was offline. Full field notes with workflow moments, UI wishes, pitfall reminders, and a 3-item MVP prioritization are in `.planning/phases/999.11-farmer-app/FARMER-APP-NOTES-2026-04-11.md`. Depends on nothing strictly; composes well with 999.3 (alerts/Signal), 999.5 (vision/time-lapse), 999.10 (on-demand camera).
- **Phase 999.10: On-demand camera streaming (4G credit thrift)** — `fc_camera` currently publishes `/fc1/camera/compressed` continuously regardless of viewers. At 1 FPS × ~24 KB/frame that's ~2 GB/day of constant cellular traffic, most of it watching nothing. Farmer flagged 2026-04-11 — this will chew through the 4G hotspot credit. Interim workaround applied same day: `camera_fps` lowered from 1.0 → 0.0167 (~1 frame/min, ~35 MB/day), and `camera_fps` default in `fc_camera.py` changed to float to allow sub-1 values. Proper fix: make `fc_camera` subscriber-aware — idle (or drop to a trickle like 1/min) when `count_subscribers('/fc1/camera/compressed') == 0`, ramp to full configured rate when a Mission Control viewer connects. Bridge already owns the MJPEG client set and could hint via a ROS service call. Touches `fc_camera.py` (subscriber polling or service server), possibly `mission_control_bridge` (viewer-state signaling), `fc_config.yaml` (idle-rate param). Not a v1.0 blocker — the YAML workaround holds until 4G budget pressure forces the proper fix.
- **Phase 999.9: PID + time-proportional humidity control** — replace bang-bang with a PID loop that outputs a 0–100% duty cycle, translated by the actuator layer into time-proportional on/off windows (HVAC-style slow PWM on the binary SSR mister). **Empirically justified 2026-04-11:** farmer calibration session proved bang-bang + 180s dwell has a structural regulation ceiling of ~±2% RH — dwell forces a +2.0% overshoot under a ±0.5% band, 4× the band width itself. Narrower bands provide no additional regulation benefit under the current control law. Full system-ID data (rise/decay rates, deadtime, step response, nonlinear gain scheduling implications, recommended time-proportional window length and interim operating band) captured in `.planning/phases/999.9-pid-time-proportional-humidity-control/CALIBRATION-FINDINGS-2026-04-11.md` — feedback from the farmer/operator to the dev team. Touches `fc_controller.py` substantially, new actuator duty-cycle primitive, PID tuning params, test suite expansion. Interim band until this ships: `humidity_tolerance: 0.01` (±1%).

---
*Roadmap created 2026-03-28. v1.1 phases added 2026-04-11.*
