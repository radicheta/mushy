# Phase 2: Safety Hardening - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-30
**Phase:** 02-safety-hardening
**Areas discussed:** Spike rejection, Config cleanup scope, Sensor error handling

---

## Spike Rejection

| Option | Description | Selected |
|--------|-------------|----------|
| Delta threshold | Reject reading if change > X% from previous sample | |
| Rolling median | Keep N-sample buffer, publish median | ✓ |
| N-of-M consecutive | Accept only if confirmed by 2 of last 3 reads | |
| Rolling average | Keep N-sample buffer, publish average | (discussed, rejected) |

**User's choice:** Rolling median, 5-sample window, filter in `fc_controller.py`

**Notes:** User observed the humidity curve on OpenMCT looks noisy. Raised rolling average as an alternative — decided median is better because average is skewed by spikes (a spike of 95% vs true 70% takes the whole window to flush). "Filter lives in controller — seems more honest" (sensors publish truth, controller decides what to act on).

---

## Config Cleanup Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Strict fix | Add `humidifier_pin: 17` only | |
| Clean sweep | Add humidifier_pin, remove dht_pin, update SHT30 comments | |
| Clean sweep + SHT30 params | Same + add `sht30_i2c_address: 0x44` to yaml | ✓ |

**User's choice:** Option 3 — full cleanup including missing SHT30 params

**Notes:** No additional context provided.

---

## Sensor Error Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Keep it simple | Log every error at ERROR, skip sample | ✓ |
| Consecutive failure counter | Warn after N consecutive failures | |
| Failure rate logging | Log every Nth error to avoid spam | |

**User's choice:** Keep it simple

**Notes:** No additional context provided.

---

## Claude's Discretion

None — all areas had clear user decisions.

## Deferred Ideas

None.
