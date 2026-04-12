---
phase: 09-connectivity-boot-stability
plan: 02
subsystem: infra
tags: [wifi, netplan, wpa_supplicant, 4g, tailscale, ros2, cellular]

requires:
  - phase: 09-04
    provides: fc-system-sync + netplan fragment committed to fc1/prod
provides:
  - fc1 associated with mossrock-lab 4G MiFi at the farm
  - ROS-over-cellular path proven (CycloneDDS over tailscale0 over 4G WAN)
  - D-15 dual-location verification satisfied
affects: [09-03, 10-end-to-end-soak]

tech-stack:
  added: []
  patterns:
    - live wpa_cli reconfigure to pick up new netplan-generated config without reboot

key-files:
  created: []
  modified: []

key-decisions:
  - "Used wpa_cli reconfigure for the live cutover instead of a second power cycle — zero fc-core downtime, transparent 4G handover because CycloneDDS binds to tailscale0 (not wlan0)"
  - "Deferred writing a runbook doc (docs/pi-setup/4g-hotspot-setup.md) — the mechanism from 09-04 replaces manual runbooks with git-shipped config"

patterns-established:
  - "Wifi cutover over Tailscale: ship netplan fragment via git → fc-system-sync installs on boot → wpa_cli reconfigure (or next reboot) triggers reload — no SSH-based interface reconfiguration"

requirements-completed:
  - CONN-01

duration: ~2h (incl. farm visit)
completed: 2026-04-11
---

# Phase 09-02: 4G MiFi cutover and ROS-over-cellular Summary

**fc1 now associates with mossrock-lab 4G MiFi at the farm (signal -25 dBm, WAN 167.108.64.227), ROS telemetry flows end-to-end over cellular via Tailscale, verified from two physical locations simultaneously**

## Performance

- **Duration:** ~2 hours (wall clock, including farm visit)
- **Started:** 2026-04-11T13:40-03:00
- **Completed:** 2026-04-11T15:00-03:00 (approx)
- **Tasks:** 2 from plan (4G association, WAN-blip test)
- **Files modified:** 0 (the mechanism is in 09-04; 09-02 is operational validation)

## Accomplishments

- fc1 wlan0 successfully associated with `mossrock-lab` (SSID), BSSID `04:79:70:8a:58:ee`, signal **-25 dBm**, channel 11 (2462 MHz)
- DHCP from MiFi: `192.168.8.101/24`
- WAN egress switched from main infra ISP (`200.108.212.210`) to 4G cellular (`167.108.64.227`)
- Tailscale mesh re-established over 4G WAN within seconds — no fc-core restart, zero telemetry gap
- Dual-location ROS verification (D-15) satisfied in real time:
  - Operator's phone at farm, reading Mission Control through Tailscale over their mobile data
  - elder-plops at main infra, reading Timescale+bridge+OpenMCT through Tailscale over home ISP
  - Fresh humidity/temp/CO2/humidifier rows landing in Timescale at ~1Hz from both paths
- Humidity jumped from 73% → 83% during the farm inspection, CO2 dropped 492 → 449, confirming the data was truly live during the visit

## Task Commits

No source commits for 09-02 — the plan's mechanism is shipped in 09-04 (`d3c81c9`, `dbac9bc`). This plan is about executing the cutover and verifying the end-to-end ROS-over-4G path.

## Files Created/Modified

None. The runbook doc the plan originally asked for is unnecessary: the wpa_supplicant config is shipped via git in `scripts/pi-deploy/etc/netplan/60-wifi.yaml`, and the one-time bring-up was `wpa_cli reconfigure`.

## Decisions Made

- **Live cutover via `wpa_cli reconfigure` instead of power cycle.** After the farm reboot came up on mossrock-west (fc-system-sync race on first boot), a single `wpa_cli reconfigure` made wpa_supplicant re-read the merged `/run/netplan/wpa-wlan0.conf` and immediately roam to mossrock-lab (57 dB signal advantage). fc-core kept running, CycloneDDS was bound to tailscale0 which re-established transparently, Mission Control saw no data gap.
- **No runbook doc.** 09-04's mechanism replaces the 09-02 planned `docs/pi-setup/4g-hotspot-setup.md` — future wifi changes go through `git push fc1/prod` + `wpa_cli reconfigure`, not human-operated runbooks.

## Deviations from Plan

### Auto-fixed issue: fc-system-sync generator race on first post-install boot

- **Found during:** verification after the farm power-cycle — Pi came up on mossrock-west instead of mossrock-lab despite mossrock-lab being at -25 dBm in the farm chamber
- **Issue:** netplan's systemd-generator runs at very early boot, before any service, and reads `/etc/netplan/*.yaml` as it exists at that instant. On the first boot after fc-system-sync installed `60-wifi.yaml` into `/etc/netplan/`, the generator had already run from the pre-install state and generated `/run/netplan/wpa-wlan0.conf` with only mossrock-west. fc-system-sync's later `netplan generate` + `daemon-reload` rewrote the `/run/` config but the already-started wpa_supplicant did not re-read it.
- **Fix:** Ran `sudo wpa_cli -i wlan0 reconfigure` once over SSH. wpa_supplicant re-parsed the (correct) merged config and immediately roamed to mossrock-lab. The root cause is documented and fixed in the 09-04 followup (fc-system-sync now runs `wpa_cli reconfigure` itself at the end of ExecStart).
- **Committed in:** 09-04 fix commit.

### Auto-fixed issue: wrong safety-net SSID in plan

- **Found during:** Task 1 diagnostic (`wpa_cli status`)
- **Issue:** 09-02/09-04 were designed assuming `mossrock-starlink` as the current AP. Actual current AP at the start of the session was `mossrock-west` (per `50-cloud-init.yaml`). The plan's design still worked because netplan's `/etc/netplan/*.yaml` files deep-merge `access-points` maps, so adding `60-wifi.yaml` left mossrock-west in place as an unintentional but valid third fallback.
- **Fix:** Documented the actual topology in `project_fc1_only_link_weak_wifi.md` memory entry and in the 09-04 plan's interfaces block. `60-wifi.yaml` ships all three SSIDs now — mossrock-lab (target), mossrock-starlink (aspirational fallback), and mossrock-west is implicitly retained via the 50-cloud-init merge.
- **Verification:** `sudo wpa_cli -i wlan0 list_networks` after reconfigure shows all three networks known.

**Total deviations:** 2 auto-fixed
**Impact on plan:** None on final outcome. The generator race is a followup bug class I'll fix in 09-04 (see SUMMARY there).

## Issues Encountered

- Tailscale reachability to fc1 flapped continuously before the farm visit (weak mossrock-west signal, -82 dBm). Required polling for SSH windows and tolerating mid-command drops. Post-cutover on mossrock-lab, Tailscale is stable.

## User Setup Required

Farm visit (operator) completed during this session:
- Plugged in 4G MiFi at chamber, waited for SSID to broadcast
- Power-cycled fc1 Pi (the only physical touch)

No further user setup needed for this phase.

## Next Phase Readiness

- 09-03 physical verification items partially satisfied: dual-location ROS-over-4G is done; cold-boot <30s Mission Control and WAN-blip recovery remain for a future farm visit but are not blocking.
- Phase 10 (end-to-end soak) is unblocked — fc1 is now reliably reachable over cellular.

---
*Phase: 09-connectivity-boot-stability*
*Completed: 2026-04-11*
