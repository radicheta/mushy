# Seeds — dormant ideas awaiting trigger conditions

Seeds are forward-looking ideas captured during other work, with explicit
trigger conditions that surface them at the right moment. Not on the active
roadmap; promote via `/gsd:plant-seed` workflow when a trigger fires.

## Active seeds

| ID       | Title                                              | Trigger                                                                  | Scope         |
|----------|----------------------------------------------------|--------------------------------------------------------------------------|---------------|
| SEED-001 | Lightweight runtime config delivery                | Multi-chamber, config mgmt, operational tooling, or Pi fleet work        | Medium        |
| SEED-002 | FarmOS event writer from captured Signal content   | After Phase 25 ships AND ≥2 weeks of captured farmer content exist       | Medium-to-Large |
| SEED-003 | Farmer app "Mission Control" section (→ OpenMCT)   | Zoy starts farmer-app sectioning work OR farmer asks for engineer view   | Small         |
| SEED-004 | Pinning is a cycle, not a setpoint — mode schema needs bands + VPD | Phase 28 discuss-phase entry (mode primitive); also relevant to 30/31/999.33/999.34 | Medium |
| SEED-005 | Chamber water-mass observer + condensation camera macro | VPD scoping decision OR Phase 31 surfaces sensor-saturation pain | Medium |

## Files

- [SEED-001-runtime-config-delivery.md](SEED-001-runtime-config-delivery.md)
- [SEED-002-farmos-event-writer.md](SEED-002-farmos-event-writer.md)
- [SEED-003-farmer-app-mission-control-section.md](SEED-003-farmer-app-mission-control-section.md)
- [SEED-004-pinning-cycle-and-vpd-mode-schema.md](SEED-004-pinning-cycle-and-vpd-mode-schema.md)
- [SEED-005-chamber-water-mass-observer.md](SEED-005-chamber-water-mass-observer.md)

## Composition notes

- **SEED-002 + SEED-003** together define the farmer-app nav: **Field Notes**
  (Phase 25 capture surface), **Daily Summary + Events** (existing + SEED-002
  writes), **Mission Control** (SEED-003 door to OpenMCT).
- **SEED-001** is independent of the farmer-app thread and composes with
  multi-chamber work (Phase 999.6) or PID tuning (Phase 999.9).
- **SEED-004** extends the RH(t) groundwork (memory `project_dynamic_rh_target_groundwork`,
  Phase 999.23) along two new axes — band shape (asymmetric / passive ride) and
  VPD as the underlying variable. Surfaces at Phase 28; cross-cuts 30, 31,
  999.27 (derived VPD telemetry), 999.33 (twin sim), 999.34 (SHT30 heater).
