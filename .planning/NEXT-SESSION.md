# Next session — start here (notes from 2026-05-02 evening)

## What today produced

- Chamber recovered from a multi-event incident (blackout + 4G uplink instability + fc-core start-limit-hit + DERP relay flakiness). RH ended at 93.98%, target 94%.
- Hotfix already on `origin/fc1/prod` (commit `ad949c6`): pwm cap raised 0.40 → 0.90.
- 999.1 Wave 1+2 executed (8 commits on `main`): fc_buffer node + bridge replay poller, all tests green; **Wave 3 (deploy + soak + farmer attest) NOT done — that's the next ship item**.
- Three new backlog items filed reactively: 999.28 (systemd hardening), 999.29 (cap redesign), 999.30 (sampling rate reduction).
- Two new memory entries: `project_blackout_2026_05_02_fc_core_stuck`, `project_fc1_tailscale_cpu_spike`.
- On fc1: stale `99-static.yaml` netplan removed, cloud-init network regen disabled, mosh installed both ends. `/etc/netplan/50-cloud-init.yaml` was edited to drop `mossrock-west` from the wlan0 stanza. **Repo netplan tracking does NOT yet reflect these manual changes** — see "Repo drift" below.

## Workflow correction

Items 999.28/29/30 are scoped, evidence-backed, ready-to-plan — they shouldn't sit in the 999.x parking lot. Promote them properly tomorrow.

## Proposed shape for tomorrow — option 3 (the v1.5.0.1 hotfix milestone)

Pattern matches v1.2.1: a small focused milestone for "lessons from a specific incident", shipped as a coherent unit before resuming the main milestone.

**v1.5.0.1 — Resilience hotfix from the 2026-05-02 incident.** Candidate phases:

1. **999.1 Wave 3 (carryover)** — deploy fc_buffer + bridge replay poller, induce 5-min Tailscale dropout soak, farmer attest. Closes the "data lost forever" gap that today proved is a real cost. Already 89% complete; Wave 3 just needs the deploy+verify protocol.

2. **999.28 — fc-core systemd unit hardening.** ExecStartPre waits for tailscale0 IPv4 (not just link); apply Restart=always + RestartSec + wider StartLimitInterval/Burst per the existing `feedback_systemd_restart_ros2_launch` lesson; consider After=tailscaled.service. Today's blackout proved this is a real risk: fc-core stayed dead 55 min before manual recovery.

3. **999.30 — Telemetry sampling rate reduction.** `sensor_read_interval: 2.0` → 10.0. Caveats and validation noted in the backlog entry. Should drop tailscaled load substantially.

4. **Repo drift cleanup (no backlog item yet — file as a small phase or fold into 999.28).** Tonight we manually edited fc1's `/etc/netplan/50-cloud-init.yaml` (dropped mossrock-west wlan0 block), deleted `/etc/netplan/99-static.yaml`, and added `/etc/cloud/cloud.cfg.d/99-disable-network-config.cfg`. None of this is in the repo. The repo's `60-wifi.yaml` doesn't have an `ethernets:` block either, so wired ethernet to the 4G router currently does nothing. Reconcile: update repo netplan to match fc1's clean state + add eth0 dhcp4 stanza so wired works as a redundant path. fc-system-sync.service then keeps them in sync going forward.

## Stays in v1.5 main (NOT in the hotfix)

5. **999.29 — replace rolling-duty cap with max-continuous-on + forced cool-down** (45 min on / 3 min off, per farmer call; 45/3 are gut estimates pending soak test). PID/humidity-control adjacent; thematic fit with v1.5's PID-and-modes work. Promote to Phase 32 (or insert as 27.1) when planning v1.5's continuation. Pre-planning task: actual mister hardware soak test to validate or revise the 45/3 numbers.

## Stays as 999.x backlog

Everything else already on the roadmap (999.2–27, ex 999.1/28/29/30 above).

## Open / unverified

- **Tailscaled CPU spike when poked from elder-plops** (memory `project_fc1_tailscale_cpu_spike`). Tonight's diagnosis was incomplete — eth0 route fix helped but didn't eliminate the spike (tailscaled still hit 240% later when the office-side bridge re-engaged). Real cause is more about DDS retransmits through bad DERP. 999.30 sampling rate cut is the practical mitigation.
- **First reboot test still not done** — the reboot would validate (a) 99-static.yaml stays gone, (b) tailscaled CPU drops at boot, (c) fc-core comes up clean (catches start-limit-hit if 999.28 bites). Worth doing **after** 999.28 ships, when reboot is no longer scary.
- **The `default via 10.68.155.1 dev eth0 proto static`** route is gone at runtime AND we removed the file that was its source on fc1, but a reboot is the only way to be 100% sure.

## Suggested first command tomorrow

```
/gsd-new-milestone v1.5.0.1
```

with the four items above as the milestone scope.
