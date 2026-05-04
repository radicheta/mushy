# PID Calibration Notes — FC-1 Humidity

**Date:** 2026-05-03  
**Chamber:** FC-1 stack  
**Target:** 94% RH

## TODO

- [x] Find current P/I/D values in config
- [ ] Try `ros2 param set /fc_controller pid_kp 0.35` and observe for 30-60 min
- [ ] Consider adding a ±0.3% deadband to stop controller chasing sensor noise

## Current PID Config (`src/chambers/fc-core/config/fc_config.yaml`)

| Param | Value |
|-------|-------|
| `pid_kp` | 0.5 |
| `pid_ki` | 0.002 |
| `pid_kd` | 4.0 |
| `pid_derivative_filter_tau` | 10.0s |
| `pwm_window_seconds` | 120.0s (2-min duty cycle window) |

Params are **live-reloadable** — re-read every control tick. Use `ros2 param set` to tune without restart. Changes don't write back to yaml; update manually once a value is confirmed good.

## Diagnosis

This is a **limit cycle**, not a transient. The oscillation does not decay — same amplitude at 21:00 as 22:15. Caused by P gain being too aggressive for the ~5 min system lag between duty change and sensor response.

A well-tuned PID on this system should reach essentially flat steady state. Next step: drop Kp ~30% (0.5 → 0.35) and observe whether oscillation decays over 30-60 min.

## First Run Observations

Humidity settles well to setpoint but oscillates with ~5-7 minute period, ±0.2-0.3% amplitude.

- Initial heat-up (17:00–19:00): underdamped, large overshoot/undershoot
- Steady state (20:00+): centered on 94%, limit cycling, duty steady at ~0.55–0.65
- Actuator: PWM duty on humidifier (2-min window), pink dots = instantaneous on/off within cycle

## Charts

![Overview](pid_cal_overview.png)
![Full session](pid_cal_full.png)
![Zoomed steady state 21:00–22:15](pid_cal_zoomed.png)
