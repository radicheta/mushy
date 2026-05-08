# Requirements — v1.5.0.1 (active hotfix) + v1.5 (paused)

---

## v1.5.0.1 — Resilience hotfix from 2026-05-02 incident

**Milestone goal (post-realignment 2026-05-03):** Close the resilience gaps the 2026-05-02 blackout + DERP-relay incident exposed. The original 4-phase shape was overtaken by an architectural detour: fc1's microSD failed during diagnosis; fc1 was rebuilt and brought back on home-LAN wifi with a kernel-WG tunnel through pfSense (172.16.10.0/24); DDS switched from `tailscale0` to `wg0`. The transport switch was the real fix — it absorbs SAMP entirely, partly absorbs SYS, and parks NET until fc1 returns to the farm-4G setup.

### BUF — Edge buffering replay-on-reconnect (promotes 999.1) — SHIPPED 2026-05-03 over wg0

- [x] **BUF-01** — fc1 buffers all `fc.*` topics locally (sqlite WAL, 24h retention) during normal operation; survives fc-core restarts.
- [x] **BUF-02** — On bridge reconnect, fc1 replays un-acked points oldest-first with original timestamps; bridge ingest is idempotent via UNIQUE `(topic, time)`.
- [x] **BUF-03** — Replayed (backfilled) points must NOT poison sensor-health "last fresh" timestamps; alerter ignores backfilled rows per existing WS-only design.
- [ ] **BUF-04** — Acceptance pending natural-event attestation. Original "induced 5-min Tailscale dropout" recipe no longer applicable (DDS not on Tailscale any more); D-12 deferral chosen instead. fc_buffer + replay verified live by farmer eyeball 2026-05-03.

### SYS — fc-core systemd unit hardening (promotes 999.28) — partially shipped via transport switch

- [x] **SYS-02** — `Restart=always` + `RestartSec=10` + `StartLimitIntervalSec=300` + `StartLimitBurst=5` applied to `scripts/pi-deploy/fc-core.service`. ros2 launch's "exit 0 on child crash" trap mitigated by Restart=always.
- [x] **SYS-03** — Unit has explicit `After=wg-quick@wg0.service` and `Wants=wg-quick@wg0.service` (kernel-WG `wg-quick@wg0` brings up wg0 at boot). IPv4 polling loop kept as belt-and-braces.
- [x] **SYS-01** — `ExecStartPre` waits for IPv4 on `wg0` via 60-attempt × 1s loop on `ip -4 addr show wg0 | grep -q inet`. (Previous ROADMAP text describing `ip link show wg0` was stale.)
- [ ] **SYS-04** — Validation reboot pending. Now cheap to do (fresh microSD, stable home-LAN connectivity).

### SAMP — Telemetry sampling-rate reduction — MOOTED 2026-05-03

The 240% tailscaled CPU on fc1 was the SAMP justification. With DDS on kernel-WG and tailscaled disabled, fc1 load avg is 0.41. SAMP-01..03 retired in this milestone. The "0.1Hz publish cadence is fine for chamber" idea remains a valid backlog candidate (4G-credit / chart-resolution motivations), just no longer load-bearing here.

### NET — Repo netplan drift reconciliation — MOOTED 2026-05-03 in planned form

fc1 is on home-LAN wifi with kernel-WG, not at the farm on 4G. The drifted netplan state captured in the original plan was a farm-4G snapshot; both the reconciliation and the new `eth0 dhcp4` stanza wait until fc1 is back at the farm. The underlying anti-pattern (manual fc1 netplan edits not in repo; fc-system-sync would clobber them) re-surfaces at that point.

### Out of Scope (this hotfix)

- **999.29 max-continuous-on + cool-down redesign** — stays in v1.5 main; needs mister hardware soak to validate the 45/3 farmer estimate first. Operational risk already covered by the 0.40 → 0.90 PWM cap hotfix on `fc1/prod` (commit `ad949c6`).
- **microSD wear from fc_buffer SQLite WAL** — separate work item, gated on user procuring USB-SSD hardware.
- **`cyclonedds-tailscale.xml` filename rename** — cosmetic, tracked separately.

---

## v1.5 Requirements (paused — resumes after v1.5.0.1)

### HUMID — Analog Humidity Control

- [x] **HUMID-01** — Controller publishes a 0–100% duty cycle setpoint each control tick (replaces bang-bang on/off decision).
- [x] **HUMID-02** — Actuator layer translates duty cycle into time-proportional on/off windows on the existing relay (slow-PWM); window length per calibration findings (`.planning/phases/999.9-pid-time-proportional-humidity-control/CALIBRATION-FINDINGS-2026-04-11.md`).
- [x] **HUMID-03** — PID gains tunable as ROS params; defaults derived from 2026-04-11 system-ID data.
- [ ] **HUMID-04** — Operating band tightens from interim ±1% to PID-tracked tolerance verifiable on a 2-hour soak at the farm; farmer-attested.

### MODE — Mode Primitive + Runtime Config Delivery (incorporates SEED-001)

- [x] **MODE-01
** — Controller exposes a mode registry: named bundles of `(target_humidity, band_low, band_high, defend_side: low|high|both, T_target_optional)` defined in declarative YAML, with mode definitions flattened into dotted-key ROS2 params (e.g. `modes.fruiting.band_low`). Schema reconciled with SEED-004 at Phase 28 discuss-phase 2026-05-07; old `(target_RH, band, duty-cycle behavior)` wording retired. `T_target` reserved for future VPD anchoring; loop stays RH-targeted in v0.
- [x] **MODE-02
** — Two baseline modes shipped: `fruiting` and `pinning`, with per-mode targets/bands chosen with farmer.
- [x] **MODE-03
** — Farmer can switch active mode via ROS service call (and farmer-app button when surfaced); switch takes effect on next control tick.
- [x] **MODE-04
** — Controller publishes `current_mode` topic so downstream consumers (alerter, dashboards, scheduler) read live mode without restart.
- [x] **MODE-05
** — Mode definitions are runtime-tunable without a deploy cycle (SEED-001 pain): farmer can edit a mode's target/band and have it picked up live on the next switch (or on explicit reload).

### ALRT — Alerter Mode Awareness + Cooldown Tuning

- [x] **ALRT-08** — Alerter reads RH target and band from `current_mode` (or `current_target_humidity` + `current_humidity_band` topics) instead of static env vars; closes backlog 999.22.
- [x] **ALRT-09** — Sweep `src/agents/alerter/src/config.js` for any other farmer-meaningful knobs hiding in env (heartbeat hour, humidifier-stuck threshold, RH OOB grace, pi/sensor offline minutes) and route them through the same dynamic source as ALRT-08.
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
| BUF-01 | 27.1 | Complete (2026-05-03 over wg0) |
| BUF-02 | 27.1 | Complete (2026-05-03 over wg0) |
| BUF-03 | 27.1 | Complete (2026-05-03 over wg0) |
| BUF-04 | 27.1 | Pending — natural-event attestation |
| SYS-01 | 27.2 | Complete — IPv4-on-wg0 60×1s ExecStartPre loop |
| SYS-02 | 27.2 | Complete — fc-core.service has Restart=always + StartLimit* |
| SYS-03 | 27.2 | Complete — explicit After=/Wants=wg-quick@wg0.service |
| SYS-04 | 27.2 | Pending — reboot validation |
| SAMP-01 | 27.3 | Mooted by transport switch |
| SAMP-02 | 27.3 | Mooted by transport switch |
| SAMP-03 | 27.3 | Mooted by transport switch |
| NET-01 | 27.4 | Mooted (parked until fc1 returns to farm-4G) |
| NET-02 | 27.4 | Mooted (parked until fc1 returns to farm-4G) |
| NET-03 | 27.4 | Mooted (parked until fc1 returns to farm-4G) |

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
| ALRT-08 | 29 | Complete |
| ALRT-09 | 29 | Complete |
| ALRT-10 | 29 | Pending |
| SCHED-01 | 30 | Pending |
| SCHED-02 | 30 | Pending |
| SCHED-03 | 30 | Pending |
| EXPT-01 | 31 | Pending |
| EXPT-02 | 31 | Pending |
| EXPT-03 | 31 | Pending |
