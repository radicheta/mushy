# Roadmap: Mushroom Farm — FC-1 Humidity Control (and beyond)

## Milestones

- ✅ **v1.0 MVP — FC-1 Humidity Control** — Phases 1–8 (shipped 2026-04-11)
- ✅ **v1.1 Tech Debt & Connectivity** — Phases 9–10 (shipped 2026-04-12)
- ✅ **v1.2 FarmOS Integration & QoL** — Phases 11–13 (shipped 2026-04-13)
- ✅ **v1.2.1 Hotfix — camera stall + sensor warmup** — Phases 14–16 (shipped 2026-04-18)
- ✅ **v1.3 Alerts & Unified Farmer Dashboard** — Phases 17–18 (shipped 2026-04-19; Phases 19/20 externally gated → v1.5)
- ✅ **v1.4 Vision & Growth Insights** — Phases 21–26 (shipped 2026-05-01; Phase 24 deferred behind backlog 999.26 camera coverage)
- ⏸ **v1.5 Analog Humidity Control & Condensation/Evaporation Forcing** — Phases 27–31 (Phase 27 shipped 2026-05-02; PAUSED behind v1.5.0.1 hotfix); promotes backlog 999.9 + absorbs 999.22/999.23 + SEED-001; carries Phase 20 alert cooldown tuning from v1.3
- ◆ **v1.5.0.1 Resilience hotfix from 2026-05-02 incident** — Phases 27.1–27.4 (active 2026-05-02); promotes backlog 999.1 + 999.28 + 999.30 + repo netplan drift cleanup; pattern matches v1.2.1

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

<details>
<summary>✅ v1.4 Vision & Growth Insights (Phases 21-26) — SHIPPED 2026-05-01</summary>

- [x] Phase 21: Camera history continuous persistence (4/4 plans) — 2026-04-19
- [x] Phase 22: Timeline scrubber + farmer story view (4/4 plans) — 2026-04-19
- [x] Phase 23: Time-lapse composition (ffmpeg) (3/3 plans) — 2026-04-27
- [ ] Phase 24: ML vision events via ComfyUI — **DEFERRED 2026-05-01** behind backlog 999.26 (camera coverage)
- [x] Phase 25: Bidirectional Signal — farmer↔robot capture channel (5/5 plans) — 2026-04-28 (7/7 farmer UATs PASS)
- [x] Phase 26: Dual sensor publishing + offline alarms — SHT30/SCD41 (3/3 plans) — 2026-04-29 (UAT-8 PASS)

CV pipeline foundation, bidirectional Signal "Field Notes" channel, dual-sensor visibility. SCD41 RH known to clip at 100% — SHT30 is RH source of truth. Phase 24 (ML vision) explicitly deferred behind camera coverage prereq. See `.planning/milestones/v1.4-ROADMAP.md`.

</details>

<details open>
<summary>◆ v1.5.0.1 Resilience hotfix from 2026-05-02 incident (Phases 27.1-27.4) — ACTIVE</summary>

- [ ] **Phase 27.1: Edge buffering — fc1 telemetry replay-on-reconnect (Wave 3 carryover)** — Wave 1+2 already on `main` (commits `ad44a36..e8d15d0` 2026-05-02); this phase closes Wave 3: deploy fc_buffer + bridge replay poller, induced 5-min Tailscale dropout soak, farmer attestation. Promotes 999.1; BUF-01..04
- [ ] **Phase 27.2: fc-core systemd unit hardening — survive blackout/boot races** — `ExecStartPre` waits for tailscale0 IPv4 (not just link); apply `Restart=always` + wider `StartLimitInterval/Burst` per existing systemd lesson; audit `After=tailscaled.service`. Promotes 999.28; SYS-01..04
- [ ] **Phase 27.3: Telemetry sampling-rate reduction** — `sensor_read_interval` 2.0s → 10.0s (decoupled from `control_interval`); update alerter `sensor_stale_timeout` to ≥2× new cadence. Cuts tailscaled CPU 5× under bad DERP. Promotes 999.30; SAMP-01..03
- [ ] **Phase 27.4: Repo netplan drift reconciliation** — align repo to fc1's currently-running clean state (drop mossrock-west on wlan0, remove 99-static.yaml, disable cloud-init network regen) + add `eth0 dhcp4` stanza so wired path to 4G router actually works. NET-01..03

Hotfix shape (2026-05-02 evening): the 2026-05-02 blackout + DERP-relay incident exposed three resilience gaps (telemetry lost forever during dropouts, fc-core stuck dead 55 min after a boot race, tailscaled saturated under bad DERP) plus a repo/runtime drift on netplan. Pattern matches v1.2.1: small focused hotfix milestone, shipped as a coherent unit before resuming v1.5 main. Out of scope: 999.29 (max-continuous-on cap redesign — needs mister hardware soak first; operational risk already covered by `ad949c6` PWM cap raise on `fc1/prod`).

</details>

<details>
<summary>⏸ v1.5 Analog Humidity Control & Condensation/Evaporation Forcing (Phases 27-31) — PAUSED behind v1.5.0.1 hotfix</summary>

- [x] **Phase 27: PID + time-proportional duty-cycle primitive** — shipped 2026-05-02; HUMID-01..04
- [ ] **Phase 28: Mode primitive + 2 baseline modes (`fruiting`, `pinning`) + runtime config delivery** — incorporates SEED-001 (modes change without redeploy); MODE-01..05
- [ ] **Phase 29: Alerter mode awareness + cooldown tuning** — alerter reads target/band from controller; sweep other env-hidden knobs; closes 999.22; carries Phase 20; ALRT-08..10
- [ ] **Phase 30: Time-of-day mode scheduling** — declarative schedule, scheduler issues mode switches at window boundaries; closes 999.23; SCHED-01..03
- [ ] **Phase 31: Experimental forcing modes (`force-condensation`, `force-evaporation`)** — timed, auto-revert, with TimescaleDB experiment logging; EXPT-01..03

PID-first shape (locked 2026-05-01 with farmer): farmer wants condensation/evaporation experiments soon and they're achievable as a side-effect of the early phases. Calibration findings already on disk: `.planning/phases/999.9-pid-time-proportional-humidity-control/CALIBRATION-FINDINGS-2026-04-11.md`. Modes are kept thin in v1.5 — 2 hardcoded YAML modes; richer mode-editor UI is v1.6. Resumes after v1.5.0.1 ships.

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
| 26. Dual sensor publishing + offline alarms (SHT30/SCD41) | v1.4 | 3/3 | Complete — UAT-8 PASS 2026-04-29 (farmer-eyeballed slot-1/slot-2 overlay, SCD41 clipping confirmed) | 2026-04-29 |
| 27. PID + time-proportional duty-cycle primitive | v1.5 | 5/5 | Complete    | 2026-05-02 |
| 27.1. Edge buffering — fc1 telemetry replay-on-reconnect (Wave 3) | v1.5.0.1 | 3/4 | Wave 1+2 on main (8 commits ad44a36..e8d15d0); Wave 3 = deploy + soak + attest | — |
| 27.2. fc-core systemd unit hardening | v1.5.0.1 | 0/? | Not started | — |
| 27.3. Telemetry sampling-rate reduction | v1.5.0.1 | 0/? | Not started | — |
| 27.4. Repo netplan drift reconciliation | v1.5.0.1 | 0/? | Not started | — |
| 999.1. Edge buffering | backlog | — | Promoted to Phase 27.1 (v1.5.0.1) on 2026-05-02 | — |
| 28. Mode primitive + baselines + runtime config delivery | v1.5 | 0/? | Paused behind v1.5.0.1 | — |
| 29. Alerter mode awareness + cooldown tuning | v1.5 | 0/? | Paused behind v1.5.0.1 | — |
| 30. Time-of-day mode scheduling | v1.5 | 0/? | Paused behind v1.5.0.1 | — |
| 31. Experimental forcing modes (condensation/evaporation) | v1.5 | 0/? | Paused behind v1.5.0.1 | — |

### Phase 27: PID + time-proportional duty-cycle primitive

**Goal:** Replace bang-bang humidifier control with a PID loop that emits a 0.0–1.0 duty cycle on `fc1/actuators/humidifier_duty`, driven onto the existing SSR via a slow-PWM actuator (120s window, 10s min ON pulse) plus a "Mode C" full-ON bypass when far from setpoint. Closes the structural ±2% RH ceiling proven 2026-04-11. Acceptance: ±0.5% RH over a 2h farmer-attested soak (HUMID-04). Ships the primitive only — Phase 28 wraps it in named modes.

**Requirements:** HUMID-01, HUMID-02, HUMID-03, HUMID-04.

**CONTEXT.md:** `.planning/phases/27-pid-time-proportional-duty-cycle-primitive/27-CONTEXT.md`. GSD workflows use `phase=27`.

**Dependencies:** independent of v1.4. Builds on Phase 03 safety contracts, Phase 15 grace, Phase 16 sensor_health, Phase 26 slot-1 fallback. Calibration foundation in `.planning/phases/999.9-pid-time-proportional-humidity-control/CALIBRATION-FINDINGS-2026-04-11.md`.

**Plans:** 5/5 plans complete

Plans:
- [x] 27-01-PLAN.md — Wave 0: vendor simple-pid, scaffold RED tests, sweep min_dwell_time, add new pid_*/pwm_* params to fc_config.yaml
- [x] 27-02-PLAN.md — Wave 1: implement fc_pwm_driver node (slow-PWM windowing + GPIO27 ownership) + setup.py + fc.launch.py wiring
- [x] 27-03-PLAN.md — Wave 2: refactor fc_controller.py — strip bang-bang/dwell/GPIO, add PID + Mode C + ramp + bumpless transfer
- [x] 27-04-PLAN.md — Wave 3: bridge subscription on fc1/actuators/humidifier_duty (TRANSIENT_LOCAL, no rescale)
- [x] 27-05-PLAN.md — Wave 4: deploy to fc1/prod + rebuild bridge + 2-hour HUMID-04 farmer-attested soak

### Phase 27.1: Edge buffering — fc1 telemetry replay-on-reconnect (Wave 3 carryover)

**Goal:** Close the visibility-during-Tailscale-dropout gap proven by the 2026-05-02 incident (~2h cumulative blackout where PID held the chamber but Mission Control had no idea what it was doing). Wave 1+2 already on `main` (commits `ad44a36..e8d15d0`, 8 commits, fc_buffer node + bridge replay poller GREEN); this phase ships Wave 3: deploy fc1 via `git push fc1/prod` + `deploy.sh`, rebuild bridge with `--build`, induce a 5-min Tailscale dropout, attest farmer.

**Requirements:** BUF-01, BUF-02, BUF-03, BUF-04. Acceptance = induced 5-min Tailscale dropout (`sudo tailscale down` on fc1, wait, `sudo tailscale up`) fills the OpenMCT humidity chart within ~60s of reconnect with original timestamps; no false-fire on alerter; sensor-health "last fresh" not poisoned by backfilled rows.

**CONTEXT.md:** `.planning/phases/999.1-edge-buffering-local-telemetry-storage-on-pi-with-store-and-/999.1-CONTEXT.md` (preserved from backlog promotion). GSD workflows use `phase=27.1` (resolves to the same dir; rename if the resolver requires).

**Dependencies:** None within v1.5.0.1 (independent of 27.2/27.3/27.4 — composes naturally with 27.3 since less raw traffic per buffered minute = longer effective retention in same SQLite size).

**Plans:** 4 plans (3 already executed on `main`)

Plans:
- [x] 999.1-01-PLAN.md — Wave 1: pre-flight Timescale dedupe + idempotent UNIQUE (topic, time) migration in initDb() + shared config/buffered_topics.yaml manifest
- [x] 999.1-02-PLAN.md — Wave 2: implement fc_buffer ROS node (sqlite WAL + http.server on 100.96.239.75:8765 + 24h pruner) + setup.py entry_point + fc.launch.py wiring + systemd /var/lib/fc-core dir setup
- [x] 999.1-03-PLAN.md — Wave 2: bridge buffer_replay.js (30s poll, 15s timeout, ON CONFLICT DO NOTHING) + insertTelemetry timestamp refactor + msg.header.stamp on live RH/T paths + last_ingested_ns persistence to host volume
- [ ] 999.1-04-PLAN.md — Wave 3: deploy fc1 via git push fc1/prod + deploy.sh + rebuild bridge with --build + induce 5-min Tailscale dropout soak + farmer attestation

### Phase 27.2: fc-core systemd unit hardening — survive blackout/boot races

**Goal:** Make fc-core's systemd unit survive the boot-time race the 2026-05-02 farm power outage exposed: tailscale0 link came up before acquiring an IPv4, fc-core's `ExecStartPre` only checked link presence, all 5 ROS nodes failed `rcl_create_node`, `ros2 launch` exited 0 (the known systemd trap), 5 retries in ~10s tripped `start-limit-hit`, service stayed dead 55min until manual `reset-failed && start`. Farmer-visible: "fc never came back after black out."

**Requirements:** SYS-01, SYS-02, SYS-03, SYS-04. Acceptance = stop tailscaled and reboot the Pi; fc-core waits and comes up green without manual intervention.

**CONTEXT.md:** `.planning/phases/27.2-fc-core-systemd-unit-hardening/27.2-CONTEXT.md` (to be created in plan-phase).

**Dependencies:** Independent. Same family as 27.1 (outages should leave control intact and visibility recoverable, not require human intervention) and as 999.25 (fc-core init race — sister boot-time fragility on fc1).

**Plans:** TBD (defined during `/gsd-plan-phase 27.2`)

### Phase 27.3: Telemetry sampling-rate reduction

**Goal:** Cut the per-second packet volume across the Tailscale → DERP → elder-plops path 5× by raising `sensor_read_interval` from 2.0s (0.5Hz) to 10.0s (0.1Hz). Keep `control_interval` fast — Phase 27 PID tuning was done at the existing control cadence; slowing the control loop changes discrete-time dynamics, slowing only the publish cadence does not (verify via `fc_sensors.py`/`fc_controller.py` decoupling read during plan-phase). Should drop tailscaled from 240% CPU under bad DERP back below saturation.

**Requirements:** SAMP-01, SAMP-02, SAMP-03. Acceptance = before/after tailscaled CPU + load-avg measurement on fc1 when poked from elder-plops; chamber RH chart still readable in Mission Control with 5× coarser samples; alerter does not false-fire "sensor stale" with the new `sensor_stale_timeout`.

**CONTEXT.md:** `.planning/phases/27.3-telemetry-sampling-rate-reduction/27.3-CONTEXT.md` (to be created).

**Dependencies:** Plan AFTER 27.1 ships (cleaner before/after measurement once buffering is live; also so SAMP-02 can pick alerter timeouts knowing replay behavior). Composes with 27.1 (longer effective buffer retention), 27.2 (same family of "make fc1 robust against bad uplink").

**Plans:** TBD (defined during `/gsd-plan-phase 27.3`)

### Phase 27.4: Repo netplan drift reconciliation

**Goal:** Reconcile the repo's tracked netplan with fc1's currently-running clean state, and add a wired ethernet path that today does nothing because the repo has no `ethernets:` block. Tonight's manual edits on fc1 (mossrock-west dropped from `wlan0`, `99-static.yaml` deleted, cloud-init network regen disabled via `99-disable-network-config.cfg`) are not in the repo — fc-system-sync would clobber them on next push.

**Requirements:** NET-01, NET-02, NET-03. Acceptance = repo netplan matches fc1's currently-running state, fc-system-sync applies cleanly without breaking the live uplink, and a cable plugged into the 4G router's LAN port DHCPs and routes ROS as a redundant uplink alongside wlan0.

**CONTEXT.md:** `.planning/phases/27.4-repo-netplan-drift-reconciliation/27.4-CONTEXT.md` (to be created).

**Dependencies:** Plan AFTER 27.2 ships — once fc-core boot is no longer a coin flip, validating netplan changes via reboot is safe again.

**Plans:** TBD (defined during `/gsd-plan-phase 27.4`)

## Backlog (parking lot)

These are ideas captured during v1.0/v1.1 execution but not yet scoped into a
milestone. Promote with `/gsd:review-backlog` when ready.

- **Phase 999.1: Edge buffering — fc1-side ring buffer + replay on reconnect** — **PRIORITY BUMP 2026-05-02 (evening):** today's blackout-recovery session lost hours of telemetry forever — multiple multi-minute DERP-relay outages plus the 14:29→15:25 fc-core start-limit-hit window plus the wifi reassociation gap. With Phase 27 high-resolution PID telemetry, every dropout is a permanent hole in data we'd want for tuning, alerting, and post-mortem. The chamber controlled itself fine; we just have no idea what it actually did during ~2 hours of cumulative blackouts today. Wave 1+2 of the phase are already executed (commits `ad44a36..e8d15d0` on main, 8 commits, fc_buffer node + bridge replay poller GREEN); Wave 3 (deploy + soak + farmer attestation) is next. **Treat as the next thing to ship.** Original local SQLite/JSONL on fc1 captures all `fc.*` topics; on bridge reconnect, fc1 replays buffered points with original timestamps so Mission Control gets gap-fill instead of holes. **Earlier motivation 2026-05-02 morning:** ~13-min Tailscale dropout 00:19→00:32 UTC (PID held RH at 94.0±0.04% the whole time — control was unaffected, only visibility was lost). **Scope sketch:** (1) lightweight on-Pi store (sqlite or jsonl with size cap) for all `fc.*` topics keyed by `(topic, ts_ns)`; (2) bridge connection state observer on fc1 — when bridge reconnects, replay un-acked points oldest-first; (3) idempotent ingest on bridge/Timescale side (Timescale already accepts out-of-order inserts cleanly, `(topic, time)` key dedupes). **Compose with:** 999.27 (derived telemetry node — both touch the fc1 telemetry layer; sequence so derived metrics also get buffered), 999.25 (init race — buffer should survive fc-core restarts), 999.18 (true "last fresh" — replayed points should not poison sensor-health timestamps), 999.30 (sampling-rate reduction — composes naturally; less raw traffic per buffered minute = longer retention in same buffer size).
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
- **Phase 999.22: BUG — Alerter ops thresholds must read from a single farmer-tunable source, not env** — Surfaced 2026-04-28 across two farmer interactions in one session. **(1) RH target/band:** farmer changed `target_humidity` 0.90→0.94 + `humidity_tolerance` 0.01→0.015 via `ros2 param set` on `/fc_controller`. Controller picked it up live, but the alerter kept firing OOB pages against its own copy (`ALERT_RH_TARGET=90`, `ALERT_RH_BAND=3`). **(2) Pi/sensor offline thresholds:** farmer flagged that ~5min outages on a known-spotty 4G link aren't worth a page — wants ≥10min before alerting. Fixed downstream by bumping `ALERT_PI_OFFLINE_MIN=10` and `ALERT_SENSOR_OFFLINE_MIN=10` in `.env` and recreating alerter, but same anti-pattern: the farmer-tunable knob lives in elder-plops env, not in a farmer-facing surface. Same root cause: every farmer-meaningful threshold (RH target, RH band, pi offline min, sensor offline min — and likely future temp band, humidifier-stuck threshold, etc.) currently lives as alerter env duplicated from or independent of the controller, requiring `.env` + container recreate to tweak. Farmer (correctly) called this out — syncing env each time is the wrong solution. **Fix direction:** alerter reads ops thresholds from a single source per knob: RH target/band from `/fc_controller` ROS params (which farmer already tweaks live); offline minutes from controller params too OR a dedicated `farmos`/runtime config surface that the farmer app + alerter both consume. Two shapes for delivery: (a) subscribe to a ROS param-broadcast topic the controller publishes (cleanest for controller-owned params, requires controller-side work); (b) alerter polls the bridge for current values via a small endpoint (`/api/fc1/ops_config` covering all alerter-relevant knobs) — the bridge already speaks ROS. Touches `src/agents/alerter/src/config.js` (drop static env-fed thresholds, fetch dynamically), `src/agents/alerter/src/rules.js`/`message.js` (re-evaluate per-tick instead of capture-at-boot), possibly `src/mission-control/bridge/src/index.js` (new endpoint or ws message type), and the controller (expose offline-min knobs as ROS params if we go route-(a)). **Interim state on elder-plops `.env`:** `ALERT_RH_TARGET=94`, `ALERT_RH_BAND=3`, `ALERT_PI_OFFLINE_MIN=10`, `ALERT_SENSOR_OFFLINE_MIN=10` — keep these in sync with the live controller until the fix lands. **Acceptance:** any farmer-meaningful threshold change (RH target via `ros2 param set`, future farmer-app slider, etc.) is reflected in the alerter's next evaluation cycle with no container/env/restart action. **Composes with 999.23** — the dynamic-target work means the alerter's "current target" will change *over time within a single grow* (ramps, scheduled day/night cycles, fruiting-stage transitions), so reading-from-controller isn't an optimization, it's a correctness requirement. Whatever fix shape lands here should expose the *current effective values at evaluation time*, not a static-at-boot snapshot. **Sweep when fixing:** `src/agents/alerter/src/config.js` for any other farmer-meaningful knobs hiding in env (heartbeat hour, humidifier-stuck threshold, RH OOB grace, etc.) — pull them all to the same surface in one go.
- **Phase 999.23: Dynamic RH target — schedules, ramps, stage-aware setpoints** — Farmer flagged 2026-04-28: the current single scalar `target_humidity` is fine for today but won't hold up. Real grows want (a) **scheduled modes** (e.g. "fruiting" 95% RH day / 90% night, "pinning" 98% for first 48h then taper, "incubation" 80% baseline), (b) **animated ramps** between setpoints instead of step changes (smooth transitions over minutes/hours so the bang-bang controller doesn't slam), and (c) **stage-aware presets** triggered by farmer action ("flag spawn-run start" → switch profile) or by elapsed time inside a stage. Groundwork lessons to apply *now* so we don't re-architect later: (1) the canonical target should be a *function of time* `target_humidity(t)`, not a constant — even today's static value should pass through that function (constant profile). (2) anything reading the target (alerter 999.22, farmer dashboard, history charts as a reference line, future PID 999.9) must read the *current effective value*, not a config snapshot. (3) keep schedule definition declarative (YAML/JSON profile per chamber per stage) — don't bake mode logic into the controller's Python. (4) profile changes should be a single farmer action (Signal command, farmer-app button, farmOS stage transition), not a redeploy. **Composes with:** 999.9 (PID — proper ramp tracking needs a non-bang-bang loop), 999.22 (alerter must already be reading from controller, not env, before targets start moving), 999.11 (farmer app — schedule editor UI), 999.16 (history charts should overlay the *moving* target line, not a flat one), Phase 26 (dual-sensor selection per stage — e.g. trust SCD41 RH during fruiting, SHT30 during incubation). **Acceptance (groundwork milestone, not full delivery):** controller exposes `current_target_humidity` and `current_humidity_band` as runtime-evolving params/topics; default profile is the existing constant; alerter + dashboards consume the current value; no more than one new abstraction in the controller (a `TargetProfile` strategy interface), keep the YAML for static-target users untouched.
- **Phase 999.24: fc_camera VideoCapture re-open on cap.read() failure** — Surfaced 2026-04-29: snapshots chip went red after ~24h of zero captures. Root cause was fc_camera spamming `cap.read() failed, skipping frame` continuously since Apr 28 ~13:09 UTC with no recovery — the loop in `fc_camera.py:152-155` just logs warn + returns; never releases or re-opens the `cv2.VideoCapture` handle. USB camera was still enumerated (`/dev/video0` present, `lsusb` showed Microdia 0c45:636b) so a `systemctl restart fc-core` recovered it cleanly — confirms the fix shape is software-only re-open, not hardware reseat. Memory's "Phase 12 9s recovery" covered a *different* stall mode (idle/inactive timer, not cap.read). **Fix:** after N consecutive cap.read() failures (say 5 — i.e. 5 sec at active fps), `cap.release()` + reconstruct `cv2.VideoCapture(device)`, re-apply width/height/buffer settings; if reopen fails, exponential backoff retry. Don't swallow indefinite failure — emit a `sensor_health` KeyValue (`camera_fresh: false`) once the stall exceeds a threshold so the alerter (Phase 999.18-shape) can page. Acceptance: yank+replug the USB cam at the chamber → fc_camera resumes publishing within 30s without a service restart; snapshots chip stays green. Touches `src/chambers/fc-core/fc_core/fc_camera.py` + a small unit test that mocks `cap.read()` returning False and asserts re-open is attempted. Composes with 999.18 (true-age tracking — alerter should know "camera last fresh: X mins ago" not "since alerter boot").
- **Phase 999.25: fc-core CycloneDDS-over-Tailscale init race at startup** — Surfaced during 2026-04-29 sensor-offline-alarm investigation. Journalctl shows the `rmw_create_node: failed to create domain, error Error` cluster (e.g. Apr 27 18:52 + 19:24 UTC) where all four nodes (`fc_sensors`, `fc_controller`, `fc_display`, `fc_camera`) exit 1 in lockstep, plus periodic `Sensor data stale — humidifier OFF for safety` events when `fc_sensors` alone dies and the controller stays up but goes stale (Apr 24 ~03:43, Apr 28 ~06:42). 7-day rate is roughly 2–3 brief outages/week, each ~1 minute downtime under the new `Restart=always` (which is masking, not fixing). Almost certainly a startup ordering race: fc-core boots before `tailscale0` + `cyclonedds-tailscale.xml`'s peer endpoints are reachable, so `rmw_create_node` fails on the first DDS domain join. The systemd unit (`fc-core.service`) currently has `Restart=always` + a hard 20s `startup_grace_period` in the controller, but no `After=` / `Wants=` / `ExecStartPre=` gate on Tailscale or DDS readiness. Each crash → sensors stale → alerter pages (now ≥10 min, but still pages on a real long outage). **Fix direction:** (a) `After=tailscaled.service` + `Wants=tailscaled.service` on `fc-core.service` so systemd serialises the dependency. (b) `ExecStartPre=/usr/bin/tailscale status --self=true --peers=false` (or a small wait-for-peer script) that polls until the Tailscale data-plane is up. (c) consider giving CycloneDDS a longer `peer.discovery_timeout` for the cold-boot case. (d) emit a `fc_init_failed` boot counter to `sensor_health` so we can graph crash frequency post-fix. Touches `scripts/pi-deploy/systemd/fc-core.service` (the Pi-deployed unit; remember `feedback_diff_repo_vs_pi_systemd` — the live unit may have drifted), possibly a small `scripts/pi-deploy/wait-for-tailscale.sh` helper. Acceptance: zero `rmw_create_node: failed to create domain` events over 14 consecutive days post-deploy; sensor-stale events <1/week (i.e. only real network/i2c hiccups, not init races). Composes with 999.18 (alerter "Last fresh" should make crash-vs-network distinguishable from the farmer's perspective).
- **Phase 999.19: Alert link → real farmer destination** — Surfaced 2026-04-25: alerter `DASHBOARD_URL` linked to `/farmer` on the bridge, but Phase 18 only built `/farmer/summary` (a JSON API for farmOS to consume) — no HTML page at `/farmer` ever existed. Farmer tapped the link from Signal and got "Cannot GET /farmer." Patched same session by repointing to OpenMCT (`http://100.96.10.66:8080/`) which is reachable on the tailnet and shows live dashboards, but per `project_phase18_22_farmos_proxy_architecture` the long-term farmer destination is the farmOS "story view" (Zoy-side, page path TBD). Decision needed when farmOS story view is ready: switch DASHBOARD_URL to that page so the alert link lands on the farmer-friendly UI, not the operator-facing OpenMCT. Trivial config change — `src/agents/alerter/src/config.js` + `docker-compose.override.yml`. Acceptance: tapping the alert link from the farmer's phone lands on the farmer dashboard (whatever its final URL), not OpenMCT.
- **Phase 999.27: Derived telemetry channel — bridge-side `fc_metrics` module** — Surfaced 2026-05-01 during Phase 27 deploy; **architecture revised 2026-05-02 (farmer call): bridge-side, NOT a new fc1 ROS node.** Farmer asked for a delta-t / error parameter on the OpenMCT charts; the right shape is a derived-telemetry sidecar. **2026-05-02 decision:** compute derived values inside the bridge (JS module subscribed to raw topic stream the bridge already consumes), write directly to Timescale + broadcast on WS to OpenMCT. **Reasoning for bridge-side:** (a) bridge already subscribes to every raw topic, (b) elder-plops has the CPU/RAM headroom, (c) iterating on a new metric = `docker compose up -d --build bridge` (seconds) instead of `git push fc1/prod` + deploy.sh + 999.25 init-race risk, (d) no ROS-side consumers of derived topics on the near-term roadmap (alerter is WS-only per 999.1 RESEARCH §Q10), so the "ROS-native lifecycle" argument doesn't pay rent yet. **MUST be replay-aware:** when 999.1 buffer backfills 13min of raw T/RH/PID into Timescale post-Tailscale-dropout, the derivation pipeline must compute derived values for those backfilled timestamps too — otherwise raw series fill in but derived series stay as holes. Bake retroactive derivation into the design from day one. **v1 metric set (mushroom-relevant):** (1) `humidity_error` = humidity − humidity_target — direct PID error visualization, the trigger for this phase; (2) `vpd` (kPa, function of T+RH) — true driver of mushroom moisture exchange, more useful than RH alone; (3) `dew_point` (°C, T+RH) — condensation risk on chamber walls / camera lens; (4) `abs_humidity` (g/m³, T+RH) — what the humidifier actually has to add when temperature swings; (5) `humidity_rate` (%/min, smoothed RH rolling window) — spot leaks/stalls before they hit the band. **Touches:** new `src/chambers/fc-core/fc_core/fc_metrics.py` ROS node + `setup.py` entry_point + `launch/fc.launch.py` wiring (mirrors Plan 27-02 pattern), `src/mission-control/bridge/src/index.js` `ALLOWED_TOPICS` + 5 subscriptions, `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js` SENSORS + fieldToKey, RED tests then GREEN. **Composes with:** 999.17 (overlay plots — VPD overlaid on RH+target tells the real story), 999.22 (alerter must read derived values dynamically — VPD-out-of-range is a nicer alert than RH-out-of-range), 999.23 (when target becomes time-varying, humidity_error has to be re-derived per-tick from current effective target). **Acceptance:** five derived topics live on fc1, persisting to Timescale, visible on OpenMCT with correct units; VPD chart matches a hand-calculated value within ±0.05 kPa for a known T/RH pair.
- **Phase 999.26: Camera coverage prerequisite for vision (roaming or multi-cam)** — Surfaced 2026-05-01 when farmer reviewed Phase 24 scope and called the blocker: a single fixed FC-1 camera only frames a fraction of substrate, so ML vision alerts (pinning, contamination) on that footprint are a demo, not a field-useful tool. Phase 24 (ML vision via ComfyUI) is deferred behind this. Two viable shapes to weigh during planning: (a) **roaming cam** — the farm-rover seed (999.7) carries a single camera through the chamber on a schedule, captures pose-tagged frames covering all shelves; reuses any servo/motion work; one camera to maintain but mechanical complexity and a moving part in a high-RH environment. (b) **multi-cam** — N fixed cameras (one per shelf or per chamber zone), each publishing to a slot topic; reuses the existing `fc_camera` node pattern (parameterize device + camera_id), Phase 21 persistence and Phase 22 scrubber generalize over multiple `camera_id`s; more hardware + more 4G traffic but no mechanical risk. Either path needs: persistence/index extended to multi-camera (`snapshots` table already has `camera_id`), Mission Control + farmer-app UI extended to pick/switch camera, time-lapse composition extended per-camera, vision-agent (Phase 24 follow-up) able to fan out per-camera. Composes with: Phase 24 (the consumer that unblocks), 999.6 (multi-chamber scaling — same pattern), 999.7 (rover — overlaps with shape-(a)), Phase 21/22/23 (persistence, scrubber, timelapse all need camera_id awareness). Pre-decision when promoted: roaming-vs-multi-cam tradeoff with farmer in the loop (mechanical risk vs hardware/cost vs operational complexity).

- **Phase 999.28: fc-core systemd unit hardening — survive blackout/boot races** — Surfaced 2026-05-02 after a farm power outage. fc1 booted, `tailscale0` link came up before acquiring an IPv4. fc-core's `ExecStartPre` only checks `ip link show tailscale0` (link presence), so launch fired while CycloneDDS still reported "tailscale0: does not match an available interface". All 5 ROS nodes failed `rcl_create_node`; `ros2 launch` exited 0 (the known systemd trap captured in `feedback_systemd_restart_ros2_launch`); 5 retries in ~10s tripped `start-limit-hit`; service stayed dead 55min until manual `systemctl reset-failed && systemctl start fc-core`. Farmer-visible: "fc never came back after black out." **Scope:** (1) `ExecStartPre` waits for tailscale0 to have an IPv4 address, not just link existence (e.g. loop on `ip -4 addr show tailscale0 | grep -q inet`); (2) apply the existing Restart=always + `RestartSec` + wider `StartLimitInterval`/`StartLimitBurst` lesson — fc-core unit on the Pi predates that fix; (3) consider `After=`/`Wants=tailscaled.service` or a dedicated tailscale-ready oneshot; (4) audit other fc1 systemd units (fc-update, anything else binding DDS to tailscale0) for the same race. **Out of scope:** changing CycloneDDS interface binding away from tailscale0 — that's the deliberate VPN-only design from the farm connectivity work. **Validation:** simulate by stopping tailscaled and rebooting the Pi; confirm fc-core waits and comes up green without manual intervention. **Composes with:** 999.25 (init race — same family of boot-time fragility on fc1), 999.1 (edge buffering — outages should leave control intact and visibility recoverable, not require a human to notice).

- **Phase 999.29: Replace rolling-duty cap with max-continuous-on + forced cool-down** — Surfaced 2026-05-02 during today's blackout + uplink-instability incident. Chamber RH sat at 68–80% (target 94%) with PID demanding `duty=1.0` continuously for hours. `fc_pwm_driver` enforces a rolling 5-min duty cap D-12 (default `max_duty_5min_avg=0.40` — see `src/chambers/fc-core/fc_core/fc_pwm_driver.py:35-41` + back-solve at `:119-121`). At cap=0.40 the chamber recovers at ~0.5%/min, so a 26% deficit takes nearly an hour to close — every minute below target is mushroom-welfare risk. **Hotfix shipped:** raised cap to 0.90 on fc1/prod (commit `ad949c6` 2026-05-02); this permanently loosens a steady-state safety to cover what is actually a transient recovery scenario.

  **Preferred design (farmer call 2026-05-02):** retire the rolling-average cap entirely and replace with a **max-continuous-on with forced cool-down**: humidifier is allowed to run continuously up to `max_continuous_on_seconds` (e.g. 45 min), then is forced OFF for at least `forced_cooldown_seconds` (e.g. 3 min) before it may run again. Effective max duty in extreme demand ≈ 94% (45/48), ample for recovery from any plausible deficit, while still guaranteeing the mister gets a periodic break to bleed thermal/mechanical load. Steady-state behavior: PID typically demands 5–30% duty, so windows are short and the cool-down rule essentially never engages — i.e. it imposes no penalty on normal operation. Concrete and explainable: "max 45 min on, then 3 min off" is a sentence; "rolling 5-min average duty cap with back-solve" needs a paragraph.

  **Scope sketch:** retire `max_duty_5min_avg`; new params `max_continuous_on_seconds` + `forced_cooldown_seconds` + the `_window_on_seconds` back-solve goes away (windows still exist, just no cap rule on top). State machine in `_tick`: track `_continuous_on_seconds` (incremented when relay is high, reset to 0 on every OFF edge); when `_continuous_on_seconds >= max_continuous_on_seconds`, force OFF and start `_cooldown_remaining = forced_cooldown_seconds`; while `_cooldown_remaining > 0`, override duty to 0 regardless of PID demand. Tests: continuous-on hits cap → forced OFF; cool-down completes → resumes; PID asks for 0.5 forever → never trips cap (windows have built-in offs); rapid demand changes → no missed cool-downs.

  **Validation:** induce a 25% RH deficit (door open then closed), confirm chamber recovers at ≥ ~1.0%/min vs the ~0.5%/min seen today with cap=0.40; confirm during a real long demand period that the forced 3-min off does happen on schedule.

  **Source for 45/3 numbers:** farmer's gut estimate (confirmed 2026-05-02), not from a hardware spec or empirical thermal test. Treat as starting point, not gospel — pre-planning task: check the actual mister hardware spec for max-continuous-duty rating + run a single soak test (run the mister for 60+ min, watch for thermal trip / output degradation / water-pump strain) before locking values into the plan.

  **Fallback design** (if the max-on approach turns out to have an edge case): the original conditional-recovery-mode shape — keep cap=0.40 steady-state but auto-lift to ~0.95 when `|humidity_error| > 0.05` with hysteresis. Documented here for contrast; not the primary plan.

  **Out of scope:** removing all duty protection; UI-tunable cap (lands via Phase 28 Mode primitive anyway).

  **Composes with:** Phase 28 (mode primitive — cool-down params could be per-mode), 999.27 (derived telemetry — `humidity_error` and `humidifier_continuous_on_seconds` are nice things to chart), 999.28 (fc-core systemd hardening — same family of blackout-recovery resilience).

  **Concrete trigger:** today's outage proved cap=0.40 is an active hazard during recovery; until this ships we run with cap=0.90 in steady state (less protection in steady state) or revert to 0.40 and accept slow recovery on every future blackout.

- **Phase 999.30: Reduce telemetry sampling rate to relieve DERP-relay pressure** — Surfaced 2026-05-02 evening after diagnosing tailscaled at 240% CPU on fc1 (load avg 4.7 across 4 cores) when polled from elder-plops over the lossy São Paulo DERP relay. Hypothesis: every 5Hz humidity publish + control-loop chatter has to traverse Tailscale → DERP → elder-plops; with the relay dropping packets, DDS reliable QoS forces aggressive retransmits and tailscaled pays the CPU cost. Reducing publish cadence from `sensor_read_interval: 2.0` (every 2s, 0.5Hz) to ~10s (0.1Hz) cuts the per-second packet volume 5×, which should drop tailscaled CPU well below the saturation point and free up Pi headroom. **Touches:** `src/chambers/fc-core/config/fc_config.yaml` `sensor_read_interval` (currently 2.0); possibly the `control_interval: 1.0` and `display_interval: 1.0` if we want to slow those too — separate decision, since control_interval is a real control-loop knob (slowing it changes PID dynamics, not just visibility cadence). **Implications to think through during planning:** (1) Phase 27 PID tuning was done at 2s interval — slowing to 10s changes the discrete-time response and may need re-tuning; recommend keeping `control_interval` fast and only slowing `sensor_read_interval` (the publish cadence to Mission Control), if that's actually how the code is wired. Read `fc_sensors.py` + `fc_controller.py` to verify the two are decoupled before planning. (2) Alerter "last fresh" sensitivity — Phase 26 alerter uses sensor_health timestamps; slower publish = larger natural gap before "stale" — needs new `sensor_stale_timeout` (currently 10.0s, would have to be at least 2× new publish interval). (3) Mission Control chart resolution — farmer's UI gets 5× coarser; with 999.16 downsampling already in flight this may compound. **Composes with:** 999.1 (edge buffering — fewer raw points per minute = longer effective buffer in same SQLite size; ratio improves), 999.27 (derived telemetry — bridge-side derivation runs at the publish cadence, so cost goes down too), 999.28 (systemd hardening — same family of "make fc1 robust against bad uplink"). **Out of scope:** changing the DERP relay choice (Tailscale auto-selects; could be forced via `--exit-node` but that's its own decision tree); compressing DDS payloads. **Validation:** before/after tailscaled CPU + load-avg measurement when poked from elder-plops; chamber RH chart still readable in Mission Control with 5× coarser samples; alerter doesn't fire false-positive "sensor stale".

---
*Roadmap created 2026-03-28. v1.4 shipped 2026-05-01.*
