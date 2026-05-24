---
created: 1779999000
title: Mission Control — add VPD display + a few control buttons
area: mission-control
files:
  - src/openmct/  # (or wherever the OpenMCT dashboard configs live)
  - src/bridge/   # (likely needs a new telemetry channel for VPD if not derived client-side)
---

## Idea (captured 2026-05-24 from Santi)

> "negative vapour pressure display and a few buttons would be a natural addition for MC next release — and they aren't gated i believe?"

Two pieces, both candidates for the next Mission Control increment:

### 1. VPD ("negative vapour pressure") display

Read as: vapor pressure deficit (VPD) display panel. Worth confirming whether the framing is literally VPD (Tair, Tleaf, RH → deficit in kPa) or something else (negative pressure ventilation? sub-atmospheric chamber state?). Default working assumption: **VPD**, since it's the standard mushroom-fruiting-environment derived metric and the chamber already publishes the inputs (`fc1/temperature`, `fc1/humidity`).

- Compute VPD from temperature + RH (client-side or in bridge — open question).
- Display alongside current temp/humidity panels in MC.
- Standard mushroom-grow VPD ranges: ~0.4-0.8 kPa for fruiting; expose target band in config if/when farmer requests.

### 2. "A few buttons"

Open-ended — Santi to clarify which control surfaces. Likely candidates from prior conversations:
- Humidifier on/off override
- Fan PWM nudge (+/-)
- Lights on/off override
- "Refresh now" / "force re-sample" trigger

These would need write-path wiring through the bridge → ROS2 services on fc1. Verify the existing bridge has a write path (most current MC is read-only).

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
