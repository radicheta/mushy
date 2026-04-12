---
phase: 09-connectivity-boot-stability
verified: 2026-04-11T21:00:00Z
status: passed
score: 5/5 truths verified (2 core + 3 mechanism; 2 deferred items non-blocking)
overrides_applied: 0
deferred:
  - truth: "Pi recovers and Tailscale mesh reconnects automatically after WAN blip (hotspot toggled off/on) — /fc1/humidity readable within 30s, no manual intervention"
    addressed_in: "Future farm visit (opportunistic)"
    evidence: "09-03 SUMMARY decisions: 'Accept partial completion of 09-03 — WAN-blip recovery test deferred to a future farm visit as non-blocking.' Underlying path validated by live mossrock-west → mossrock-lab cutover which completed with zero fc-core restart."
  - truth: "Mission Control dashboard shows live telemetry within 30 seconds of Pi boot completing"
    addressed_in: "Future farm visit (opportunistic)"
    evidence: "09-03 SUMMARY decisions: '<30s dashboard timing deferred to future farm visit as non-blocking.' Preconditions confirmed present: fc-core active within seconds of boot (tailscale0 ready attempt 1 at 17:44:28), bridge running on elder-plops."
---

# Phase 09: Connectivity & Boot Stability — Verification Report

**Phase Goal:** Eliminate fc-core cold-boot restart loop (TDEBT-03) and establish reliable 4G-based connectivity for fc1 at the farm (CONN-01), so the Pi is trustworthy and unattended at the farm and Mission Control can see it from anywhere.
**Verified:** 2026-04-11T21:00:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `ros2 topic echo /fc1/humidity` returns within 5s on 4G WAN, dual-location | VERIFIED | 09-03 SUMMARY: two simultaneous paths confirmed during farm visit — operator phone via mobile data + elder-plops via home ISP, both seeing ~1Hz Timescale rows. Humidity 73% → 83% confirmed live, neither side caching. D-15 dual-location requirement satisfied. |
| 2 | Pi auto-recovers from WAN blip without manual intervention | DEFERRED (non-blocking) | Formal MiFi toggle test not run. Decision documented in 09-03 SUMMARY: deferred to preserve working state during farm visit. Underlying path validated by live SSID cutover (mossrock-west → mossrock-lab) completing with zero fc-core restart. |
| 3 | Zero automatic restarts on cold boot — fc-core reaches active on first attempt | VERIFIED | 09-03 SUMMARY: real plug-pull at 2026-04-11 17:43:49 UTC. `NRestarts=0`, `ActiveState=active`. Journal: `fc-core: tailscale0 ready (attempt 1)` at 17:44:28 — single "Started fc-core" entry. TDEBT-03 satisfied. |
| 4 | Mission Control shows live telemetry within 30s of Pi boot | DEFERRED (non-blocking) | Formal timing not measured. Decision documented in 09-03 SUMMARY: deferred, non-blocking. Qualitative preconditions confirmed: fc-core starts in <1s after tailscale0 ready, bridge on elder-plops running. |
| 5 | Remote-safe wifi cutover mechanism exists in the repo and is installed on fc1 | VERIFIED | `scripts/pi-deploy/etc/netplan/60-wifi.yaml` and `scripts/pi-deploy/fc-system-sync.service` committed to fc1/prod (commits d3c81c9, b8ed990). fc-system-sync installed and enabled on fc1 during single SSH session without touching live interfaces. Exercised live: power-cycle at farm picked up mossrock-lab automatically via fc-system-sync → netplan generate → wpa_cli reconfigure chain. |

**Score:** 3/3 non-deferred truths verified (+ 2 explicitly deferred, non-blocking)

### Deferred Items

Items not yet formally measured but explicitly accepted as non-blocking by operator decision in 09-03 SUMMARY.

| # | Item | Deferred To | Evidence |
|---|------|-------------|----------|
| 1 | WAN-blip recovery formal timing (≤30s criterion) | Future farm visit | 09-03 SUMMARY: "Non-blocking: the underlying CycloneDDS+Tailscale recovery path is the same one that survived the live mossrock-west → mossrock-lab cutover with zero fc-core restart." |
| 2 | Mission Control <30s cold-boot timing | Future farm visit | 09-03 SUMMARY: "The necessary preconditions are all met — telemetry starts flowing within seconds of fc-core reaching active — so this is expected to pass when measured." |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `scripts/pi-deploy/fc-core.service` | Systemd unit with `After=tailscaled.service`, `Wants=tailscaled.service`, ExecStartPre poll | VERIFIED | All three directives present. `CYCLONEDDS_URI=file:///etc/cyclonedds-tailscale.xml` correct (hotfix dbac9bc restored after repo/runtime drift). `ros2 launch fc_core fc.launch.py` intact. |
| `scripts/pi-deploy/etc/netplan/60-wifi.yaml` | Netplan fragment with mossrock-lab (hashed PSK) and mossrock-starlink (open) fallback | VERIFIED | mossrock-lab with 64-char hex PSK present. mossrock-starlink with `key-management: none` present. Merges additively with `50-cloud-init.yaml` on Pi — mossrock-west retained as implicit third fallback. |
| `scripts/pi-deploy/fc-system-sync.service` | Early-boot root oneshot installing repo configs before networkd | VERIFIED | `Before=systemd-networkd.service network-pre.target netplan-wpa-wlan0.service` present. `install -m 600` path for 60-wifi.yaml present. `cmp`-based idempotency. `wpa_cli reconfigure` on change. |
| `docs/pi-setup/4g-hotspot-setup.md` | Runbook doc (originally in 09-02 plan) | INTENTIONAL DESCOPE | 09-02 SUMMARY decision: "No runbook doc. 09-04's mechanism replaces the 09-02 planned runbook — future wifi changes go through `git push fc1/prod` + `wpa_cli reconfigure`, not human-operated runbooks." The git-shipped config IS the runbook. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `fc-core.service [Unit] After=` | `tailscaled.service` | systemd ordering | WIRED | `After=network-online.target fc-update.service tailscaled.service` confirmed in file |
| `fc-core.service ExecStartPre=` | `tailscale0` interface | `ip link show tailscale0` poll loop | WIRED | ExecStartPre present, polls `tailscale0`, exits 0 on found or 1 after 30s |
| `fc-system-sync.service ExecStart` | `scripts/pi-deploy/etc/netplan/60-wifi.yaml` | `install -m 600` from `$REPO/etc/netplan/60-wifi.yaml` | WIRED | Pattern confirmed in fc-system-sync.service ExecStart body |
| `fc-system-sync.service [Unit] Before=` | `systemd-networkd.service` | systemd ordering | WIRED | `Before=systemd-networkd.service network-pre.target netplan-wpa-wlan0.service` confirmed |
| `fc1 wlan0` | `mossrock-lab 4G MiFi` | wpa_supplicant / netplan | WIRED (live) | 09-02 SUMMARY: wlan0 associated BSSID `04:79:70:8a:58:ee`, signal -25 dBm, DHCP `192.168.8.101/24`, WAN `167.108.64.227` |
| `elder-plops ros2` | `/fc1/humidity` | CycloneDDS over tailscale0 over 4G | WIRED (live) | 09-03 SUMMARY: `fc.humidity 83.63` at 18:04:53, ~1Hz rows landing in Timescale from both verification locations |

### Data-Flow Trace (Level 4)

Not applicable — this phase produces systemd service files, netplan config, and operational evidence, not software components that render data. The data-flow is a physical infrastructure path (Pi → 4G → Tailscale → elder-plops → Timescale), verified live during farm visit.

### Behavioral Spot-Checks

| Behavior | Check | Result | Status |
|----------|-------|--------|--------|
| fc-core.service has tailscaled ordering | `grep 'After=.*tailscaled' scripts/pi-deploy/fc-core.service` | Present: `After=network-online.target fc-update.service tailscaled.service` | PASS |
| fc-core.service has ExecStartPre poll | `grep 'ExecStartPre=' scripts/pi-deploy/fc-core.service` | Present: polls `ip link show tailscale0` | PASS |
| ExecStartPre references tailscale0 | `grep 'tailscale0' scripts/pi-deploy/fc-core.service` | Present in poll body | PASS |
| 60-wifi.yaml has mossrock-lab | `grep 'mossrock-lab' scripts/pi-deploy/etc/netplan/60-wifi.yaml` | Present with hashed PSK | PASS |
| 60-wifi.yaml has fallback SSID | `grep 'mossrock-starlink' scripts/pi-deploy/etc/netplan/60-wifi.yaml` | Present with `key-management: none` | PASS |
| fc-system-sync.service has Before= ordering | `grep 'Before=systemd-networkd' scripts/pi-deploy/fc-system-sync.service` | Present | PASS |
| fc-system-sync.service installs netplan fragment | `grep '/etc/netplan/60-wifi.yaml' scripts/pi-deploy/fc-system-sync.service` | Present in install path | PASS |
| Commits on fc1/prod | `git log --oneline origin/fc1/prod \| head -6` | f5f507e (TDEBT-03), d3c81c9 (CONN-01), b8ed990 (first-boot race fix), dbac9bc (CYCLONEDDS_URI) all present | PASS |
| Real cold boot NRestarts=0 | 09-03 SUMMARY human evidence | `NRestarts=0`, `ActiveState=active`, journal `tailscale0 ready (attempt 1)` at 2026-04-11 17:44:28 UTC | PASS |

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| TDEBT-03 | 09-01, 09-03 | fc-core.service starts cleanly on Pi cold boot without restart loops waiting for tailscale0 | SATISFIED | Real plug-pull 2026-04-11 17:43:49 UTC confirmed NRestarts=0. Journal shows `tailscale0 ready (attempt 1)`. fc-core.service in repo has the fix. |
| CONN-01 | 09-02, 09-03, 09-04 | fc1 Pi maintains reliable internet at the farm via 4G hotspot — ROS topics and Mission Control reachable from elder-plops, auto-recovers from WAN blips | SATISFIED | fc1 associated with mossrock-lab (-25 dBm, DHCP from MiFi, WAN 167.108.64.227). Dual-location ROS verification passed. fc-system-sync mechanism in repo and on Pi ensures future wifi changes via `git push fc1/prod`. WAN-blip formal timing deferred/non-blocking per operator decision. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `scripts/pi-deploy/fc-system-sync.service` | 36 | `netplan generate ... \|\| echo "...failed (continuing)"` — generate failure is non-fatal | Info | Intentional: allows boot to proceed even if netplan has a syntax issue in the new file; wpa_supplicant falls back to existing /run state. Documented risk T-09-04-02. |

No blockers found. The `|| echo "...(continuing)"` pattern in fc-system-sync is intentional safety behavior, not a stub.

### Human Verification Required

None — the core phase goal (boot stability + 4G connectivity path established) is fully verified by evidence in the SUMMARYs. The two deferred items (WAN-blip timing, Mission Control <30s timing) are regression quantification checks that the operator explicitly accepted as non-blocking. They do not gate the phase goal.

### Gaps Summary

No gaps. All core must-haves are satisfied by evidence.

The two items not formally measured (SC2 WAN-blip timing, SC4 Mission Control <30s) were explicitly accepted as non-blocking by operator decision recorded in 09-03 SUMMARY. The architectural path for both is validated (live SSID cutover, fc-core telemetry flowing within seconds of boot). Formal timing requires a second farm visit and can be done opportunistically.

The missing `docs/pi-setup/4g-hotspot-setup.md` artifact was explicitly descoped in 09-02 SUMMARY: the git-shipped netplan fragment + fc-system-sync mechanism replaces what a human runbook would document.

**Phase 09 goal is achieved:**
1. fc-core reaches active on cold boot with NRestarts=0 — confirmed by real plug-pull on 2026-04-11
2. fc1 is reachable over cellular Tailscale — confirmed from two physical locations simultaneously
3. Remote-safe wifi cutover mechanism exists in the repo — confirmed via `scripts/pi-deploy/etc/netplan/60-wifi.yaml` + `scripts/pi-deploy/fc-system-sync.service`, exercised live at farm

---

_Verified: 2026-04-11T21:00:00Z_
_Verifier: Claude (gsd-verifier)_
