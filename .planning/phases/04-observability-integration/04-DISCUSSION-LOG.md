# Phase 4: Observability & Integration - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-04
**Phase:** 04-observability-integration
**Areas discussed:** Actuator state topic, OpenMCT bridge update, Hardware validation scope

---

## Actuator State Topic

| Option | Description | Selected |
|--------|-------------|----------|
| Just humidifier Bool | ACTR-03 spec says Bool + TRANSIENT_LOCAL. Simple, matches the requirement. | |
| Actuator bundle message | Custom msg with humidifier + fan + light. More info but deviates from spec. | |
| You decide | Claude picks approach matching ACTR-03. | |

**User's choice:** "yeah we want to log all available data. later more sensors will be connected. can live with lower refresh rate btw"
**Notes:** User wants comprehensive logging beyond minimum ACTR-03. Humidifier Bool satisfies the requirement, but all actuator/sensor state should be published for observability. Extensibility for future sensors is important.

---

## OpenMCT Bridge Update

| Option | Description | Selected |
|--------|-------------|----------|
| Full OpenMCT integration | Add CO2 + actuator to both bridge AND OpenMCT plugin. Live charts. | ✓ |
| Bridge only, skip plugin | Just add topics to WebSocket bridge. OpenMCT plugin update can wait. | |
| You decide | Claude picks based on existing code and effort. | |

**User's choice:** Full OpenMCT integration
**Notes:** None — straightforward selection.

---

## Hardware Validation Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Breath test sufficient | Control loop verified. Soak test belongs in Phase 5. | |
| Need soak test first | Run 1+ hours with real humidifier before Phase 4 complete. | ✓ |
| Soak test in Phase 5 | Mark TEST-02 done, add soak requirement to Phase 5. | |

**User's choice:** Need soak test. Blocker: network gap between lab and farm. WireGuard over internet needed.
**Notes:** Pi needs to physically move from lab to farm. Remote SSH via WireGuard over internet (not LAN) is a prerequisite. This is a separate network issue, not Phase 4 scope.

---

## Network Approach (follow-up)

| Option | Description | Selected |
|--------|-------------|----------|
| pfSense port forward | Forward UDP 51820 on WAN. Simplest approach. | |
| Defer — separate issue | Remote access is its own problem. Phase 4 focuses on observability code. | ✓ |
| Other approach | User has something else in mind. | |

**User's choice:** Defer — separate issue
**Notes:** Remote access deferred. Phase 4 delivers the observability code; soak test happens when network is solved.

---

## Claude's Discretion

- QoS profiles for non-actuator observability topics
- OpenMCT chart formatting for CO2 (ppm) and boolean actuator state
- Individual topics vs combined system status endpoint

## Deferred Ideas

- Remote WireGuard over internet for farm access
- Actuator bundle message (rejected in favor of individual topics)
- TimescaleDB telemetry storage wiring
