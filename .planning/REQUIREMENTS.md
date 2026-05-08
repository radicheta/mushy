# Requirements — v1.5 (Analog Humidity Control + Modes)

> v1.5.0.1 (resilience hotfix) shipped 2026-05-07 — see `.planning/milestones/v1.5.0.1-REQUIREMENTS.md` and `.planning/milestones/v1.5.0.1-ROADMAP.md` for the archive.

---

## v1.5 — Analog Humidity Control & Condensation/Evaporation Forcing

### HUMID — Analog Humidity Control

- [x] **HUMID-01** — Controller publishes a 0–100% duty cycle setpoint each control tick (replaces bang-bang on/off decision).
- [x] **HUMID-02** — Actuator layer translates duty cycle into time-proportional on/off windows on the existing relay (slow-PWM); window length per calibration findings (`.planning/phases/999.9-pid-time-proportional-humidity-control/CALIBRATION-FINDINGS-2026-04-11.md`).
- [x] **HUMID-03** — PID gains tunable as ROS params; defaults derived from 2026-04-11 system-ID data.
- [x] **HUMID-04** — Operating band tightens from interim ±1% to PID-tracked tolerance verifiable on a 2-hour soak at the farm; farmer-attested 2026-05-02.

### MODE — Mode Primitive + Runtime Config Delivery (incorporates SEED-001)

- [x] **MODE-01** — Controller exposes a mode registry: named bundles of `(target_humidity, band_low, band_high, defend_side: low|high|both, T_target_optional)` defined in declarative YAML, with mode definitions flattened into dotted-key ROS2 params (e.g. `modes.fruiting.band_low`). Schema reconciled with SEED-004 at Phase 28 discuss-phase 2026-05-07; old `(target_RH, band, duty-cycle behavior)` wording retired. `T_target` reserved for future VPD anchoring; loop stays RH-targeted in v0.
- [x] **MODE-02** — Two baseline modes shipped: `fruiting` and `pinning`, with per-mode targets/bands chosen with farmer.
- [x] **MODE-03** — Farmer can switch active mode via ROS service call (and farmer-app button when surfaced); switch takes effect on next control tick.
- [x] **MODE-04** — Controller publishes `current_mode` topic so downstream consumers (alerter, dashboards, scheduler) read live mode without restart.
- [x] **MODE-05** — Mode definitions are runtime-tunable without a deploy cycle (SEED-001 pain): farmer can edit a mode's target/band and have it picked up live on the next switch (or on explicit reload).

### ALRT — Alerter Mode Awareness + Cooldown Tuning

- [x] **ALRT-08** — Alerter reads RH target and band from `current_mode` (or `current_target_humidity` + `current_humidity_band` topics) instead of static env vars; closes backlog 999.22.
- [x] **ALRT-09** — Sweep `src/agents/alerter/src/config.js` for any other farmer-meaningful knobs hiding in env (heartbeat hour, humidifier-stuck threshold, RH OOB grace, pi/sensor offline minutes) and route them through the same dynamic source as ALRT-08.
- [ ] **ALRT-10** — Alert cooldown thresholds tuned based on Phase 17's ≥2 weeks of live data (Phase 20 carry from v1.3).

### SCHED — Time-Of-Day Mode Scheduling

- [ ] **SCHED-01** — Declarative schedule definition (YAML/JSON) maps time-of-day windows to mode names (e.g. "06:00–22:00 → fruiting; 22:00–06:00 → pinning").
- [ ] **SCHED-02** — A scheduler issues mode-switch service calls at window boundaries; closes backlog 999.23 groundwork (canonical target becomes a function of time).
- [ ] **SCHED-03** — Default profile is the existing constant single-mode case (no schedule) — backward compatible with HUMID-* and MODE-* defaults.

### EXPT — Experimental Forcing Modes

- [ ] **EXPT-01** — `force-condensation` mode: 100% duty cycle for N minutes, auto-reverts to prior mode on timeout. Farmer-triggered via Signal command or farmer-app button.
- [ ] **EXPT-02** — `force-evaporation` mode: 0% duty cycle for N minutes, auto-reverts. Same trigger surface as EXPT-01.
- [ ] **EXPT-03** — Both experimental modes log their start/end + measured RH delta to TimescaleDB so farmer can review experiment outcomes after the fact.

---

## Future Requirements (deferred from v1.5 scope)

- **Mode editor UI in farmer app** — graphical mode definition + schedule editor; v1.6 candidate, depends on farmer-app maturity (999.11).
- **Per-mode PID gains** — different modes carry different gains for stage-aware tuning; baseline v1.5 ships one PID gain set across all modes.
- **Stage-triggered mode transitions** — farmer flags "spawn-run start" → schedule advances; v1.6 candidate, depends on farmOS event integration.
- **Mode-aware sensor selection** — trust SHT30 RH during incubation, SCD41 RH during fruiting; deferred until SCD41 RH clipping is investigated (Phase 26 known issue).

## Out of Scope

- **Temperature control** — still no actuator in scope.
- **Multi-chamber mode coordination** — single-chamber until multi-chamber milestone.
- **PID auto-tuning** — manual tuning from calibration data is sufficient for v1.5.
- **Phase 19 (FarmOS admin actions)** — deferred to v1.6; still Zoy/farm-team gated.

## Traceability

| REQ-ID | Phase | Status |
|--------|-------|--------|
| HUMID-01 | 27 | Complete |
| HUMID-02 | 27 | Complete |
| HUMID-03 | 27 | Complete |
| HUMID-04 | 27 | Complete (farmer-attested 2026-05-02) |
| MODE-01 | 28 | Complete |
| MODE-02 | 28 | Complete |
| MODE-03 | 28 | Complete |
| MODE-04 | 28 | Complete |
| MODE-05 | 28 | Complete |
| ALRT-08 | 29 | Complete |
| ALRT-09 | 29 | Complete |
| ALRT-10 | 29 | Pending |
| SCHED-01 | 30 | Pending |
| SCHED-02 | 30 | Pending |
| SCHED-03 | 30 | Pending |
| EXPT-01 | 31 | Pending |
| EXPT-02 | 31 | Pending |
| EXPT-03 | 31 | Pending |
