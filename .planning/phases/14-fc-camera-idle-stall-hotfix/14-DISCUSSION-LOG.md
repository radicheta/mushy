# Phase 14: fc_camera idle-stall hotfix — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or
> execution agents. Decisions are captured in `14-CONTEXT.md` — this
> log preserves the alternatives considered.

**Date:** 2026-04-17
**Phase:** 14-fc-camera-idle-stall-hotfix
**Present:** farmer (operator + grower), farm team, dev team
**Mode:** interactive (group discussion during real incident aftermath)
**Areas discussed:** Fix strategy, MC freshness signal, Regression test, Observability bundling

---

## Fix strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Diagnose first | Reproduce and find root cause before fixing. Principled, might eat weekend. | ✓ |
| Robust-make | Restructure so stall is impossible (e.g., heartbeat recovery regardless of subscriber state). Ships faster, leaves mystery. | |
| Both | Quick robust-make now + followup to diagnose. | |

**User's choice:** 1a — Diagnose first.
**Notes:** The whole point of Phase 12 was to make the camera
subscriber-aware for 4G thrift; patching the symptom would undo that.
Risk accepted that diagnosis may eat a good chunk of the weekend.

---

## MC freshness signal

| Option | Description | Selected |
|--------|-------------|----------|
| Last-frame-age badge | Show "updated Xs ago" on camera panel. | |
| Stale-placeholder | Replace stale frame with explicit "no recent frame" graphic after N seconds. | |
| Out of scope | Just fix the bug; revisit UI in 999.14. | |
| **Two lights in MC** (emerged during discussion) | Small status strip — "feed live" + "camera subscribed" — scoped narrow now, sets stage for broader health panel later. | ✓ |

**User's choice:** 2 → narrow-A (two lights).
**Notes:** Farm team wants a "panel with green lights" eventually — a
real system health dashboard covering sensors, camera, actuators, bridge,
Pi. That scope was evaluated and split out as Phase 16 to keep Phase 14
weekend-sized. Decision: start with two lights in MC as the first
installment of the broader panel, so the data plumbing and visual
primitive carry over.

---

## Regression test

| Option | Description | Selected |
|--------|-------------|----------|
| Unit test | Simulate subscriber-count transitions in test_camera.py. | |
| Live soak | Run on fc1 for ~30 min, cycle viewer, verify frames. | |
| Both | Unit test locks the logic, soak validates integration. | ✓ |

**User's choice:** 3c — both.
**Notes:** Neither alone is enough. The unit test would miss DDS-level
quirks (which are the most likely root-cause area); a soak alone
wouldn't catch future regressions in CI.

---

## Observability bundling

| Option | Description | Selected |
|--------|-------------|----------|
| Bundle now | Add `last_frame_age_sec` to bridge `/health` in this phase. | ✓ |
| Defer to Phase 16 | Ship only the camera fix; add observability with the broader panel later. | |

**User's choice:** 4 — bundle now.
**Notes:** We're already touching the bridge for the two-lights data
source; deferring would mean revisiting the same file twice.

---

## Claude's Discretion

- Stall-diagnosis methodology (log instrumentation vs test harness vs
  DDS packet capture — depends on what early investigation shows)
- Exact MC layout for the two lights
- Internal structure of the fix once root cause is known
- Whether diagnostic logs remain in shipped code or get guarded

## Deferred Ideas

- **Phase 16: System health panel (broad)** — green/yellow/red for
  sensors, camera, actuators, bridge, Pi. Filed as new phase; scope
  explicitly split from Phase 14.
- Idle-pulse persistence gap — 999.14 already covers this.
- DDS/ROS discovery deep-dive beyond what Phase 14 root-cause analysis
  surfaces.
- Healthy-idle heartbeat log — only if cheap once diagnosis is done.

## Ambient context (from session memory, not re-asked)

- "Gap over noise" farmer principle drives MC signal design
  (`feedback_gap_over_noise.md`)
- Phase 12 camera stall + idle-pulse-not-persisted issue
  (`project_phase12_camera_stall.md`)
- elder-plops is dev+prod → rebuilds are production
  (`project_elder_plops_dual_role.md`)
- Pi deploy via `fc1/prod` branch (`feedback_deploy_method.md`)
- SSH fc1 via Tailscale (`feedback_ssh_tailscale.md`)
