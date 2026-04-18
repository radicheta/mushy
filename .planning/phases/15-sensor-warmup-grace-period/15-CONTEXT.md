# Phase 15: Sensor warm-up grace period

**Filed:** 2026-04-17 (promoted from 999.8 backlog)
**Milestone:** v1.2.1 (hotfix)
**Status:** Filed, awaiting planning
**Prioritized by farmer:** yes — explicit ask 2026-04-17

## Problem

Every restart of `fc-core` on the Pi produces a ~30s transient spike on
the first sensor reads before values settle. Example sequence observed
during the 2026-04-11 calibration session:

```
t=0s   18.7°C / 77.2% RH
t=2s   21.8°C / 64.4% RH
t=12s  21.4°C / 66% RH  (settled)
```

Consequences:
1. Contaminates tick-gain and bounce measurements.
2. Can trigger spurious humidifier ON, which then gets dwell-locked
   for 3 minutes even once the reading corrects.
3. Gives the farmer false data in Mission Control right when they
   most want to trust it (just after a deploy).

## Farmer constraint (2026-04-17)

> "the sensor noise on restarting the pi bothers the farmer and please
> prio warmup phase. rather have a bigger gap than noise"

Translation for planning: **a visible gap in the data is preferable to
noisy/incorrect data.** The implementation should not try to interpolate
or guess a reasonable value during warm-up — it should publish nothing
(or an explicit "warming up" status) until sensors have stabilized.

This is a design-of-failure-mode signal: the farmer would rather see a
missing-data indicator in MC than a wrong-looking value, because the
wrong value actively erodes their trust in the whole system.

## Suggested implementation (from original 999.8 note)

- `control_loop` early-return until:
  - `_humidity_buffer` is full AND
  - ≥20s wall-clock elapsed since boot
- New `startup_grace_period` config parameter (default 20s or until
  buffer-full, whichever is longer)
- During grace period: don't publish actuator commands; either suppress
  sensor publishes entirely or publish with a `warming_up=true` flag so
  MC can show a distinct visual state

**Touches:** `fc_controller.py`, `fc_config.yaml`, `test_controller.py`,
possibly `fc_sensors.py` if we suppress sensor publishes too.

## MC/UX followup (separate phase or bundle)

MC should visibly indicate the warm-up state rather than just going
blank — consistent with the farmer's "bigger gap > noise" preference,
but ideally annotated ("sensors warming up, X seconds remaining") so
the gap is legible rather than alarming.
