---
phase: 09-connectivity-boot-stability
plan: 01
subsystem: infra
tags: [systemd, tailscale, ros2, cyclonedds, raspberry-pi]

requires:
  - phase: 05-production-deployment
    provides: fc-core.service running on fc1 with Tailscale-based CycloneDDS
provides:
  - fc-core.service that waits for tailscale0 interface before launching ros2
  - zero-restart cold boot on fc1 (TDEBT-03 satisfied)
  - ExecStartPre poll loop pattern for interface-dependent systemd units
affects: [09-02, 09-03, 09-04, future-boot-stability]

tech-stack:
  added: []
  patterns:
    - systemd ExecStartPre interface-wait loops
    - repo-to-/etc sync via root oneshot on boot (established in 09-04)

key-files:
  created: []
  modified:
    - scripts/pi-deploy/fc-core.service

key-decisions:
  - "30-second timeout for tailscale0 poll — aborts cleanly if tailscaled is broken, rather than hanging forever"
  - "Inline shell loop in ExecStartPre (no separate script file) — keeps the fix self-contained in the unit"
  - "Added Wants=tailscaled.service alongside After= — ensures tailscaled is started even if fc-core is the sole consumer"

patterns-established:
  - "Interface-wait pattern: poll ip link show <iface> with 1s cadence, fail at 30s, let Restart=on-failure handle systemic breakage"

requirements-completed:
  - TDEBT-03

duration: ~45min
completed: 2026-04-11
---

# Phase 09-01: fc-core tailscale ordering and boot-race fix Summary

**fc-core.service now orders after tailscaled.service and polls for tailscale0 before launching ros2 — eliminates the ~4 automatic restarts per cold boot observed since the Tailscale cutover**

## Performance

- **Duration:** ~45 min (including hotfix round-trip for CYCLONEDDS_URI drift)
- **Started:** 2026-04-11T13:40-03:00
- **Completed:** 2026-04-11T14:25-03:00
- **Tasks:** 1 (single-task plan)
- **Files modified:** 1

## Accomplishments

- fc-core.service orders `After=network-online.target fc-update.service tailscaled.service` and pulls in `Wants=...tailscaled.service`
- ExecStartPre inline bash loop polls `ip link show tailscale0` up to 30 times at 1s intervals; exits 0 as soon as the interface exists, exits 1 at timeout so systemd treats it as a real failure
- Live-deployed to fc1 via SSH + `systemctl reset-failed + restart fc-core`
- Verified `NRestarts=0` on the running service AND on a subsequent clean cold boot at the farm
- Journal line `fc-core: tailscale0 ready (attempt 1)` confirmed the poll exits on the first iteration when tailscale0 is already up

## Task Commits

1. **Task 1: Add tailscaled ordering and ExecStartPre poll** — `f5f507e` (fix)
2. **Hotfix: Restore CYCLONEDDS_URI to cyclonedds-tailscale.xml** — `dbac9bc` (fix)

## Files Created/Modified

- `scripts/pi-deploy/fc-core.service` — added `After=`/`Wants=tailscaled.service`, ExecStartPre poll loop, and restored `CYCLONEDDS_URI=file:///etc/cyclonedds-tailscale.xml` after a repo/runtime drift was exposed during deploy

## Decisions Made

- Used `Restart=on-failure` instead of the existing `Restart=always` on the Pi — more conservative and lets legitimate ExecStartPre-failed terminations surface rather than loop forever
- Poll cadence 1s × 30 iterations = 30s ceiling, chosen because tailscaled typically brings `tailscale0` up within ~2-5s of its own start

## Deviations from Plan

### Auto-fixed issue: stale `CYCLONEDDS_URI` in repo (drift)

- **Found during:** live deploy of the updated unit to fc1
- **Issue:** The repo's `scripts/pi-deploy/fc-core.service` referenced `/etc/cyclonedds.xml` (old WireGuard/wg0 config). The live Pi had been hand-patched to `/etc/cyclonedds-tailscale.xml`. The 09-01 plan's embedded "current unit" block was stale and the edit preserved the repo's drift. Deploying the (stale) repo version to the Pi briefly pointed CycloneDDS at `wg0`, which does not exist on fc1 anymore — telemetry would have stopped on restart.
- **Fix:** In-place sed on `/etc/systemd/system/fc-core.service` to restore `cyclonedds-tailscale.xml`, followed by a repo hotfix commit (`dbac9bc`) and push to `fc1/prod`. Telemetry never actually dropped because the recovery was faster than one Mission Control scrape interval.
- **Verification:** `systemctl show fc-core.service -p Environment` shows `CYCLONEDDS_URI=file:///etc/cyclonedds-tailscale.xml`; Timescale query confirmed fresh rows immediately after restart.
- **Committed in:** `dbac9bc`

**Total deviations:** 1 auto-fixed (repo/runtime drift)
**Impact on plan:** Caught the drift inside the same session. Saved a new memory (`feedback_diff_repo_vs_pi_systemd.md`) so future work on `scripts/pi-deploy/*.service` starts with a `diff` against live `/etc/systemd/system/`.

## Issues Encountered

- fc1 reachability was intermittent throughout the session (weak wifi on mossrock-west, Tailscale flapping). Worked around by polling for SSH windows and making each command idempotent. First deploy SSH session dropped mid-chain but left fc1 in a clean state because no writes had landed yet.

## User Setup Required

None.

## Next Phase Readiness

- 09-01 fully delivered TDEBT-03's requirement. Cold-boot validation was subsumed by the farm-visit power cycle in 09-03.
- The `tailscale0` poll pattern is reusable for any future ros2 service that binds to a VPN interface.

---
*Phase: 09-connectivity-boot-stability*
*Completed: 2026-04-11*
