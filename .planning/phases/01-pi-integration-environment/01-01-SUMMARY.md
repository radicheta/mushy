---
phase: 01-pi-integration-environment
plan: "01"
subsystem: infra
tags: [ssh, wireguard, raspberry-pi, ubuntu, networking, vpn]

# Dependency graph
requires: []
provides:
  - SSH key-based access to FC-1 Pi (10.68.155.53) via `ssh fc1`
  - SSH setup runbook at docs/pi-setup/ssh-setup.md
  - WireGuard setup runbook at docs/pi-setup/wireguard-setup.md
  - WireGuard deployment script at scripts/pi-deploy/wg-setup.sh
affects:
  - 01-02
  - 01-03
  - all subsequent pi-integration plans

# Tech tracking
tech-stack:
  added: [wireguard, envsubst]
  patterns: [static-ip-via-netplan, ssh-config-host-alias]

key-files:
  created:
    - docs/pi-setup/ssh-setup.md
    - docs/pi-setup/wireguard-setup.md
    - scripts/pi-deploy/wg-setup.sh
  modified: []

key-decisions:
  - "Pi is on 10.68.155.0/24 LAN (not 192.168.88.x as originally planned) — all docs updated to match"
  - "Static IP set via /etc/netplan/99-static.yaml on Pi (DHCP disabled on eth0)"
  - "VPN is prepared but not a Phase 1 blocker per D-07"

patterns-established:
  - "Pi access: ssh fc1 (Host fc1 / HostName 10.68.155.53 / User ubuntu)"
  - "WireGuard template: wg0.conf.template in repo root, envsubst substitution, scripts/pi-deploy/wg-setup.sh to deploy"

requirements-completed: [INFRA-01, INFRA-02]

# Metrics
duration: 15min
completed: "2026-03-29"
---

# Phase 1 Plan 01: SSH + WireGuard Setup Summary

**SSH key-based access to FC-1 Pi on 10.68.155.53 (Ubuntu 24.04) via `ssh fc1`, with WireGuard config template and deployment script prepared for VPN readiness**

## Performance

- **Duration:** ~15 min (continuation agent after human-action checkpoint)
- **Started:** 2026-03-29T15:20:00Z (continuation)
- **Completed:** 2026-03-29T15:34:10Z
- **Tasks:** 2/2
- **Files modified:** 3

## Accomplishments

- SSH runbook updated with real Pi IP (10.68.155.53, subnet 10.68.155.0/24) and confirmed working
- WireGuard setup runbook created documenting all 4 template variables with full troubleshooting section
- WireGuard deployment script created with env var validation, envsubst substitution, and systemd service setup

## Task Commits

Each task was committed atomically:

1. **Task 1: Update SSH runbook with real Pi IP** - `4080e31` (feat)
2. **Task 2: WireGuard docs and deployment script** - `ca8d6de` (feat)

**Plan metadata:** (see final docs commit)

## Files Created/Modified

- `docs/pi-setup/ssh-setup.md` - SSH setup runbook with real IP (10.68.155.53), static IP config method, current Pi state documented
- `docs/pi-setup/wireguard-setup.md` - WireGuard VPN setup runbook with all template variables, deploy steps, verification, and troubleshooting
- `scripts/pi-deploy/wg-setup.sh` - Bash deployment script; validates 4 env vars, runs envsubst on template, writes to /etc/wireguard/wg0.conf, enables/starts wg-quick@wg0

## Decisions Made

- Actual Pi network is 10.68.155.0/24, not the planned 192.168.88.x. All docs updated to the real network.
- Static IP is configured at `/etc/netplan/99-static.yaml` (not the cloud-init file, which can be overwritten on reboot).
- VPN is prepared but explicitly marked as not a Phase 1 blocker (per D-07/D-08). Phase 1 proceeds over LAN SSH.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Network subnet mismatch corrected throughout**
- **Found during:** Task 1 (SSH runbook update — continuation from human-action checkpoint)
- **Issue:** Plan and runbook referenced 192.168.88.x but actual Pi network is 10.68.155.x. All placeholder IPs needed to be replaced with real values.
- **Fix:** Replaced all 192.168.88.x references with 10.68.155.53 / 10.68.155.0/24 / 10.68.155.1 throughout ssh-setup.md. Added current status section documenting live Pi state.
- **Files modified:** docs/pi-setup/ssh-setup.md
- **Verification:** `ssh fc1 "hostname"` returns `fc1` without password prompt
- **Committed in:** `4080e31` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - factual correction, not a code bug)
**Impact on plan:** Required correction — runbook would have been wrong if left with placeholder IPs. No scope creep.

## Issues Encountered

- Plan was interrupted after Task 1 draft by a checkpoint (human-action: SSH access needed to be established manually). This is expected flow per plan type. Continuation agent resumed after SSH was confirmed working.

## User Setup Required

None — no external service configuration required for this plan. WireGuard VPN setup (when desired) is documented in `docs/pi-setup/wireguard-setup.md` and requires filling 4 environment variables before running the deployment script.

## Next Phase Readiness

- SSH access to FC-1 is confirmed and documented: `ssh fc1` works from workstation
- Pi specs confirmed: Ubuntu 24.04.4 LTS, kernel 6.8.0-1047-raspi, Raspberry Pi 4
- WireGuard config prepared — can be deployed when server is accessible
- Ready for Plan 01-02: ROS2 native installation on Pi

---
*Phase: 01-pi-integration-environment*
*Completed: 2026-03-29*

## Self-Check: PASSED

- docs/pi-setup/ssh-setup.md: FOUND
- docs/pi-setup/wireguard-setup.md: FOUND
- scripts/pi-deploy/wg-setup.sh: FOUND
- .planning/phases/01-pi-integration-environment/01-01-SUMMARY.md: FOUND
- Commit 4080e31 (Task 1): FOUND
- Commit ca8d6de (Task 2): FOUND
