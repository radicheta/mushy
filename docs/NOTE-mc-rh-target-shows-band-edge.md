# TODO: Mission Control "RH target" shows the defended band-edge, not the real setpoint

Status: open / deferred (logged 2026-06-27)
Priority: cosmetic (display-only; no control impact)

## Symptom

MC plots "RH target" as a value that jumps between the two band edges instead of
showing the humidity target the farmer set. With the fruiting band `[0.885, 0.915]`
(target 0.90), MC shows:

- **91.5** when RH is above the band (defending the high edge `band_high`)
- **88.5** when RH is in/below the band (defending the low edge `band_low`)
- **never 90.0** — even though the chamber actually settles at ~the midpoint

This confused the farmer after lowering the target to 90% on 2026-06-27: MC read 91.5.

## Root cause

The `fc1/humidity_target` topic publishes `self._effective_setpoint`, which
`_ramp_setpoint_to_band()` ramps toward the **defended band edge** (Phase 28 D-10),
not the target. After the 2026-06-21 quadratic feather, the controller's true
operating point is the band **midpoint** (the feather anchors error=0 there;
chamber settles ~midpoint = feather-up balanced against passive-drying-down).
So the published band-edge no longer matches where the chamber actually sits.

`_effective_setpoint` is **telemetry-only** — it is NOT fed to the PID. The control
loop computes `error_pct` directly from the band edges + feather. So the published
value can be changed freely without affecting control.
(See `fc_controller.py`: `_effective_setpoint` is only written in the ramp helpers
and read only by the `_humidity_target_pub` publishes.)

## Proposed fix

Publish the **midpoint** (`mode.target`, currently 0.90) on `fc1/humidity_target`
instead of `_effective_setpoint`. MC then reads a stable, honest "90.0" matching
the farmer-set target.

- Decide whether the ramp/`_effective_setpoint` machinery is still wanted at all
  post-feather, or whether the topic should just carry `mode.target` directly.
- Display-only change, but it lives in the deployed controller on `fc1/prod`, so it
  needs a rebuild + `fc-core` restart. Queue the deploy for when RH has settled
  (don't restart mid-adjustment — a restart resets PID state).

## Related

- Feather / midpoint operating-point behavior: 2026-06-21 calibration + 2026-06-27
  RH lowering (band `[0.885, 0.915]`, committed to `fc1/prod` as `c758319`).
- Phase 28 D-10 "published target = band edge" semantics is the original source of
  this display behavior.
