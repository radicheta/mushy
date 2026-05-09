# Phase 26: Dual sensor publishing + offline alarms — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-20
**Phase:** 26-dual-sensor-publishing-offline-alarms-sht30-scd41-slot-topic
**Areas discussed:** Slot 1 fallback semantics, Offline alert threshold

---

## Slot 1 fallback semantics

Question: When SHT30 drops, does slot 1 silently fall through to SCD41 (current code), or publish nothing so the gap is visible (forcing consumers to read slot 2 explicitly)?

| Option | Description | Selected |
|--------|-------------|----------|
| Silent fallback | SCD41 values publish on `fc1/humidity` / `fc1/temperature` with no flag (current behavior) | ✓ |
| Visible gap | Stop publishing slot 1 when SHT30 drops; consumers must look at slot 2 | |

**User's choice:** Silent fallback.
**Notes:** Keeps the ±1% RH control loop fed without requiring controller-side changes in this phase.

---

## Offline alert threshold

Question: How long without a reading before Signal fires, and should recovery send a second message?

| Option | Description | Selected |
|--------|-------------|----------|
| 5 minutes | Alert after 5 min of no fresh readings from a physical sensor | ✓ |

**User's choice:** 5 minutes.
**Notes:** Recovery message on resume locked in by Claude's discretion (symmetric with existing alerter behavior for `pi_liveness` / `sensor_health`).

---

## Claude's Discretion

- Offline detection mechanism (extend Pi-side `sensor_health` vs alerter-side topic-silence watchdog vs both)
- Cooldown / dedup policy (reuse existing alerter patterns)
- Which downstream consumers need slot 2 surfaced

## Deferred Ideas

- Per-slot `sensor_source` telemetry flag
- Cross-sensor drift detection
- SCD41 RH bias correction

## Scope Note

User pushed back on an initial 5-area gray-area menu as overcomplicated. Scope reduced to the two genuinely ambiguous decisions (slot 1 fallback behavior, alert threshold). Topic naming (`_2` suffix), alert channel (Signal), and detection locus (existing `sensor_health` + alerter) were treated as already-decided per ROADMAP wording and prior phase infrastructure.
