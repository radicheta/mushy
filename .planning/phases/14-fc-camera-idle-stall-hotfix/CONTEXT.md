# Phase 14: fc_camera idle-mode stall hotfix

**Filed:** 2026-04-17
**Milestone:** v1.2.1 (hotfix)
**Status:** Filed, awaiting planning

## Problem

v1.2 Phase 12 shipped subscriber-aware camera (idle 1/hr, active 1fps).
On 2026-04-17 the farmer reported "camera down? i see black on MC".
Investigation:

- fc_camera logged transition to idle at 13:53:14 (0.000278 fps)
- No "active" transition log for ~8 hours despite bridge subscribing on
  viewer connect
- Bridge `/data/snapshots/fc1/2026-04-17/` contained 28 consecutive
  snapshots at *exactly* 32095 bytes (same stale cached frame re-saved
  every 15 min)
- Workaround: `sudo systemctl restart fc-core` recovered the camera in
  ~10s; first post-restart snapshot was 32374 bytes (fresh)

## Suspected causes (not yet diagnosed)

1. `get_subscription_count()` on the fc_camera publisher not reflecting
   the bridge's post-idle re-subscription (DDS discovery edge case?)
2. Idle timer (1/hr) stopped capturing entirely after first idle
   transition (V4L device handle gone stale? timer destroy/recreate bug?)
3. Interaction with Phase 12's 5-second grace window

## Scope

Bug fix only. Do not expand into a rewrite of the subscriber-aware
design. If that's needed, file a separate design phase.

**Touches:**
- `src/chambers/fc-core/fc_core/fc_camera.py` — idle/active transition
  logic, subscriber polling
- `src/chambers/fc-core/fc_core/test/test_camera.py` — add regression test
  for the stall (simulate long idle → subscribe → verify active transition)

## Observability ask (bundle or followup)

Phase 12's logs don't distinguish "healthy idle" from "stuck idle".
Add either:
- Periodic heartbeat log line in idle mode (e.g. every idle capture),
  so silence is detectable
- `last_frame_age_sec` field in bridge `/health` — lets any monitor
  notice a stall without inspecting logs

## Upstream reference

Original Phase 12 planning: `.planning/phases/12-subscriber-aware-camera/`
Findings that prompted this filing:
`.planning/phases/999.14-index-camera-snapshots-in-timescale/FINDINGS-2026-04-17.md`
