---
status: partial
phase: 27-pid-time-proportional-duty-cycle-primitive
plan: 27-05
deploy_started: 2026-05-01T21:42:49Z
soak_window_start: 2026-05-01T21:50:00Z
soak_window_end: 2026-05-01T23:50:00Z
---

# Phase 27 Soak Evidence — HUMID-04

## Deploy verification (DONE)

**fc1 (raspberry pi, 100.96.239.75)**

- `fc1/prod` head: `d8c0cfb` (includes `fix(27): register fc_core.vendor packages in setup.py`)
- `colcon build --packages-select fc_core` succeeded (7.78s)
- `fc-core.service`: active (running) since `2026-05-01 21:42:49 UTC`
- All four expected nodes present in cgroup: `fc_sensors`, `fc_display`, `fc_pwm_driver`, `fc_camera`, **plus `fc_controller`** (verified after vendor-packages fix)
- No `fc_controller` traceback after redeploy
- `ros2 topic list` shows all three new topics: `/fc1/actuators/humidifier_duty`, `/fc1/control/humidity_target`, `/fc1/control/pid_output`

**elder-plops (mission control)**

- Bridge container `mushy-bridge-1` rebuilt with `--build` (image `6124e032973c`)
- Bridge logs show all three new subscriptions:
  - `Humidifier-duty subscription: TRANSIENT_LOCAL QoS`
  - `Humidity-target subscription: TRANSIENT_LOCAL QoS`
  - `PID-output subscription: TRANSIENT_LOCAL QoS`

**Timescale ingestion (5 min after deploy)**

| topic | count | min | max | avg |
|---|---|---|---|---|
| fc.humidifier_duty | 23 | 0.693 | 0.830 | 0.800 |
| fc.humidity_target | 23 | 0.940 | 0.940 | 0.940 |
| fc.pid_output | 23 | 0.693 | 0.830 | 0.800 |

Notes:
- `pid_output == humidifier_duty` because PID is in the linear region (no Mode C clamp, no soft-limit clamp). Expected when humidity is near target.
- `humidity_target` locked at 0.94 — setpoint ramp completed (within first 30s of controller boot); steady-state target matches `fc_config.yaml`.

## Hotfix during deploy

**Bug caught at deploy gate, NOT in any sub-plan:**

`fc_controller` crashed on first deploy with:
```
ModuleNotFoundError: No module named 'fc_core.vendor'
```

Root cause: `setup.py` `packages=` only listed `fc_core`. The vendored `simple_pid` directory was committed to source (Plan 27-01) but never registered as a Python package, so `colcon install` did not ship it.

Plan 27-02 edited `setup.py` to add the `fc_pwm_driver` console_script entry but missed the `packages=` update.

Fix landed in commit `3c73812` (main) → merged `aaa2cca` to fc1/prod. Both Wave 0 plans (27-01 and 27-02) should add a process check to setup.py packaging in their retro/learnings.

## Soak window (PENDING — closes 2026-05-01T23:50:00Z)

Verification queries to run after window close:

```sql
SELECT MIN(value) AS min_rh, MAX(value) AS max_rh, AVG(value) AS avg_rh,
       STDDEV(value) AS stddev_rh, COUNT(*) AS samples
FROM telemetry
WHERE topic='fc.humidity'
  AND time >= '2026-05-01T21:50:00Z'
  AND time <  '2026-05-01T23:50:00Z';
```

Pass criteria (from RESEARCH §HUMID-04):
- `max_rh - min_rh <= 0.01` (1% absolute = 2× the ±0.5% band)
- Stretch: `stddev_rh <= 0.005`
- Zero `MODE C` engagements per `journalctl -u fc-core` over the window (controller never had to bypass into emergency clamp)
- Farmer attestation: humidifier behavior visually OK on Mission Control; no audible/visible slamming

**Pending actions:**
- [ ] Run the SQL aggregate at/after 23:50 UTC
- [ ] Grep `journalctl -u fc-core --since "21:50"` for `MODE C engaged|disengaged` count
- [ ] Pull farmer attestation (Signal)
- [ ] Mark this file `status: complete` and append PASS/FAIL verdict

## Observations during soak (not blockers)

- **`humidifier_duty` is visibly noisy on the OpenMCT chart.** Root cause is SHT30 ~±0.1% RH measurement noise multiplied by Kp=0.5 → ~0.05 swings in `pid_output` for sub-0.1% RH wobble. D term is already filtered (`pid_derivative_filter_tau: 10.0`). **Physical behavior is not affected** — slow-PWM locks duty at the start of each 120s window and ignores intra-window jitter, so the relay never saw the noise. Cosmetic-plus-edge-case (occasional cap-forecast bump at window roll). Suggested fix for the v1.6 PID-tuning phase: add a `pid_input_filter_tau: 10.0` EMA on humidity before the PID input only (raw stays on dashboards / sensor_health). One param, ~10 lines, no architectural change. Phase lag (~10s) is invisible against the chamber's minutes-scale transport delay. **Not shipping during the soak gate** — bundling with future PID refinement work alongside 999.27 derived metrics.
