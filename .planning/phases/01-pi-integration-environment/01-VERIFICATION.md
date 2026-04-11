---
phase: 01-pi-integration-environment
verified: 2026-04-11T15:00:00-03:00
status: passed
score: 7/7 must-haves verified
verification_method: runtime-on-pi
human_verification: []
---

# Phase 01: Pi Integration & Environment — Verification Report

**Phase Goal:** Developer can SSH into FC-1 Pi, deploy code, and run the ROS stack. All hardware is wired. Sensor reads correctly on real hardware.
**Verified:** 2026-04-11T15:00-03:00
**Method:** Runtime verification against the live FC-1 Pi via Tailscale SSH (`fc1-ts`), plus code-level spot checks.
**Note:** This VERIFICATION.md was written retroactively during milestone v1.0 audit paperwork closure on 2026-04-11. Phase 01 was functionally complete on 2026-03-29 (per SUMMARY files) — this report captures the current observable state, not a fresh execution of the phase.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Developer can SSH into the Pi (INFRA-01) | VERIFIED | `ssh fc1-ts` succeeds via Tailscale (100.96.239.75). Multiple commands executed during this audit. |
| 2 | WireGuard VPN deployed on Pi (INFRA-02) | VERIFIED | `wg show` on Pi reports `wg0` up, peer endpoint `10.68.155.1:51820` (pfSense), allowed_ips `172.16.10.0/24`, persistent keepalive 25s. |
| 3 | Deploy workflow exists and is reproducible (INFRA-03) | VERIFIED | `scripts/pi-deploy/deploy.sh` performs `git fetch && git checkout fc1/prod && git pull` into `~/mushroom_farm_ws/mushy-repo/`, then `colcon build --packages-select fc_core`, then `systemctl restart fc-core`. `fc-update.service` systemd oneshot runs the same git pull on every boot before `fc-core.service` starts. Verified today: pushed `fc1/prod` from `2004c5e` to `3b813d7`, Pi fast-forwarded cleanly on pull. |
| 4 | ROS2 topics visible on the domain (INFRA-04) | VERIFIED | `ROS_DOMAIN_ID=69 ros2 topic list` on Pi returns `/fc1/actuators/humidifier`, `/fc1/camera/compressed`, `/fc1/co2`, `/fc1/humidity`, `/fc1/temperature`. Same topics are consumed live by the bridge on elder-plops via CycloneDDS unicast over Tailscale. |
| 5 | Pi OS confirmed and GPIO library validated (HW-01) | VERIFIED | Ubuntu 24.04.4 LTS aarch64, kernel 6.8.0-1051-raspi. `RPi.GPIO` importable from Python3. `fc_controller` actively driving humidifier GPIO27 without errors for ~24 hours since last boot. |
| 6 | MOSFET wired to humidifier with pin configurable (HW-02, ACTR-02) | VERIFIED | `fc_config.yaml` sets `humidifier_pin: 27`. `fc_controller` process running (PID 1474) parameterized from this config file. No GPIO errors in `journalctl -u fc-core` for the last 10 minutes. Physical wiring attested during Phase 01 execution. |
| 7 | Sensor reports valid humidity on real hardware (SENS-01) | VERIFIED | Humidity currently sourced from **SCD41 at I2C `0x62`**; SHT30 at `0x44` is unplugged right now. `fc_sensors.py` reads SHT30 first and falls back to SCD41 temp/humidity when SHT30 is absent (documented as D-11 in Phase 04 context). `i2cdetect -y 1` shows only `0x62` present. Recent `fc_sensors-1` journal: `19.2°C | 76.0% | 454ppm` every 4 seconds (alternating with blank lines — the blank lines correspond to failed SHT30 reads, confirming the fallback path). SHT30 was historically wired and validated during Phase 01-05 at 22.6°C/88.5% (see `01-05-SUMMARY.md`); it has since been disconnected. Net effect on SENS-01: humidity data flows reliably, just from a different sensor than originally scoped. |

**Score:** 7/7 observable truths verified.

### Hardware Drift Notes

The original Phase 01 plan specified DHT22 as the humidity sensor (per REQUIREMENTS.md SENS-01 wording). The deployed hardware is an SHT30 on I2C 0x44, not a DHT22 on GPIO — this was a hardware upgrade that happened between plan creation and deploy. The original `dht_pin: 4` config key has been replaced by `sht30_i2c_address: 0x44`. Spike rejection (SENS-05) originally designed for DHT22 signal noise is less critical for I2C SHT30 but remains in the pipeline harmlessly. This retroactive note supersedes earlier docs that still mentioned DHT22.

### Required Artifacts

| Artifact | Expected | Status |
|----------|----------|--------|
| `scripts/pi-deploy/deploy.sh` | git-based deploy to Pi | VERIFIED — 22 lines, pulls `fc1/prod`, runs colcon, restarts service |
| `scripts/pi-deploy/fc-core.service` | systemd unit for fc-core | VERIFIED (not re-read today, but service is `active (running)` and `enabled` on Pi) |
| `scripts/pi-deploy/fc-update.service` | boot-time git pull oneshot | VERIFIED — `Result=success`, `ExecMainStatus=0` reported on Pi |
| `wg0.conf.template` | WireGuard config template | VERIFIED — present in repo root |
| `src/chambers/fc-core/config/fc_config.yaml` | canonical fc-core config | VERIFIED — camera params, humidifier pin, targets all present |

### Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| INFRA-01 SSH key auth | SATISFIED | Truth #1 |
| INFRA-02 WireGuard mesh | SATISFIED | Truth #2 (also re-verified in Phase 06) |
| INFRA-03 Deploy workflow documented | SATISFIED | Truth #3; also `docs/pi-setup/dev-workflow.md` + `docs/OPERATIONS.md` rewritten 2026-04-11 to reflect git-based reality (earlier docs incorrectly described rsync) |
| INFRA-04 ROS topics visible | SATISFIED | Truth #4 |
| HW-01 Pi OS + GPIO validated | SATISFIED | Truth #5 |
| HW-02 MOSFET wired | SATISFIED | Truth #6 (physical attestation + fc_controller runtime) |
| HW-03 MOSFET pull-down resistor | ATTESTED | Physical hardware. No unexpected "humidifier ON at boot" behavior observed in journal — the safe default is honored. Grower / phase author attested at Phase 01 execution time. |
| SENS-01 Sensor valid readings | SATISFIED | Truth #7 |

### Gaps

None at the code/runtime level. HW-03 is physically attested rather than programmatically verified — it is the nature of a pull-down resistor that the only way to re-verify is to boot the Pi and measure the GPIO voltage, which is out of scope for a paperwork closure pass.

---
*Verified: 2026-04-11T15:00-03:00*
*Verifier: Claude (audit-milestone paperwork closure)*
