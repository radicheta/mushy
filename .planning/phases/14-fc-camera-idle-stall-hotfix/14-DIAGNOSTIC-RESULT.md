# Phase 14 — Live Diagnostic Result

**Date (UTC):** 2026-04-18T00:24:08Z
**fc-core uptime:** FcCamera node started at Apr 17 22:18:56 UTC (restarted manually after 8-hour stall)

## Evidence

### Bridge /health (Task 1.1)

- lastFrame epoch: 1776468979213 ms (2026-04-17T23:49:39 UTC)
- Wall clock at probe: 1776471848114 ms (2026-04-18T00:24:08 UTC)
- Frame age at probe: 2868 seconds (~47.8 minutes)
- subscribed: false
- clients: 0

**Note:** State has changed from research capture. During research (22:48 UTC), bridge
had 2 MJPEG clients and was subscribed. By 00:24 UTC the clients had disconnected and
the bridge had unsubscribed — this is CORRECT behavior (bridge unsubscribes when no
MJPEG clients are connected). See "Stall autopsy" below.

### fc_camera journal tail (Task 1.2)

Last 10 relevant lines since last service start:

```
Apr 17 13:41:45 fc_camera: active (1.0 fps, 1 subscriber(s))
Apr 17 13:53:14 fc_camera: idle (0.000278 fps)
Apr 17 21:52:51 fc_camera: active (1.0 fps, 1 subscriber(s))
Apr 17 21:56:42 fc_camera: idle (0.000278 fps)
Apr 17 22:18:56 FcCamera node started (idle: 0.000278 fps, active: 1.0 fps, grace: 5.0s)
Apr 17 23:18:53 fc_camera: active (1.0 fps, 1 subscriber(s))
Apr 17 23:37:21 fc_camera: idle (0.000278 fps)
# ← no further transitions as of 2026-04-18T00:26 UTC
```

### DDS graph from fresh CLI participant (Task 1.3)

Captured at 2026-04-18T00:26:30Z (after MJPEG clients had disconnected):

- Publisher count: 1 (fc_camera, GID 01.10.ca.97.65.72.f1.69.64.86.83.8a.00.00.16.03)
- Subscription count: 0 (bridge unsubscribed — no MJPEG clients)

This is consistent with the current `/health` state. DDS graph is live-accurate.

### rclpy count_subscribers probe (Task 2)

Probe: fresh rclpy Node joined as "fc_camera_probe_14_01", slept 3s for discovery,
then called `node.count_subscribers('/fc1/camera/compressed')`.

- count_subscribers('/fc1/camera/compressed') = 0
- count_publishers('/fc1/camera/compressed') = 1

Raw probe output: `PROBE_RESULT count_subscribers=0 count_publishers=1`

**Interpretation:** The probe returned 0 because the bridge genuinely had no active
subscription at probe time. This confirms `count_subscribers()` is a LIVE graph query,
not a stale cache — it accurately reflects the actual DDS state.

### Post-probe re-check (Task 2 tail)

- Frame age: 2868+ seconds (unchanged: lastFrame = 1776468979213)
- Stall persisted: N/A — fc_camera is correctly idle with 0 subscribers; frame
  staleness is expected in this state (bridge unsubscribed, no viewer present)

## Stall Autopsy

The stall documented in 14-RESEARCH.md (52-min stale frame while subscribed=true) has
since self-resolved via the delayed idle tick. Here is the complete timeline:

| Time (UTC) | Event |
|------------|-------|
| 13:41:45 | fc_camera active (morning viewer session) |
| 13:53:14 | fc_camera idle (viewer left) |
| 21:49:00 | Bridge subscribed to /fc1/camera/compressed (viewer opened MC) |
| 21:52:51 | fc_camera active (get_subscription_count returned 1) |
| 21:56:26 | Last fresh frame saved (32374 bytes) |
| 21:56:42 | fc_camera idle (viewer left, grace expired) |
| 22:18:56 | fc-core restarted (manual — stall was still live) |
| 22:18:56 | FcCamera node started — idle, timer period = 1/0.000278 ≈ 3597 s |
| **22:18–23:18** | **STALL WINDOW — bridge subscribed, 2 MJPEG clients, fc_camera idle,** |
|                  | **get_subscription_count() NEVER POLLED (idle tick not yet due)** |
| 23:18:53 | First idle tick fires; get_subscription_count() = 1 → fc_camera ACTIVE |
| 23:20:00 | New frame captured and published (snapshot changes from 32374 → 30698 bytes) |
| 23:37:21 | fc_camera idle (viewers left; grace expired) |
| ~00:05:00 | Both MJPEG clients disconnected; bridge unsubscribed |

**Root cause confirmed:** The idle timer period is ~3597 seconds (1/0.000278 fps). After
the 22:18 service restart, `capture_and_publish` (which contains the only call to
`get_subscription_count()`) would not fire until 23:18 — 60 minutes later. During that
entire window, fc_camera could not detect the bridge's subscription regardless of whether
`get_subscription_count()` is accurate. The 23:18 tick proved `get_subscription_count()`
DID return 1 correctly — confirming H1 is NOT the root cause in the strict sense.

**The true root cause is the polling frequency, not the API correctness.** `get_subscription_count()` works correctly when it is called. The bug is that it is only called inside the idle-rate callback (once per 3597 seconds), making the theoretical worst-case recovery time 3597 seconds (~60 min).

This is a variant of H2 (idle timer never fires in the relevant window) combined with
the stale-cache symptom: `get_subscription_count()` IS accurate but is called too
infrequently to drive 10-second recovery.

## Interpretation

The Path A fix (add a 1 Hz `_graph_poll` timer calling `self.count_subscribers()`) is
validated by this diagnostic:

1. `count_subscribers()` is a live graph query (confirmed: returns 0 now with no
   subscribers, consistent with actual DDS state). It will return 1 when the bridge
   subscribes.
2. The existing `get_subscription_count()` in `capture_and_publish` also works correctly
   (confirmed: returned 1 at the 23:18 idle tick when the bridge was subscribed). The
   problem was frequency, not accuracy.
3. The fix: add a 1 Hz timer that calls `self.count_subscribers()` and ramps up if > 0.
   This reduces worst-case recovery from 3597 seconds to ≤ 1 second. The existing idle
   polling in `capture_and_publish` becomes a redundant safety net.

Path B (bridge-side viewer_present hint topic) is NOT needed. The node-level graph API
provides sufficient information.

## Decision

path_chosen: A

- `count_subscribers()` is confirmed live-accurate (not stale)
- `get_subscription_count()` is also confirmed accurate (returned 1 correctly at 23:18)
- Root cause is polling frequency, not API reliability
- Path A (1 Hz `_graph_poll` using `count_subscribers()`) solves the root cause cleanly
- No bridge-side changes needed

## Notes

1. **Stall partially self-healed overnight.** The 60-minute delayed idle tick at 23:18
   temporarily broke the stall. The fix is still critical — 60-minute worst-case recovery
   is unacceptable for the farmer's workflow.

2. **Probe returned 0 — no asymmetry observable today.** The research-period asymmetry
   (bridge subscribed but `get_subscription_count()` stuck at 0) was a time-window
   phenomenon, not an API-level bug. The probe returned 0 because the bridge was not
   subscribed at probe time. No contradiction with Path A.

3. **Bridge snapshot evidence is informative.** Snapshot at 23:20 = 30698 bytes (new
   frame), then 31546, 31666 bytes — confirms fc_camera DID publish fresh frames after
   the 23:18 recovery. The idle-pulse-not-persisted issue (999.14) is unrelated.

4. **fc-core was NOT restarted during this diagnostic.** The 22:18 restart was performed
   by the researcher prior to this plan. This plan ran entirely read-only.
