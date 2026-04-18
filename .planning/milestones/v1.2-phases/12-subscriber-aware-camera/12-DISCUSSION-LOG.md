# Phase 12: Subscriber-Aware Camera - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-13
**Phase:** 12-subscriber-aware-camera
**Areas discussed:** Rate configuration, Disconnect grace period, Idle trickle vs silent, Config parameters

---

## Area Selection

User delegated area selection: "pick sensibly" — all four identified gray areas were resolved by Claude with user confirmation.

## Active Frame Rate

| Option | Description | Selected |
|--------|-------------|----------|
| 1 fps | Live enough to check chamber, ~1-2 MB/min over 4G | ✓ |
| 2 fps | Smoother but doubles data usage | |
| 5 fps | Near-video feel, high data cost | |

**User's choice:** 1 fps (confirmed via "yeah")
**Notes:** None

## Disconnect Grace Period

| Option | Description | Selected |
|--------|-------------|----------|
| Immediate | Drop to idle the instant subscriber count hits 0 | |
| 5 seconds | Survives page refresh without cycling | ✓ |
| 30 seconds | Very conservative, wastes some data | |

**User's choice:** 5 seconds (confirmed)
**Notes:** Configurable via fc_config.yaml

## Idle Trickle vs Silent

| Option | Description | Selected |
|--------|-------------|----------|
| Trickle at 1/min | Current rate, 1440 frames/day | |
| Trickle at 1/hour | 24 frames/day, 60x less data than current | ✓ |
| Silent (0 fps) | No capture when idle — Phase 13 would need separate mechanism | |

**User's choice:** 1 frame/hour
**Notes:** User correction — "idle trickle can be lower, 1 frame per hour". Phase 13 still gets 24 frames/day.

## Config Parameters

| Option | Description | Selected |
|--------|-------------|----------|
| Just active_fps | Minimal addition | |
| active_fps + grace_sec | Two new params, reuse camera_fps as idle | ✓ |
| Full suite (idle, active, poll, grace) | Most flexible but more config surface | |

**User's choice:** Two new params (camera_active_fps, camera_subscriber_grace_sec), reuse camera_fps as idle rate
**Notes:** None

## Claude's Discretion

- Timer swap implementation details
- Logging verbosity for rate transitions
- Whether to capture immediately on ramp-up
- Test structure for subscriber-aware behavior

## Deferred Ideas

None
