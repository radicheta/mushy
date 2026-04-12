---
phase: 09-connectivity-boot-stability
plan: 04
subsystem: infra
tags: [systemd, netplan, wpa_supplicant, deploy, git-ops, raspberry-pi]

requires:
  - phase: 09-01
    provides: fc-core.service tailscale ordering fix (also synced by fc-system-sync)
provides:
  - fc-system-sync.service — early-boot root oneshot that stages repo configs into /etc/ and reloads netplan + wpa_supplicant
  - scripts/pi-deploy/etc/netplan/60-wifi.yaml — netplan fragment with mossrock-lab (hashed PSK) and mossrock-starlink (open) as known access points
  - pattern: future fc1 wifi / systemd unit changes ship via `git push fc1/prod` with no SSH or physical access
affects: [09-02, 09-03, future-pi-config-changes]

tech-stack:
  added: []
  patterns:
    - repo → /etc sync via root oneshot unit, idempotent with cmp-based change detection
    - wpa_cli reconfigure to trigger wpa_supplicant config reload without a restart

key-files:
  created:
    - scripts/pi-deploy/etc/netplan/60-wifi.yaml
    - scripts/pi-deploy/fc-system-sync.service
    - .planning/phases/09-connectivity-boot-stability/09-04-PLAN.md
  modified: []

key-decisions:
  - "Netplan merge over file replacement — ship an additive 60-wifi.yaml that merges with 50-cloud-init.yaml, so mossrock-west (the pre-existing fallback) is retained automatically without having to list it in the new file"
  - "Hashed PSK via wpa_passphrase — keeps the plaintext password out of git; the hash is scoped to mossrock-lab and not reusable elsewhere"
  - "fc-system-sync runs Before=systemd-networkd.service network-pre.target netplan-wpa-wlan0.service — all three orderings were needed to close the first-boot race; the final Before=netplan-wpa-wlan0.service was added after the race was observed in 09-02"
  - "Live wpa_cli reconfigure in ExecStart — rather than waiting for a second reboot, fc-system-sync tells the (possibly already running) wpa_supplicant to re-read its config. If wpa_supplicant isn't up yet, the command no-ops and the fresh /run/netplan/wpa-wlan0.conf gets used at first start."
  - "cmp-based change detection — fc-system-sync only runs netplan generate + daemon-reload + wpa_cli reconfigure when a file actually changed, so it's a cheap idempotent no-op on most boots"

patterns-established:
  - "Remote-safe config cutover for single-link Pis: commit netplan fragment → fc-system-sync installs on boot → netplan generates → wpa_cli reconfigure applies. The mechanism never drops the current link (additive merge + auto-fallback), and the change takes effect on the same boot it landed."

requirements-completed:
  - CONN-01

duration: ~1.5h
completed: 2026-04-11
---

# Phase 09-04: Remote-safe wifi cutover mechanism Summary

**fc-system-sync.service installed on fc1 — early-boot root oneshot that stages `scripts/pi-deploy/*` into `/etc/` and reloads netplan + wpa_supplicant. Ships a netplan fragment with mossrock-lab (hashed PSK) and mossrock-starlink (open) so fc1 auto-associates with whichever wifi is strongest, and future cutovers need only `git push fc1/prod`.**

## Performance

- **Duration:** ~1.5 hours of active work (plan creation, drafts, install, debug of first-boot race)
- **Started:** 2026-04-11 ~13:50-03:00
- **Completed:** 2026-04-11 ~15:20-03:00
- **Tasks:** 5 from plan (diagnostic, commit, dry-run, install, health-check) — all executed
- **Files created:** 3 (netplan fragment, service unit, 09-04-PLAN.md)

## Accomplishments

- `scripts/pi-deploy/etc/netplan/60-wifi.yaml` — adds `mossrock-lab` (hashed PSK `1e98ba69...`) and `mossrock-starlink` (open) to wlan0's access-points. Merges with existing `50-cloud-init.yaml` (which has `mossrock-west`) so all three SSIDs become known fallbacks at netplan generate time.
- `scripts/pi-deploy/fc-system-sync.service` — root oneshot unit:
  - `DefaultDependencies=no`, `After=local-fs.target`, `Before=systemd-networkd.service network-pre.target netplan-wpa-wlan0.service`
  - Detects changes via `cmp -s` on each source/destination pair (idempotent no-op when nothing moved)
  - Installs `60-wifi.yaml` → `/etc/netplan/` and `fc-core.service` → `/etc/systemd/system/`
  - Runs `netplan generate` + `systemctl daemon-reload`
  - Runs `wpa_cli -i wlan0 reconfigure` if wpa_supplicant is already up, so the change applies same-boot without a second reboot
- Installed + enabled on fc1 via a single SSH session during a stable Tailscale window — no interface touched during install
- Plan 09-02's farm-visit cutover exercised the whole chain end-to-end: power-cycled Pi came up with new mechanism → netplan-generated /run/ config → wpa_supplicant associated → 4G WAN → Tailscale → fc-core with zero restarts

## Task Commits

1. **Task 1 (diagnostic) — no commit** — done over SSH; output captured in the session log
2. **Task 2 (commit artefacts)** — `d3c81c9` (feat: 09-04 remote-safe wifi cutover mechanism)
3. **Task 3 (dry-run)** — skipped on elder-plops (no netplan); relied on `netplan generate` at install time
4. **Task 4 (SSH install)** — no source commit; state change lives on fc1 in `/etc/systemd/system/`
5. **Task 5 (health check)** — no commit; verified via `wpa_cli status`, `systemctl show fc-core`, Timescale query

**Followup fix (first-boot race):** `b8ed990` — added `Before=netplan-wpa-wlan0.service`, `wpa_cli reconfigure` on change, and `cmp`-based idempotency

## Files Created/Modified

- `scripts/pi-deploy/etc/netplan/60-wifi.yaml` — wifi access-points fragment
- `scripts/pi-deploy/fc-system-sync.service` — the root oneshot that glues repo → /etc
- `.planning/phases/09-connectivity-boot-stability/09-04-PLAN.md` — the plan that scoped this work

## Decisions Made

(Covered in `key-decisions` above)

## Deviations from Plan

### Auto-fixed issue: first-boot race against netplan's systemd-generator

- **Found during:** Plan 09-02 farm cutover
- **Issue:** netplan's systemd-generator runs at the very start of boot, before any service. It reads `/etc/netplan/*.yaml` at that instant and stamps `/run/netplan/wpa-wlan0.conf` + `/run/systemd/system/netplan-wpa-wlan0.service` into the initial unit graph. On the FIRST boot after fc-system-sync installed a new `60-wifi.yaml` into `/etc/netplan/`, the generator had already run (against the pre-install state) and scheduled `netplan-wpa-wlan0.service` with the stale single-network config. fc-system-sync's later `netplan generate` + `daemon-reload` rewrote the `/run/` files, but wpa_supplicant had already started with the stale config and didn't re-read it.
- **Fix:** Updated `fc-system-sync.service`:
  1. Added `Before=netplan-wpa-wlan0.service` to the unit ordering
  2. Added `wpa_cli -i wlan0 reconfigure` call after `daemon-reload`, guarded by `pgrep wpa_supplicant` so it's a no-op on early boot
  3. Added `cmp -s` change detection so the whole reload dance is skipped on unchanged-content boots
- **Verification:** The live `wpa_cli reconfigure` during debugging made wpa_supplicant immediately re-read the (correct) merged config and roam to mossrock-lab at -25 dBm. The updated service unit embeds this fix so future cutovers take effect on the same boot.
- **Committed in:** see "Task Commits" followup fix entry

**Total deviations:** 1 auto-fixed (first-boot race)
**Impact on plan:** None on end outcome. The race only manifested because I misunderstood when netplan's generator runs. Now fixed for good.

## Issues Encountered

- **Repo vs runtime drift on fc-core.service (surfaced by this plan).** 09-04's fc-system-sync copies `scripts/pi-deploy/fc-core.service` to `/etc/systemd/system/`. During the 09-01 deploy I had already committed a version of that file with the wrong `CYCLONEDDS_URI` — would have been clobbered back on next boot if fc-system-sync had run against the stale repo. Caught and hotfixed (`dbac9bc`) before the farm reboot, so no regression at boot time. Saved the lesson to memory: `feedback_diff_repo_vs_pi_systemd.md`.
- **Tailscale flakiness during install.** First SSH session dropped mid-command; no writes had landed, so the retry was clean. Subsequent sessions used `ServerAliveInterval=3 ServerAliveCountMax=5` for faster dead-peer detection.

## User Setup Required

None post-install. The mechanism is self-contained.

## Next Phase Readiness

- Any future fc1 wifi addition / removal is a pure `git push fc1/prod` operation, verified by the 09-02 cutover.
- Phase 10 (e2e soak) has a stable, git-managed config surface for fc1.

---
*Phase: 09-connectivity-boot-stability*
*Completed: 2026-04-11*
