# Phase 63: Chamber Alerter - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-13
**Phase:** 63-chamber-alerter
**Areas offered:** Signal I/O + snooze routing, Runtime config + live overrides, Alert FSM state on restart, Detector scope
**Areas discussed:** Runtime config + live overrides
**Areas defaulted (accepted without discussion):** Signal I/O + snooze routing, Alert FSM state on restart, Detector scope

---

## Runtime config + live overrides

### Q1 — Effective-config resolver

| Option | Description | Selected |
|--------|-------------|----------|
| Port full Tier A/B/C resolver | Reproduce `resolveEffectiveConfig` verbatim: live mode-anchored RH target + per-mode + global overrides + freshness gate; detectors consume effective cfg, never raw env. Needed for Phase-64 parity. | ✓ |
| Static env only, defer dynamic | Detectors read static rh_target/rh_band; dynamic override lands later. Simpler but breaks prod parity; would count as a Phase-64 parity failure. | |

**User's choice:** Port full Tier A/B/C resolver.
**Notes:** The dynamic RH target is the live prod behavior (pinning→fruiting setpoint moves) and the parity gate depends on it.

### Q2 — Where the chamber knobs live

| Option | Description | Selected |
|--------|-------------|----------|
| Continue precedent — add to TenantConfig | Add remaining knobs alongside the 7 already there. One config object; no gate violation. | |
| chamber-local ChamberConfig composes TenantConfig | New chamber/config.py holds alerter knobs; reads secrets + shared identity from TenantConfig. Keeps Foray island clean. | ✓ |

**User's choice:** chamber-local ChamberConfig composes TenantConfig.
**Notes:** Keeps the extractable Foray island free of mushy-private alerter concerns.

### Q3 — Fate of the 7 alerter knobs already in TenantConfig

| Option | Description | Selected |
|--------|-------------|----------|
| Move all 7 into ChamberConfig | Relocate rh_target/rh_band/pi_offline_min/sensor_offline_min/heartbeat_hour/max_sends_per_hour/timezone out of TenantConfig. Bigger diff (touches Phase-56 tests) but one clean home. | ✓ |
| Leave the 7, ChamberConfig adds the rest | Smaller diff, but alerter config stays split and TenantConfig keeps mushy-private fields. | |

**User's choice:** Move all 7 into ChamberConfig.
**Notes:** Consistent with the clean-island choice in Q2.

### Q4 — TZ fix implementation (CHM-02)

| Option | Description | Selected |
|--------|-------------|----------|
| ChamberConfig-driven, default Montevideo | Formatting reads ChamberConfig.timezone; default flips Toronto→Montevideo; env TZ overrides; snapshot test pins default. | ✓ (Claude's recommendation, user deferred) |
| Hardcode ZoneInfo('America/Montevideo') | Ignores env TZ; matches literal SC2 wording; removes the knob; diverges from Node's config-driven formatting. | |

**User's choice:** "whatever you recommend" → ChamberConfig-driven, default Montevideo.
**Notes:** Preserves Node's config-driven formatting shape (best parity), keeps the multi-tenant knob. Real fix = route ALL farmer-facing formatting through the configured `ZoneInfo` (legacy `hhmm()` used UTC). Pre-declared as intentional parity delta for Phase 64.

---

## Defaulted areas (not discussed; defaults proposed by Claude, accepted by user)

- **Signal I/O + snooze routing** → reuse `signal_io.client` (outbound) + shared receive_loop/router (inbound snooze); no duplicate Signal client. (CONTEXT D-05)
- **Alert FSM state on restart** → in-memory, Node parity; durable snooze deferred. (CONTEXT D-06)
- **Detector scope** → port all 6 alert types (rh, sensor, pi, humidifier, sht30, scd41). (CONTEXT D-07)

User selected "Ready for context" — accepted all three defaults without re-opening.

## Claude's Discretion

- Async mechanics (asyncio heartbeat loop + ZoneInfo, WS reconnect/backoff, Python structure of the effective-config resolver) — constrained by parity with Node outputs.

## Deferred Ideas

- Durable snooze/cooldown across restart — deferred unless the farmer is bitten (would be a Phase-64 parity delta if added now).
- Node-side Phase-50 quote-rendering bug (todo 2026-05-24) — out of scope; left for Node until Phase-65 cutover.

## Canonical correction captured

- ROADMAP SC3's "chamber has zero imports from non-chamber Foray" is **inverted** vs the real `.lint-imports` gate (Foray↛chamber). Recorded as CONTEXT D-00 so the planner builds against the real seam direction.
