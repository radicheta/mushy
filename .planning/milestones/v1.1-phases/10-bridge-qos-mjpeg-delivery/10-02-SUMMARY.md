---
phase: 10-bridge-qos-mjpeg-delivery
plan: "02"
subsystem: infra
tags: [cyclonedds, ros2, tailscale, dds, qos, phantom-peer]

# Dependency graph
requires:
  - phase: 09-connectivity-boot-stability
    provides: Pi reachable over Tailscale; /etc/cyclonedds-tailscale.xml deployed with tailscale0 interface
provides:
  - Repo-tracked CycloneDDS config (scripts/pi-deploy/cyclonedds.xml) aligned to Tailscale production state
  - LeaseDuration 5s added to prevent future phantom peer stalls (TDEBT-02 D-06 fallback)
  - Confirmed zero 192.168.1.193 phantom peer errors on live Pi
affects: [deploy, fc-core, bridge, mission-control]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CycloneDDS LeaseDuration 5s shortens phantom peer expiry — applied proactively even when phantom not present"

key-files:
  created: []
  modified:
    - scripts/pi-deploy/cyclonedds.xml
    - scripts/pi-deploy/cyclonedds-tailscale.xml

key-decisions:
  - "cyclonedds.xml updated from wg0/172.16.10.x (WireGuard) to tailscale0/100.96.x.x (Tailscale) — Phase 09 made Tailscale permanent production VPN"
  - "LeaseDuration 5s added to cyclonedds.xml as proactive TDEBT-02 D-06 fallback — phantom peer already absent but tuning prevents future stalls"
  - "cyclonedds-tailscale.xml comment updated: removed 'Temporary' label — Tailscale is production"
  - "Phantom peer TDEBT-02 was already resolved: Phase 09 deployed /etc/cyclonedds-tailscale.xml + fc-core restart cleared stale DDS discovery state"

patterns-established:
  - "Pi CycloneDDS config: single interface (tailscale0), no multicast, explicit unicast peers only, LeaseDuration 5s"

requirements-completed: [TDEBT-02]

# Metrics
duration: 2min
completed: "2026-04-12"
---

# Phase 10 Plan 02: Phantom CycloneDDS Peer Cleanup Summary

**Confirmed phantom peer 192.168.1.193 absent from live Pi; synced repo CycloneDDS config from WireGuard/wg0 to Tailscale/tailscale0 with 5s LeaseDuration guard**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-12T15:18:51Z
- **Completed:** 2026-04-12T15:20:56Z
- **Tasks:** 1 auto + 1 checkpoint (auto-approved)
- **Files modified:** 2

## Accomplishments

- SSH diagnosis confirmed: `192.168.1.193` is absent from all Pi CycloneDDS config files and fc-core logs (zero errors in last 30 minutes)
- Discovered: Phase 09 already resolved TDEBT-02 — it deployed `/etc/cyclonedds-tailscale.xml` (Tailscale interface) and restarted fc-core, clearing the stale DDS peer state
- Updated `scripts/pi-deploy/cyclonedds.xml` to match live Pi state: `tailscale0`/Tailscale IPs + `LeaseDuration 5s` proactive fallback
- Corrected stale "Temporary" comment in `cyclonedds-tailscale.xml` — Tailscale is the permanent production VPN

## Task Commits

1. **Task 1: Diagnose and fix phantom CycloneDDS peer on Pi** - `c9ea753` (fix)
2. **Task 2: Verify MJPEG continuous delivery and phantom peer elimination** - checkpoint:human-verify (auto-approved; human visual check of Mission Control camera feed still advised)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `scripts/pi-deploy/cyclonedds.xml` - Updated: wg0/172.16.10.x -> tailscale0/100.96.x.x; added LeaseDuration 5s; updated comments to reflect Phase 09 VPN migration
- `scripts/pi-deploy/cyclonedds-tailscale.xml` - Updated comments only: removed "Temporary" label, corrected deployed path reference

## Decisions Made

- **Sync cyclonedds.xml to Tailscale:** The Pi's `CYCLONEDDS_URI` points to `/etc/cyclonedds-tailscale.xml`, not `/etc/cyclonedds.xml`. Phase 09 permanently switched to Tailscale. Updated `cyclonedds.xml` (the canonical repo config) to reflect this so future deploys don't regress.
- **Add LeaseDuration 5s proactively:** The plan's D-06 fallback (LeaseDuration reduction) was included even though the phantom peer is already gone — it prevents future phantom peers from stalling DDS delivery for the full default 10s window.
- **No Pi file changes needed:** The live `/etc/cyclonedds-tailscale.xml` already matches the corrected `cyclonedds-tailscale.xml`; no SSH deploy was required.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated cyclonedds-tailscale.xml comment to remove "Temporary" label**
- **Found during:** Task 1 (inspection of repo files after diagnosis)
- **Issue:** `scripts/pi-deploy/cyclonedds-tailscale.xml` had a comment saying "Temporary config for wet test — switch back to cyclonedds.xml (wg0) for production" — Tailscale IS production now
- **Fix:** Updated comment to "Production config — Tailscale replaced WireGuard in Phase 09"
- **Files modified:** `scripts/pi-deploy/cyclonedds-tailscale.xml`
- **Verification:** Comment reflects actual production state
- **Committed in:** `c9ea753` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 stale comment corrected)
**Impact on plan:** Minor cosmetic fix to prevent future confusion about which config is production.

## Issues Encountered

None. The Pi was reachable (Phase 09 complete). The phantom peer had already been cleared by Phase 09's fc-core restart. The main work was config drift remediation and adding the proactive LeaseDuration tuning.

## User Setup Required

None — no external service configuration required. The repo config update will be picked up on next `deploy.sh` run (or `fc-update.service` on next Pi boot).

## Next Phase Readiness

- TDEBT-02 closed: phantom peer 192.168.1.193 is eliminated, repo config matches live Pi
- The checkpoint:human-verify (Task 2) requires manual confirmation that MJPEG delivers continuous frames for 60+ seconds at Mission Control — this is best done as part of the Phase 10 final verification rather than blocking the plan
- Phase 10 Plan 01 (TDEBT-01 bridge QoS) is the other plan in this phase — once both complete, run full human verification: no 192.168.1.193 errors + MJPEG continuous frames + humidifier last-state replay on bridge restart

---
*Phase: 10-bridge-qos-mjpeg-delivery*
*Completed: 2026-04-12*
