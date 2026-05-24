---
created: 1779999000
title: Mission Control — VPD + water-volume + digital-twin link + runtime config buttons (ship to Zoy)
area: mission-control
files:
  - src/openmct/  # (or wherever the OpenMCT dashboard configs live)
  - src/bridge/   # (likely needs a new telemetry channel + write-path for config buttons)
  - src/simulation/  # digital twin / Gazebo chamber model
---

## Idea (captured 2026-05-24 from Santi)

> "negative vapour pressure display and a few buttons would be a natural addition for MC next release — and they aren't gated i believe?"
>
> (follow-up) "yes VPD is what i meant. also estimated water volume. also link to digital twin of chamber — now that we have the real deal to model! ha. GUI can be sent to Zoy for rolling in their farmer app. for now expose simple runtime configuration values."

Four pieces, all candidates for the next Mission Control increment. GUI artifact is intentionally **handoff-shaped** — built so Zoy (farmer #2) can roll it into the farmer-facing app.

### 1. VPD display (confirmed)

Vapor pressure deficit panel. The chamber already publishes the inputs (`fc1/temperature`, `fc1/humidity`).

- Compute VPD from temperature + RH (client-side or in bridge — open question).
- Display alongside current temp/humidity panels in MC.
- Standard mushroom-grow VPD ranges: ~0.4-0.8 kPa for fruiting; expose target band in config if/when farmer requests.

### 2. Estimated water volume

Running total of humidifier water consumption (chamber-level). Inputs likely available:
- Humidifier duty cycle (`fc1/actuators/humidifier`) — already a ROS topic.
- Calibration constant (mL/sec of on-time) — needs a one-time bench measurement on fc1's actual humidifier OR a name-plate guess to start.

Output: a "water used today / since reset" counter on MC, plus an alert hook for "tank likely empty" (separate phase — note here, don't scope-creep).

### 3. Link to digital twin of chamber

Live link from MC to the Gazebo simulation. Now that there's real chamber data, the sim becomes a model that can be calibrated, not just a development scaffold.

Initial scope (minimal): a clickable link or embedded view that opens the digital twin and shows the current chamber state side-by-side with the real one. Future scope (out of this todo): drive sim from real telemetry → divergence detection / predictive control.

### 4. Runtime configuration buttons (the "few buttons")

For now, **expose simple runtime config values** — not raw actuator overrides. Lower bridge complexity, lower farmer-foot-gun risk. Candidates:
- RH target (currently runtime ros2 param, see memory `[[feedback_humidity_runtime_param]]`)
- RH tolerance / operating band
- Light schedule on/off times
- Temperature target
- (later, when bridge has write-path) actuator overrides — humidifier/fan/lights manual on/off

Pattern: each button is "set this config value" (ros2 param set + commit), not "fire this actuator." Keeps it within the existing config-edit-then-deploy mental model the farmer already has, just with fewer steps.

**Master chamber on/off switch** (Santi follow-up): a single top-level "chamber active / chamber paused" toggle that gates all actuators at once — humidifier, fan, lights. Pause-state should be visible across MC + alerter (so alerter doesn't fire "chamber uncontrolled" alarms while operator-paused). Pattern: a ROS-level `chamber_active` boolean param read by `fc_controller.py` before any actuator command goes out; alerter subscribes to the same and suppresses chamber-dark / pi-offline-style alarms when paused. **Caveat:** this is one of the higher-blast-radius buttons — needs a confirm-dialog gate ("Pause chamber? Crop will drift.") and probably an auto-resume timeout (e.g. "pause for 1h / 4h / 24h / indefinite") so a forgotten pause doesn't silently brick the chamber.

## Gating

Santi believes "not gated." Confirm:
- No farmOS/Signal/extraction dependency — yes, this is pure MC scope.
- Does require: (a) deciding whether VPD is computed in bridge vs. client, (b) confirming write-path exists in bridge for buttons (otherwise that part IS gated on a small bridge addition).

## Effort estimate

- VPD display alone: small (~1 day) — derived metric, OpenMCT panel config.
- Buttons: medium — depends on bridge write-path readiness; could be 1-3 days.

## Next step before promoting to a phase

Quick spike: does the bridge have command/service write path today, or only telemetry read? Determines whether buttons are "small" or "requires a bridge plan first."

## Cross-refs

- Memory `[[project_openmct_dashboard]]` — Mission Control stack (bridge + Timescale + OpenMCT)
- Memory `[[project_co2_unexpected_win]]` — CO2 panel was a surprise farmer-favorite; VPD likely similar
- Memory `[[feedback_no_sparklines]]` — annotated event timeline preferred over sparklines
