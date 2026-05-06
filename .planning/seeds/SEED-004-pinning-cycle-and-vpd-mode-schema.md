---
id: SEED-004
status: dormant
planted: 2026-05-06
planted_during: v1.5 Analog Humidity Control (paused behind v1.5.0.1 hotfix)
trigger_when: Phase 28 discuss-phase entry — mode primitive schema design
scope: Medium
---

# SEED-004: Pinning is a cycle, not a setpoint — mode schema must express oscillation, asymmetric bands, and VPD

## Why This Matters

Naïve framing of `pinning` and `fruiting` modes as "different RH setpoints" gets the
agronomy wrong in two ways the existing RH(t) groundwork (memory
`project_dynamic_rh_target_groundwork`, Phase 999.23) does **not** cover:

1. **Pinning is an intra-day oscillation across the dew point**, not a smooth ramp
   between stage targets. The trigger is the cycle: cool surfaces accept condensate
   in the afternoon → warming evaporates it in the morning. Holding a flat high RH
   *suppresses* pinning. The farmer's current plan (2026-05-06) is to ride the
   ambient diurnal temp swing for this; once we have temp control we can drive it
   actively (Phase 31 territory). RH(t) memory covers `step from 90→95 over 6h` —
   it does not cover circadian micro-cycling.

2. **Mode schema must express asymmetric bands and passive ride**, not just a
   target-as-function-of-time. "During pinning, don't fight upward RH excursions"
   is a *behavior*, not a target value. RH(t) memory + 999.23 are silent on band
   shape and on which side of the band the controller actively defends.

3. **VPD is the agronomically meaningful variable** — same RH at different temps
   is not the same chamber. Orthogonal to the time axis: even a flat-target mode
   should be VPD-aware in schema so the loop can re-derive RH setpoint from a
   VPD setpoint later without a config-format migration.

## When to Surface

**Trigger:** Phase 28 discuss-phase entry (mode primitive + `fruiting`/`pinning`
baseline modes + runtime config delivery).

Also relevant for:
- **Phase 30** (time-of-day scheduling) — natural home for the *passive* cycle
  (widen the band overnight, push toward fruiting target during warm hours).
- **Phase 31** (experimental forcing modes `force-condensation` / `force-evaporation`)
  — the *active* version once temp control exists. The pinning cycle is a
  rhythmic, low-amplitude force-condensation/force-evaporation pair.
- **Phase 999.34** (SHT30 heater state machine) — collides directly. The sensor
  heater clears condensation off the sensor; during pinning chamber-condensation
  is desired. Heater behavior must be aware that condensation in the chamber is
  intentional while the sensor must remain readable.
- **Phase 999.33** (digital twin sim) — the cycle is the killer use case for the
  twin. Iterating mode schemas + cycle parameters on real fc1 burns grow cycles;
  the sim makes 28→30→31 cheap to validate.

## Scope Estimate

**Medium** — affects Phase 28 mode schema directly (must accommodate bands,
asymmetry, and VPD-readability without baking RH-only assumptions). VPD as
*derived telemetry* is small (bridge-side `fc_metrics` derivation, composes with
999.27). VPD-*targeted closed-loop control* and active-cycle driving are larger
and properly belong in later phases / 999.33 sim.

## Recommended approach for Phase 28

- Keep PID **RH-targeted** at the loop level for now (don't rewrite the loop the
  same week we ship a new mode primitive).
- Mode struct expresses: `(target, band_low, band_high, defend_side: low|high|both,
  T_target_optional)`. The optional `T_target` lets a future loop derive RH from
  VPD without a schema migration.
- `pinning` mode v0 = wide band, `defend_side: low` (don't suppress upward RH
  excursions when the chamber cools).
- `fruiting` mode v0 = current narrow-band PID behavior.
- Surface VPD as a *derived telemetry channel* via `fc_metrics` so the farmer
  sees it on Mission Control alongside RH (composes with 999.27).
- Defer VPD-targeted control + active cycle driving to 999.33 (twin sim) +
  Phase 31.

## Composes with

- `project_dynamic_rh_target_groundwork.md` (memory, 2026-04-28) and Phase 999.23
  — covers the time-axis (RH-as-function-of-time / current-effective-value
  reading). This seed adds the *band-shape* and *VPD* axes that 999.23 is silent on.
- SEED-001 (runtime config delivery) — mode definitions are exactly the kind of
  config that should swap without redeploy.
- Phase 999.27 (derived telemetry / `fc_metrics` bridge module) — natural home
  for derived VPD.
- Phase 999.33 (digital twin) — validation surface for cycle parameters.
- Phase 999.34 (SHT30 heater state machine) — must coordinate with mode (heater
  off / careful when chamber wants saturation).

## Open questions for Phase 28 discuss

- How do we *measure* condensation today? No surface-temp probe. Proxies:
  SHT30 RH near 100% (with heater state known), SCD41 RH clipping at 100% as a
  binary "saturated" flag (memory says SCD41 RH always clips — finally useful
  here), rate-of-RH-change after a temp drop. IR surface-temp sensor is backlog
  hardware.
- Is `pinning` v0 purely passive (ride the swing, don't fight) or does it need
  any minimum-RH floor below which we *do* humidify (e.g. if outdoor temp swing
  is unusually small and the chamber dries out)?
- How does mode interact with the alerter (Phase 29)? An alerter alarming on
  "RH above target during pinning" would be exactly wrong. Asymmetric bands need
  to propagate to the alerter, not just the controller.

## Breadcrumbs

- Memory: `project_dynamic_rh_target_groundwork.md` (2026-04-28) — RH(t) groundwork
- Phase 999.23 — dynamic RH target (closed by Phase 30 in v1.5)
- Phase 999.27 — derived telemetry / `fc_metrics`
- Phase 999.33 — digital twin chamber sim
- Phase 999.34 — SHT30 heater state machine
- SEED-001 — runtime config delivery (mode swaps without redeploy)
- ROADMAP.md v1.5 section: Phase 28 (mode primitive), 29 (alerter mode awareness),
  30 (time-of-day scheduling), 31 (experimental forcing modes)
