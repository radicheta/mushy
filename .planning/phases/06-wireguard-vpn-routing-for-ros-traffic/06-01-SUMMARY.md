---
phase: 06-wireguard-vpn-routing-for-ros-traffic
plan: 01
subsystem: infra
tags: [wireguard, vpn, vpn-mesh, wg-quick, systemd, pfsense]

# Dependency graph
requires:
  - phase: 01-pi-integration-environment
    provides: Pi SSH access confirmed, Ubuntu 24.04 on FC-1, deploy pipeline working
provides:
  - WireGuard installed on FC-1 Pi (wireguard-tools 1.0.20210914)
  - Pi WireGuard keypair at /etc/wireguard/{private,public}.key
  - /etc/wireguard/wg0.conf deployed with LAN endpoint (10.68.155.1:51820) and VPN IP 172.16.10.5/24
  - wg-quick@wg0 systemd service enabled and active
  - Pi public key captured for pfSense peer registration (Plan 02)
  - Updated wg-setup.sh as idempotent on-Pi deploy script
  - Updated wireguard-setup.md with current deployment state
affects: [06-02-pfsense-peer-registration, 06-03-dds-unicast-config]

# Tech tracking
tech-stack:
  added: [wireguard, wireguard-tools-1.0.20210914, wg-quick@wg0.service]
  patterns: [on-pi-idempotent-setup-script, scp-then-ssh-run pattern for Pi deploy]

key-files:
  created: []
  modified:
    - scripts/pi-deploy/wg-setup.sh
    - docs/pi-setup/wireguard-setup.md

key-decisions:
  - "Endpoint is 10.68.155.1:51820 (pfSense LAN IP) — mossrock.space DNS deferred per D-04"
  - "wg-setup.sh rewrote as on-Pi script (sudo bash) rather than workstation-side envsubst template filler"
  - "Keypair generation idempotent — skips if /etc/wireguard/private.key already exists"

patterns-established:
  - "Pi deploy pattern: scp script to /tmp, then ssh fc1 'sudo bash /tmp/script.sh'"
  - "Idempotent setup scripts: check existence before install/generate steps"

requirements-completed: [INFRA-02]

# Metrics
duration: 3min
completed: 2026-03-29
---

# Phase 6 Plan 01: WireGuard Pi Setup Summary

**wireguard-tools installed on FC-1 Pi, keypair generated, wg0.conf deployed with LAN endpoint 10.68.155.1:51820, wg-quick@wg0 service active — Pi public key ready for pfSense peer registration**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-29T20:59:40Z
- **Completed:** 2026-03-29T21:02:58Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- WireGuard installed on FC-1 Pi (wireguard-tools 1.0.20210914, from Ubuntu noble apt)
- Keypair generated at `/etc/wireguard/private.key` + `/etc/wireguard/public.key`, permissions 600
- `/etc/wireguard/wg0.conf` deployed: Address=172.16.10.5/24, Endpoint=10.68.155.1:51820, PersistentKeepalive=25
- `wg-quick@wg0` systemd service enabled and active — confirmed via `sudo wg show wg0`
- `scripts/pi-deploy/wg-setup.sh` rewritten as idempotent on-Pi deploy script (scp + ssh pattern)
- `docs/pi-setup/wireguard-setup.md` updated with current state, deploy method, pfSense peer registration steps

## Pi Public Key (Required for Plan 02)

```
wVYbIBYfptP0uVpAbtk43xLVi75QIGL0yQwgTbMcATA=
```

This key must be added to pfSense in Plan 02:
- pfSense WebGUI: VPN > WireGuard > Peers > Add
- Tunnel: tun_wg0 (mossrock)
- Description: FC-1 Pi
- Public Key: `wVYbIBYfptP0uVpAbtk43xLVi75QIGL0yQwgTbMcATA=`
- Allowed IPs: 172.16.10.5/32
- Dynamic Endpoint: checked

## Task Commits

Each task was committed atomically:

1. **Task 1: Install WireGuard and deploy wg0.conf on FC-1 Pi** - `8d42feb` (feat)
2. **Task 2: Update wireguard-setup.md documentation with LAN endpoint** - `64506b8` (docs)

**Plan metadata:** (see final commit hash below)

## Files Created/Modified

- `scripts/pi-deploy/wg-setup.sh` — Rewritten as idempotent on-Pi WireGuard setup script; installs wireguard-tools, generates keypair, writes wg0.conf, enables service, prints public key
- `docs/pi-setup/wireguard-setup.md` — Updated with Current State section, LAN-only endpoint note, wg-setup.sh as primary deploy method, pfSense peer registration steps; removed mossrock.space references

## Decisions Made

- Endpoint hardcoded as `10.68.155.1:51820` (pfSense LAN IP) per CONTEXT.md D-04 — mossrock.space DNS and ISP port forward deferred to later phase
- `wg-setup.sh` redesigned as an on-Pi script (run via `sudo bash`) rather than workstation-side envsubst template filler — more reliable for hardcoded values, no dependency on workstation having envsubst or the template file accessible
- Config always overwritten (not idempotent for wg0.conf) — ensures correct values on re-run; keypair skipped if already present (idempotent for key generation)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- `test -f /etc/wireguard/wg0.conf` fails without sudo because the file is root-owned chmod 600. Verification uses `sudo test -f` or `sudo grep` — confirmed file exists and correct.
- Locale warnings from apt-get during install (es_UY.UTF-8 not installed on Pi) — cosmetic only, install succeeded.

## Next Phase Readiness

- Pi public key is ready: `wVYbIBYfptP0uVpAbtk43xLVi75QIGL0yQwgTbMcATA=`
- Plan 02 (pfSense peer registration) requires human interaction with pfSense WebGUI — add Pi as peer with the key above
- Tunnel handshake will NOT succeed until Plan 02 is complete — `sudo wg show wg0` currently shows `latest handshake: (none)` which is expected
- After Plan 02: test with `ssh fc1 "ping -c 3 172.16.10.1"` to confirm VPN tunnel established

## Self-Check: PASSED

- scripts/pi-deploy/wg-setup.sh: FOUND
- docs/pi-setup/wireguard-setup.md: FOUND
- 06-01-SUMMARY.md: FOUND
- Commit 8d42feb (Task 1): FOUND
- Commit 64506b8 (Task 2): FOUND

---
*Phase: 06-wireguard-vpn-routing-for-ros-traffic*
*Completed: 2026-03-29*
