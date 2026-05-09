---
id: SEED-007
status: dormant
planted: 2026-05-09
planted_during: v1.5 (Saturday lab visit, pre-deploy of Phase 30/31)
trigger_when: Next infrastructure / hardening milestone, or when unscheduled-reboot rate becomes a recurring incident driver
scope: Small
---

# SEED-007: Power-bank UPS for fc1 Pi (gap short blackouts)

## Why This Matters

Short power interruptions at the farm are "somewhat frequent" (radicheta, 2026-05-09). This morning's reboot was caused by one. The 2026-05-03 SD failure and 2026-05-07 unrecoverable reboot incident class both have unscheduled reboots as either trigger or amplifier. Each Pi reboot:

- Loses ~1–2 minutes of telemetry (covered by `fc_buffer` backfill, but only post-Phase 28 v1.5.0.1)
- Triggers the cold-boot DDS re-discovery window (bridge stale until restart — observed today, see live-DDS humidifier gap finding pre-deploy)
- Risks the SD-card / netplan / wg0-link race conditions documented in `project_blackout_2026_05_02_fc_core_stuck`, `project_2026_05_07_fc1_reboot_unrecoverable`, and `project_fc1_tailscale_cpu_spike`

A small UPS gapping 30–60 minutes would eliminate the majority of this incident class — short blackouts pass without the Pi noticing.

## When to Surface

**Trigger:** any of —

- Next infrastructure / hardening milestone (likely v1.6+)
- Another unscheduled-reboot incident hits the postmortem queue
- We add a third chamber Pi (multiplies the incident surface)
- We start counting "uptime SLO" as a project metric

## Scope Estimate

**Small** — hardware purchase + bench validation + one-off install. No code.

Components / decisions to make at trigger time:

- **Hardware shortlist** (lab-validate one before bulk-buy):
  - PiSugar 3 Plus — Pi-HAT form factor, soft-shutdown signal via I2C
  - Waveshare UPS HAT (B) — 18650 cells, similar I2C signalling
  - Generic 12V LiFePO4 DC UPS (e.g. Mean Well DR-UPS40) + 12→5V buck — bigger but more reliable, can also UPS the 4G router and PoE switch
- **Critical spec: true no-break passthrough** — many cheap "passthrough" power banks cut load for 10–50ms on input loss, which reboots the Pi. Need "online UPS" / "no-break" mode, not "passthrough charging" alone.
- **Soft-shutdown integration** — if outage exceeds capacity, controller should `systemctl poweroff` cleanly to protect SD card. Already a script-able hook on PiSugar/Waveshare.
- **Scope of protection:** Pi alone vs Pi + 4G router + sensor rail. Pi-alone helps observability but does NOT keep the chamber under control during a real outage (humidifier is mains-powered). Bigger UPS that also covers the router lets the bridge keep receiving telemetry through outage.

## Breadcrumbs

Related project memories and incident history:

- `project_2026_05_03_ssd_failure` — SD failure incident; cold-power events are SD-killer #1
- `project_2026_05_07_fc1_reboot_unrecoverable` — unrecoverable reboot, 11h offline
- `project_blackout_2026_05_02_fc_core_stuck` — wg0/IPv4 race after cold boot
- `feedback_fc1_remote_action_preflight_protocol` — preflight gating that this would partially obviate
- Phase 28 (`fc_buffer` HTTP backfill) — current mitigation, but only covers data continuity, not control continuity
- `project_v15_milestone_shape` — current milestone; SEED-007 is post-v1.5 work

## Notes

- Bench-test on a single Pi for ≥2 weeks before installing at the farm — make sure the chosen unit's switchover is genuinely seamless (oscilloscope + Pi `dmesg` for brownout marks).
- This complements but doesn't replace fc1's own resilience work; if 4G router is on mains and humidifier is mains-only, the chamber still loses control during real outages — UPS only protects observability + clean reboot.
- Cost ballpark: $30–50 for a Pi-HAT solution; $150–250 for a "whole rack" 12V UPS that also feeds the 4G router and switch. Decision depends on whether the trigger event is "data continuity" or "uptime SLO".
- Could pair with a future "graceful-shutdown service" on fc1 that quiesces fc-core before poweroff, reducing wg0/netplan re-init drama on next boot.
