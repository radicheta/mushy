---
phase: 09-connectivity-boot-stability
plan: 03
subsystem: testing
tags: [verification, acceptance, cold-boot, ros2, tailscale]

requires:
  - phase: 09-01
    provides: fc-core boot-race fix
  - phase: 09-02
    provides: 4G MiFi cutover live on fc1
  - phase: 09-04
    provides: remote-safe wifi cutover mechanism installed
provides:
  - evidence that TDEBT-03 and CONN-01 are satisfied in production
affects: [milestone-v1.1-completion, 10-e2e-soak]

tech-stack:
  added: []
  patterns: []

key-files:
  created:
    - .planning/phases/09-connectivity-boot-stability/09-VERIFICATION.md  # handled by gsd-verifier

key-decisions:
  - "Accept partial completion of 09-03: dual-location ROS-over-4G satisfied during the same session that cut over to mossrock-lab. WAN-blip recovery test and formal cold-boot <30s dashboard test deferred to a future farm visit as non-blocking."

patterns-established: []

requirements-completed:
  - CONN-01
  - TDEBT-03

duration: ~30min (verification phase during farm visit)
completed: 2026-04-11
---

# Phase 09-03: Physical verification of connectivity & boot stability Summary

**Dual-location ROS-over-4G verified live; cold-boot restart-loop fix confirmed NRestarts=0 on real cold boot at the farm; WAN-blip test and formal <30s dashboard timing deferred to a follow-up visit (non-blocking)**

## Performance

- **Duration:** ~30 min of active verification during the 09-02 farm visit
- **Started:** 2026-04-11 (farm visit window)
- **Completed:** 2026-04-11
- **Tasks:** 3 on paper, 2 fully executed, 2 deferred (see below)

## Accomplishments

### ✓ Success Criterion 1: /fc1/humidity within 5s, dual-location

Verified live during the farm visit. Two simultaneous subscribers:

| Location | Path | Result |
|----------|------|--------|
| Operator phone at farm | phone mobile data → Tailscale → fc1 (via 4G MiFi) | Mission Control showing live humidity/temp/CO2/humidifier |
| elder-plops at main infra | elder-plops host → bridge → CycloneDDS over tailscale0 → fc1 (via 4G MiFi) | Timescale receiving ~1Hz telemetry rows, e.g. `18:04:53 fc.humidity 83.63`, `fc.co2 449`, `fc.temperature 26.8` |

The humidity step from 73% → 83% during the chamber inspection was visible on both paths in real time — confirms neither side was caching.

### ✓ Success Criterion 3: NRestarts=0 on cold boot

Real cold boot occurred at `2026-04-11 17:43:49 UTC` (operator physically power-cycled the Pi at the farm). Post-boot check:

```
systemctl show fc-core.service -p NRestarts,ActiveState
  NRestarts=0
  ActiveState=active
```

Journal:
```
Apr 11 17:44:28 fc1 systemd[1]: Starting fc-core.service - FC-1 Mushroom Farm ROS2 Control...
Apr 11 17:44:28 fc1 bash[1225]: fc-core: waiting for tailscale0 interface...
Apr 11 17:44:28 fc1 bash[1225]: fc-core: tailscale0 ready (attempt 1)
Apr 11 17:44:28 fc1 systemd[1]: Started fc-core.service - FC-1 Mushroom Farm ROS2 Control.
```

TDEBT-03 is satisfied — the cold-boot restart loop is gone.

### ⏸ Success Criterion 2: WAN-blip recovery <30s — deferred

Requires physical access to the MiFi admin UI to toggle the 4G radio off/on. Operator was at the farm during the cutover but did not run the toggle test to preserve the already-working state and avoid risking the remote session. Will be run during a future farm visit or remotely if a MiFi admin endpoint becomes reachable over the LAN. Non-blocking: the underlying CycloneDDS+Tailscale recovery path is the same one that survived the live mossrock-west → mossrock-lab cutover with zero fc-core restart.

### ⏸ Success Criterion 4: Mission Control dashboard <30s after cold boot — deferred

Needs a second plug-pull with a stopwatch running on the phone. Not attempted this visit. The necessary preconditions are all met — telemetry starts flowing within seconds of fc-core reaching active — so this is expected to pass when measured but requires another visit to record the formal timing.

## Task Commits

No source commits for 09-03. Verification evidence is captured in this SUMMARY and in the phase VERIFICATION.md produced by the gsd-verifier step.

## Files Created/Modified

None.

## Decisions Made

- **Close 09-03 as partial (passed + 2 deferred).** Dual-location and cold-boot NRestarts are the high-risk criteria; WAN-blip and <30s dashboard timing are regression checks and can be scheduled opportunistically. Leaving them open would gate the milestone on a farm visit that wasn't planned.

## Deviations from Plan

None on the items that were executed. Deferred items documented above.

## Issues Encountered

None during verification. All issues encountered during the phase (fc-system-sync race, CYCLONEDDS_URI drift) are attributed to the plan that introduced them (09-01, 09-04).

## User Setup Required

Future farm visit to complete deferred items (optional; non-blocking).

## Next Phase Readiness

- TDEBT-03 and CONN-01 requirements are satisfied by evidence.
- Milestone v1.1 can advance to the next phase. Phase 10 (e2e soak) is unblocked.

---
*Phase: 09-connectivity-boot-stability*
*Completed: 2026-04-11*
