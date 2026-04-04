# Phase 3: Closed-Loop Control - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-04
**Phase:** 03-closed-loop-control
**Mode:** --auto (all decisions auto-selected)
**Areas discussed:** Config naming, Dwell time, Staleness threshold, Safe state behavior

---

## Config Naming

| Option | Description | Selected |
|--------|-------------|----------|
| Keep existing names | `target_humidity`/`humidity_tolerance` already deployed and readable | ✓ |
| Rename to grower terms | e.g., `humidity_setpoint`/`humidity_deadband` — more precise but breaks config | |

**User's choice:** [auto] Keep existing names (recommended default)
**Notes:** Renaming would break the live FC-1 config. Current names are clear enough for a grower.

---

## Dwell Time

| Option | Description | Selected |
|--------|-------------|----------|
| 300s (5 minutes) | Conservative — chamber needs time to respond to humidity changes | ✓ |
| 120s (2 minutes) | Faster response but risks cycling if chamber is near setpoint | |
| 600s (10 minutes) | Very conservative — may undershoot in dry conditions | |

**User's choice:** [auto] 300s (5 minutes) (recommended default)
**Notes:** SSR-10A can toggle faster physically, but the ultrasonic humidifier + chamber volume means humidity changes take minutes to propagate.

---

## Staleness Threshold

| Option | Description | Selected |
|--------|-------------|----------|
| 10s | 5 missed reads at 2s interval — clear failure signal | ✓ |
| 6s | 3 missed reads — more aggressive, may false-trigger on I2C hiccups | |
| 30s | 15 missed reads — very lenient, humidifier could run 30s on stale data | |

**User's choice:** [auto] 10s (recommended default)
**Notes:** Rolling median buffer holds 5 samples (~10s of data). If no new data arrives in 10s, the buffer is entirely stale.

---

## Safe State Behavior

| Option | Description | Selected |
|--------|-------------|----------|
| OFF + WARN + auto-recover | Humidifier OFF, log warning, resume when fresh data arrives | ✓ |
| OFF + WARN + manual reset | Requires restart to resume — safer but operationally painful | |
| OFF + silent | No logging — hard to diagnose issues | |

**User's choice:** [auto] OFF + WARN + auto-recover (recommended default)
**Notes:** Grower shouldn't need to SSH into the Pi to restart after a transient sensor glitch. Auto-recovery with clear logging is the right balance.

---

## Claude's Discretion

- Exact placement of dwell time check (inside set_humidifier vs control_loop)
- Whether to use a _safe_state_active flag for log deduplication
- Test structure and simulation helpers

## Deferred Ideas

None — discussion stayed within phase scope.
