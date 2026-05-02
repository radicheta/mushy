# Requirements — v1.5.0.1 (active hotfix) + v1.5 (paused)

---

## v1.5.0.1 — Resilience hotfix from 2026-05-02 incident

**Milestone goal:** Close the resilience gaps the 2026-05-02 blackout + DERP-relay incident exposed (telemetry lost forever during dropouts, fc-core stuck dead 55 min after a boot race, tailscaled saturated under bad DERP) before resuming v1.5 main. Pattern matches v1.2.1.

### BUF — Edge buffering replay-on-reconnect (promotes 999.1)

Wave 1+2 already on `main` (commits `ad44a36..e8d15d0` 2026-05-02); this milestone closes Wave 3.

- [ ] **BUF-01** — fc1 buffers all `fc.*` topics locally (sqlite WAL, 24h retention) during normal operation; survives fc-core restarts.
- [ ] **BUF-02** — On bridge reconnect, fc1 replays un-acked points oldest-first with original timestamps; bridge ingest is idempotent via UNIQUE `(topic, time)`.
- [ ] **BUF-03** — Replayed (backfilled) points must NOT poison sensor-health "last fresh" timestamps (composes with 999.18 spirit); alerter ignores backfilled rows per existing WS-only design.
- [ ] **BUF-04** — Induced 5-minute Tailscale dropout fills OpenMCT chart within 60s of reconnect with original timestamps; farmer-attested.

### SYS — fc-core systemd unit hardening (promotes 999.28)

- [ ] **SYS-01** — `ExecStartPre` waits for `tailscale0` to have an IPv4 address, not just link existence (e.g. loop on `ip -4 addr show tailscale0 | grep -q inet`).
- [ ] **SYS-02** — `Restart=always` + `RestartSec` + wider `StartLimitInterval`/`StartLimitBurst` applied to fc-core unit per existing `feedback_systemd_restart_ros2_launch` lesson; ros2 launch's "exit 0 on child crash" trap mitigated.
- [ ] **SYS-03** — `After=`/`Wants=tailscaled.service` relationship audited and applied where appropriate; other fc1 systemd units (fc-update, anything else binding DDS to tailscale0) audited for the same race.
- [ ] **SYS-04** — Validation: stop `tailscaled` and reboot the Pi; fc-core waits and comes up green without manual `reset-failed && start`. Farmer not paged.

### SAMP — Telemetry sampling-rate reduction (promotes 999.30)

- [ ] **SAMP-01** — `sensor_read_interval` raised from 2.0s to 10.0s in `fc_config.yaml`; `control_interval` kept fast (decoupled — slowing it would change PID dynamics, not just visibility cadence).
- [ ] **SAMP-02** — Phase 26 alerter `sensor_stale_timeout` and any freshness windows raised to ≥2× new publish cadence so the slower stream doesn't false-fire "sensor stale".
- [ ] **SAMP-03** — Validation: tailscaled CPU on fc1 measurably drops when poked from elder-plops over the lossy DERP relay; chamber RH chart still readable in Mission Control with 5× coarser samples.

### NET — Repo netplan drift reconciliation

Tonight's manual edits on fc1 (`/etc/netplan/50-cloud-init.yaml` minus mossrock-west, deleted `/etc/netplan/99-static.yaml`, added `99-disable-network-config.cfg`) are not in the repo. Repo's `60-wifi.yaml` also lacks an `ethernets:` block, so wired ethernet to the 4G router currently does nothing.

- [ ] **NET-01** — Repo netplan tracks fc1's currently-running clean state: mossrock-west dropped from `wlan0`, no 99-static.yaml, cloud-init network regen disabled.
- [ ] **NET-02** — Repo adds `eth0` `dhcp4: true` stanza so the wired path to the 4G router works as a redundant uplink alongside wlan0.
- [ ] **NET-03** — fc-system-sync applies the reconciled config to fc1 without breaking the currently-running uplink; wired path verified end-to-end (cable in → DHCP → ROS still flowing).

### Out of Scope (this hotfix)

- **999.29 max-continuous-on + cool-down redesign** — stays in v1.5 main; needs mister hardware soak to validate the 45/3 farmer estimate first. Operational risk already covered by the 0.40 → 0.90 PWM cap hotfix on `fc1/prod` (commit `ad949c6`).
- **DERP relay choice / `--exit-node`** — separate decision tree from the publish-cadence cut.
- **Compressing DDS payloads** — not the bottleneck.
- **First reboot validation of tonight's netplan changes** — deliberately deferred until SYS-04 ships, when reboot is no longer scary.

---

## v1.5 Requirements (paused — resumes after v1.5.0.1)

### HUMID — Analog Humidity Control

- [x] **HUMID-01** — Controller publishes a 0–100% duty cycle setpoint each control tick (replaces bang-bang on/off decision).
- [x] **HUMID-02** — Actuator layer translates duty cycle into time-proportional on/off windows on the existing relay (slow-PWM); window length per calibration findings (`.planning/phases/999.9-pid-time-proportional-humidity-control/CALIBRATION-FINDINGS-2026-04-11.md`).
- [x] **HUMID-03** — PID gains tunable as ROS params; defaults derived from 2026-04-11 system-ID data.
- [ ] **HUMID-04** — Operating band tightens from interim ±1% to PID-tracked tolerance verifiable on a 2-hour soak at the farm; farmer-attested.

### MODE — Mode Primitive + Runtime Config Delivery (incorporates SEED-001)

- [ ] **MODE-01** — Controller exposes a mode registry: named bundles of `(target_RH, band, duty-cycle behavior)` defined in declarative YAML/JSON.
- [ ] **MODE-02** — Two baseline modes shipped: `fruiting` and `pinning`, with per-mode targets/bands chosen with farmer.
- [ ] **MODE-03** — Farmer can switch active mode via ROS service call (and farmer-app button when surfaced); switch takes effect on next control tick.
- [ ] **MODE-04** — Controller publishes `current_mode` topic so downstream consumers (alerter, dashboards, scheduler) read live mode without restart.
- [ ] **MODE-05** — Mode definitions are runtime-tunable without a deploy cycle (SEED-001 pain): farmer can edit a mode's target/band and have it picked up live on the next switch (or on explicit reload).

### ALRT — Alerter Mode Awareness + Cooldown Tuning

- [ ] **ALRT-08** — Alerter reads RH target and band from `current_mode` (or `current_target_humidity` + `current_humidity_band` topics) instead of static env vars; closes backlog 999.22.
- [ ] **ALRT-09** — Sweep `src/agents/alerter/src/config.js` for any other farmer-meaningful knobs hiding in env (heartbeat hour, humidifier-stuck threshold, RH OOB grace, pi/sensor offline minutes) and route them through the same dynamic source as ALRT-08.
- [ ] **ALRT-10** — Alert cooldown thresholds tuned based on Phase 17's ≥2 weeks of live data (Phase 20 carry from v1.3).

### SCHED — Time-Of-Day Mode Scheduling

- [x] **SCHED-01
** — Declarative schedule definition (YAML/JSON) maps time-of-day windows to mode names (e.g. "06:00–22:00 → fruiting; 22:00–06:00 → pinning").
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

### v1.5.0.1 (active)

| REQ-ID | Phase | Status |
|--------|-------|--------|
| BUF-01 | 27.1 | Pending |
| BUF-02 | 27.1 | Pending |
| BUF-03 | 27.1 | Pending |
| BUF-04 | 27.1 | Pending |
| SYS-01 | 27.2 | Pending |
| SYS-02 | 27.2 | Pending |
| SYS-03 | 27.2 | Pending |
| SYS-04 | 27.2 | Pending |
| SAMP-01 | 27.3 | Pending |
| SAMP-02 | 27.3 | Pending |
| SAMP-03 | 27.3 | Pending |
| NET-01 | 27.4 | Pending |
| NET-02 | 27.4 | Pending |
| NET-03 | 27.4 | Pending |

### v1.5 (paused)

| REQ-ID | Phase | Status |
|--------|-------|--------|
| HUMID-01 | 27 | Complete |
| HUMID-02 | 27 | Complete |
| HUMID-03 | 27 | Complete |
| HUMID-04 | 27 | Pending |
| MODE-01 | 28 | Pending |
| MODE-02 | 28 | Pending |
| MODE-03 | 28 | Pending |
| MODE-04 | 28 | Pending |
| MODE-05 | 28 | Pending |
| ALRT-08 | 29 | Pending |
| ALRT-09 | 29 | Pending |
| ALRT-10 | 29 | Pending |
| SCHED-01 | 30 | Pending |
| SCHED-02 | 30 | Pending |
| SCHED-03 | 30 | Pending |
| EXPT-01 | 31 | Pending |
| EXPT-02 | 31 | Pending |
| EXPT-03 | 31 | Pending |
