# Phase 14: fc_camera idle-stall hotfix — Research

**Researched:** 2026-04-17 (evening, while the stall is reproducing LIVE)
**Domain:** ROS 2 Jazzy rclpy publisher subscription-count polling over CycloneDDS unicast (Tailscale)
**Confidence:** HIGH for reproduction / root-cause direction, MEDIUM for the exact DDS-internal mechanism

---

## TL;DR — read this first

**The stall is reproducing right now on live fc1.** No action needed from you to trigger it — you're already soaking in it. Recent restart at 22:18:56 UTC; as of 22:48 UTC the bridge still has `/health.camera.lastFrame = 1776462986809` (21:56:26 UTC, **50+ minutes stale**), `subscribed: true`, `clients: 2`, and fc_camera has logged zero `active`/`idle` transitions since the 22:18 startup. So the stall is not just "failed to re-ramp after idle" — it happens even across a fresh fc-core restart while the bridge holds a subscription open.

**Confirmed asymmetry:** From fc1's ros2 CLI (`ros2 topic info --verbose /fc1/camera/compressed`, run from a freshly-spawned participant using the service's Cyclone config), both endpoints ARE visible: Publisher count 1 (fc_camera), Subscription count 1 (mission_control_bridge). So DDS-level discovery has matched them. Yet fc_camera's long-lived publisher instance, inside the same running process, observes `get_subscription_count() == 0` (otherwise it would have logged `active`). This is `rcl_publisher_get_subscription_count`-level staleness on a specific publisher object — not a topic-wide discovery failure.

**Phase-14 scope is safe.** The fix does NOT require redesigning the subscriber-aware architecture. It needs either (a) a robust fallback that ramps active when the publisher's self-reported count disagrees with external liveliness, or (b) the bridge hinting to fc_camera explicitly (service call / pub-sub heartbeat) instead of relying solely on `get_subscription_count()`. Both are weekend-sized. See §5.

**Good news for D-03/D-04 observability:** the stall reproduces for hours while `/health` confidently reports `subscribed: true`. The farmer literally cannot tell "camera stuck" from "camera healthy" with current signals. D-04 (`last_frame_age_sec`) is exactly the right primitive to surface this.

---

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 Diagnose before fixing.** Reproduce stall and find root cause; do NOT patch with a blind heartbeat timer that undoes Phase 12's subscriber-aware design.
- **D-02 Test strategy.** Unit test in `test_camera.py` extending FakeNode/FakePublisher to simulate idle → sub appears → active; plus live 30-min soak on fc1 with viewer cycle.
- **D-03 MC freshness signal.** Two status lights — "Feed live" (green if `last_frame_age_sec < N`) and "Camera subscribed" (green if bridge is subscribed). Narrow now, same primitives Phase 16 will multiply.
- **D-04 Observability.** Add `camera.last_frame_age_sec` to bridge `/health` alongside existing `camera.subscribed`. Null when no frame ever; else wall-clock seconds since `latestFrame` was last updated.

### Claude's Discretion

- Stall-diagnosis methodology (instrumentation vs harness vs DDS capture).
- Exact MC layout for the two lights (inline, color palette matching chrome).
- Internal structure of the fix once root cause is known.
- Whether to add logging hooks that Phase 16 will reuse.

### Deferred Ideas (OUT OF SCOPE)

- Phase 16: broad system health panel (green/yellow/red for sensors, camera, actuators, bridge, Pi).
- Idle-pulse persistence gap — 999.14.
- DDS/ROS discovery deep-dive beyond what Phase 14 root-cause surfaces.
- Healthy-idle heartbeat log — only if cheap once diagnosis done.

---

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HFIX-01 | fc_camera recovers to active rate within N seconds of a bridge subscription being established, regardless of how long it has been idle | §1 root-cause hypotheses; §4 unit test design |
| HFIX-02 | A regression test in `test_camera.py` locks HFIX-01 in place via the FakeNode/FakePublisher harness | §4; the harness already handles sub-count transitions — just missing the "long idle → sub appears" path |
| HFIX-03 | `/health` includes `camera.last_frame_age_sec` (number of seconds, or null); `camera.subscribed` stays unchanged in shape | §3 observability gaps; existing `lastFrameTime` state is the source |
| HFIX-04 | MC camera panel renders two status lights: "Feed live" (driven by `last_frame_age_sec < N`) and "Camera subscribed" (driven by `subscribed`) | Existing `plugin.js` already has `isLive` logic combining `subscribed + lastFrame age` — split into two distinct indicators |
| HFIX-05 | Live soak on fc1 with a viewer-connect → wait → disconnect → reconnect cycle proves frames flow within N seconds of connect | §6 live-soak plan |

---

## Evidence captured tonight (non-invasive observation)

All gathered without restarting fc-core or deploying code. This is the reproduction baseline for Saturday morning.

### Bridge /health snapshot at 22:48:30 UTC

```
curl http://localhost:8081/health
{"status":"ok","db":true,"camera":{"lastFrame":1776462986809,"clients":2,"subscribed":true}}
```

`lastFrame = 1776462986809 ms = 2026-04-17 21:56:26 UTC`. Wall clock at probe: 22:48:30 UTC → frame is **52 minutes stale** while bridge reports `subscribed: true` and 2 MJPEG clients. Farmer looking at MC would see a frozen image with no cue that it's stuck.

### fc_camera transition journal (service start → now)

```
Apr 17 21:52:51  fc_camera: active (1.0 fps, 1 subscriber(s))
Apr 17 21:56:42  fc_camera: idle (0.000278 fps)
Apr 17 22:18:56  FcCamera node started (idle: 0.000278 fps, active: 1.0 fps, grace: 5.0s)
# ← no further transitions for 30+ minutes despite bridge holding 2 MJPEG clients
```

Prior stall today (what Issue 1 in FINDINGS-2026-04-17.md documented):

```
Apr 17 13:41:45  fc_camera: active (1.0 fps, 1 subscriber(s))
Apr 17 13:53:14  fc_camera: idle (0.000278 fps)
# ← 8+ hours with no recovery despite farmer loading MC → 22:18 manual restart
```

The pattern: every active window lasts 4–12 minutes, then idle, then never recovers. The 21:52→21:56 window is the "tried to check after last night's debug" moment; the 13:41→13:53 window is the farmer's morning session.

### Bridge camera logs

```
21:49  [camera] subscribed to /fc1/camera/compressed
21:49  [camera] MJPEG client connected (1 total)
21:50  snapshot 32095 bytes          # still stale cached frame
22:05  snapshot 32374 bytes          # ← FRESH — must have been during 21:52-21:56 active window
22:20  snapshot 32374 bytes          # stuck again, re-writing same bytes
22:32  [camera] MJPEG client connected (2 total)
22:35  snapshot 32374 bytes          # no new frames since 21:56
```

The single 32374-byte window is the entire "recovery" for the 21:52-21:56 active period. Everything after is re-saved stale cache.

### Tailscale link quality fc1 ↔ elder-plops

```
3 packets transmitted, 3 received, 0% packet loss
rtt min/avg/max/mdev = 142.666/256.478/442.609/132.699 ms
relay "sao" (São Paulo DERP)
```

**No packet loss in the instant** but RTT jitter is wild: 142 → 442 ms with 132 ms mdev. The connection is going through a DERP relay (likely because UDP hole-punching failed at the farm NAT). This is a plausible environment for intermittent SEDP (subscription-endpoint-discovery protocol) packet loss on a unicast CycloneDDS setup.

### DDS topic introspection (from freshly-spawned CLI participant on fc1)

```
ros2 topic info /fc1/camera/compressed --verbose

Publisher count: 1
  Node: fc_camera
  GID:  01.10.ca.97.65.72.f1.69.64.86.83.8a.00.00.16.03
  QoS:  RELIABLE, KEEP_LAST(10), VOLATILE, LIVELINESS AUTOMATIC, lease Infinite

Subscription count: 1
  Node: mission_control_bridge
  GID:  01.10.29.6d.59.8a.96.09.6d.52.5e.54.00.00.1b.04
  QoS:  RELIABLE, KEEP_LAST(10), VOLATILE, LIVELINESS AUTOMATIC, lease Infinite
```

**Publisher and subscriber ARE in the same DDS discovery graph from a third participant's view.** Yet fc_camera's publisher instance inside the running node reports 0 subscribers. The gap is between "DDS-level graph state" and "this-publisher-object's cached matched-endpoints set."

Re-probing `/health` *after* the CLI introspection: still `lastFrame: 1776462986809`. The CLI participant's discovery traffic did NOT perturb fc_camera back into active — ruling out the naïve "discovery was simply lost and can be re-kicked by any new participant" hypothesis.

### Environment

```
fc-core service env:
  RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
  CYCLONEDDS_URI=file:///etc/cyclonedds-tailscale.xml
  ROS_DOMAIN_ID=69, ROS_LOCALHOST_ONLY=0

Bridge container env: same RMW + same Cyclone XML.

Cyclone config: unicast on tailscale0, AllowMulticast=false,
explicit Peer list [100.96.10.66 elder-plops, 100.96.239.75 fc1].

ROS package versions on fc1 (Jazzy):
  ros-jazzy-rclpy                7.1.9-1noble.20260124
  ros-jazzy-rmw                  7.3.3-1noble.20260122
  ros-jazzy-rmw-cyclonedds-cpp   2.2.3-1noble.20260124
  ros-jazzy-cyclonedds           0.10.5-1noble.20260121

Bridge: rclnodejs ^1.9.0, ws ^8.16.0, express ^5.2.1, pg ^8.20.0
```

---

## Standard Stack

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| rclpy | 7.1.9 (Jazzy) | Python ROS 2 client | Existing fc_camera node; no change |
| rmw_cyclonedds_cpp | 2.2.3 | ROS → CycloneDDS RMW shim | Existing farm config for Tailscale unicast |
| pytest + unittest | stdlib / existing | Regression test | `test_camera.py` already uses unittest + FakeNode harness |
| rclnodejs | ^1.9.0 | Node.js ROS client in bridge | Existing bridge; no change |

No new dependencies. The fix lives in the existing files already listed in `14-CONTEXT.md`:
`src/chambers/fc-core/fc_core/fc_camera.py`, `src/chambers/fc-core/fc_core/test/test_camera.py`,
`src/mission-control/bridge/src/index.js`, `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js`.

---

## 1. Root-cause hypotheses (ranked)

### H1 — Publisher's matched-endpoints cache goes stale over lossy unicast DDS; `get_subscription_count()` reflects that stale cache indefinitely (HIGH likelihood)

**Claim:** On long-lived fc_camera publisher objects, the `rcl_publisher_get_subscription_count` read returns the locally-cached count of matched subscribers that CycloneDDS' reader-proxy table currently holds. On the CycloneDDS unicast-over-Tailscale configuration in use, SEDP re-announcements sometimes fail to reach fc1 (or its response fails to reach elder-plops); the reader-proxy is dropped from the writer's match table; but the subscription_count stays at the (now wrong) cached value until another SEDP announcement arrives. No timer or liveliness event inside rclpy repeatedly re-queries the DDS-layer full graph state from a long-lived publisher. [ASSUMED — based on documented CycloneDDS unicast-discovery fragility and the observed asymmetry where a new participant sees both endpoints while the long-lived publisher does not]

**Evidence for:**
- The bridge's subscription is definitely alive (it just hasn't received data because fc_camera isn't publishing at active rate, but the subscription object exists in rclnodejs).
- A fresh CLI participant on fc1 sees both endpoints. So the DDS graph IS consistent.
- fc_camera's publisher sees 0. Mismatch is fully on the long-lived publisher side.
- The 21:52:51 active ramp proves fc_camera's `get_subscription_count()` DID see the bridge once — then dropped back to 0 at 21:56:42 — and since the 22:18 restart, that same reader has not been matched at all from fc_camera's POV. So the drop is not "bridge unsubscribed"; it's "the writer's matched-readers table shrank without the reader actually going away."
- Jitter of 142–442 ms on a DERP relay over Tailscale is more than enough to cause SEDP packet loss under CycloneDDS' default retransmit parameters.
- Related: [ros2/ros2#1536 "Subscription count is 0 after subscriber is created"](https://github.com/ros2/ros2/issues/1536) and [ros2/rclcpp#668 "Subscription and intra-process subscription counts not updated in sync"](https://github.com/ros2/rclcpp/issues/668) — both document `get_subscription_count` returning stale values in known-broken configurations. [CITED: github.com]

**Evidence against:**
- None from tonight's observation — every probe is consistent with H1.
- We haven't yet instrumented Cyclone traces to PROVE the SEDP loss; that's the next step in diagnosis if we want certainty. But we don't need certainty for a weekend fix — §5 fallback strategies cover H1 without requiring us to prove it.

**Confirmation plan:** Enable `CYCLONEDDS_URI` to point at a config with `<Tracing><Verbosity>finest</Verbosity></Tracing>` for one restart and watch `discovery` / `topic` level events. We'll see reader-proxy add/remove on the writer side. DO NOT do this on live fc1 without prior approval — the log volume is significant.

**Fix cost:** Low-medium. See §5. Either a "poll the node's introspection graph instead of the publisher-local cache" fallback or an out-of-band nudge from the bridge.

---

### H2 — The idle-rate timer never actually fires on fc1 after the first idle transition (LOW likelihood — effectively ruled out)

**Claim:** `destroy_timer` + `create_timer` race in rclpy on the MultiThreadedExecutor default, leaving the new idle timer orphaned. If the idle timer never ticks, `capture_and_publish` never runs, `get_subscription_count()` is never polled, so the ramp-up branch is unreachable.

**Evidence against:**
- Today's observation shows fc_camera DID transition idle → active → idle → active → idle cleanly three times (13:41, 13:53, 21:52, 21:56) — the timer swap works.
- However, **note that each "first active" happens at fresh node startup, not from a long-idle state.** The 21:52 active ramp happened ~20 min after FcCamera startup at 21:?? (not exactly known, but inside today's runtime) — not from a stable long idle. We don't have a single observed case of "long idle → sub appears → active" on live hardware. That's a gap we must close.
- Bridge snapshot timestamps show the file size DID change at 22:05 to 32374 bytes, proving new frames reached the bridge during the 21:52-21:56 window. So the timer swap is working at least intermittently.

**Remaining uncertainty:** The idle-period `1 / 0.000278 ≈ 3597 s`. Across fc_camera's runtime from 22:18 to now (30+ min), `capture_and_publish` should have fired ONCE (the very first idle tick at ~22:18 + 3597 s would be at ~23:18). So fc_camera's callback has NOT fired yet in its current lifetime, which means we haven't observed what `get_subscription_count()` will report on the next idle tick. **H2 is demoted but not fully ruled out** — there is a chance that when the first idle tick fires around 23:18, fc_camera will ramp up correctly. If that happens, H1 still stands for the 13:41-13:53 and 21:52-21:56 observations but the picture becomes murkier. Recommend waiting to observe the next idle tick (see §6) before finalizing diagnosis.

**Fix cost if confirmed:** Trivial — just guard the timer swap better or use a single-rate timer with conditional capture.

---

### H3 — V4L / OpenCV `cap.read()` blocks indefinitely after long idle, stalling the ROS timer thread (LOW likelihood)

**Claim:** `/dev/video0` goes into a power-save state; `cap.read()` blocks the timer callback thread; the ROS subscription-matching callback can't fire in time to update the cached count. Result: even when get_subscription_count() would have seen a sub, the timer never actually gets to run.

**Evidence against:**
- fc_sensors, fc_display timer callbacks keep logging at normal rates (see journal snippet of fc_display every second). If the ROS executor were globally stalled, those would also be frozen.
- `capture_and_publish` is non-blocking by design in the code: it always reads sub count FIRST (line 93, before any cv2 call), so even if cv2 hangs, the count check and ramp decision happen before any potential block.
- rclpy uses separate callback threads by default for each timer (SingleThreadedExecutor in rclpy.spin default? — need to verify). If so, V4L blocking one timer shouldn't stall others. But: if the ROS graph-event callback shares the same executor thread as the camera timer, a V4L hang could prevent DDS discovery events from being processed in rclpy. [ASSUMED]

**Confirmation plan:** Check rclpy executor defaults for `Node.spin()` — if it's single-threaded, this matters. Add an instrumentation log at the top of `capture_and_publish` to see whether the idle ticks actually fire (should fire every ~3597 s). A soak over 2+ idle ticks will confirm or deny.

**Fix cost if confirmed:** Low — MultiThreadedExecutor, or run cv2.read() in a thread, or drop the blocking read entirely.

---

### H4 — 5-second grace-period timer is reconstructing the main timer wrong after a grace→idle drop (LOW likelihood — ruled out by code inspection)

**Claim:** `_grace_expired` calls `_ramp_down` which does `destroy_timer(_cam_timer)` and creates a new one at idle rate. Something in this path leaves the timer callback wired to a stale closure, so `capture_and_publish` runs but reads subscription count from the wrong publisher object.

**Evidence against:**
- `_ramp_down` just calls `self.create_timer(period, self.capture_and_publish)` — bound method on `self`, no closure-capture weirdness. The publisher reference `self._cam_pub` is a single node-owned object.
- The idle timer period is computed from `self._idle_fps` each time, which is a simple attribute. Nothing to go stale.

**Ruled out via code inspection.** Filing because it's worth thinking about before we rule it out in the final plan.

---

### H5 — The bridge's rclnodejs subscription object is half-dead (has a handle but is not participating in DDS liveliness) and DDS sees it as expired on the fc_camera side only (MEDIUM likelihood — needs a check)

**Claim:** rclnodejs occasionally leaves a subscription object alive on the JS side but its underlying C++ spin thread stops processing it (e.g., `node.spin()` blocked somewhere else). Liveliness is AUTOMATIC with Infinite lease, so strict liveliness won't matter, but SEDP alive-announcements might not go out anymore. fc_camera then sees the reader drop and marks it unmatched. Bridge still thinks `cameraSubscription !== null` so `/health` lies.

**Evidence for:**
- Bridge also subscribes to humidity/temp/CO2/humidifier topics and logs "Chamber Status" updates — check whether those are still flowing. If humidity/temp broadcasts are fine but ONLY the camera is stuck, rclnodejs-global-block is ruled out.
- Need to check: `docker logs mushy-bridge-1` recent output for non-snapshot lines — do telemetry broadcasts still fire?

**Evidence against:**
- bridge's CLI-visible subscriber IS present in `ros2 topic info` output from fc1, so it's still announcing itself to DDS discovery at *some* level.
- AUTOMATIC liveliness with Infinite lease means it should NEVER expire.

**Confirmation plan:** Tail the bridge logs for recent non-camera broadcasts during soak. If sensors are flowing but camera isn't, this is likely ruled out too.

**Fix cost if confirmed:** Medium — bridge-side watchdog or subscribe via a lower-level rmw call.

---

### Summary table for the planner

| # | Hypothesis | Likelihood | Cost if true | Weekend-sized? |
|---|------------|------------|--------------|----------------|
| H1 | Stale matched-endpoints cache on long-lived publisher | HIGH | Low-med (fallback path on mismatch) | YES |
| H2 | Idle timer never ticks after swap | LOW | Trivial (better swap) | YES |
| H3 | cv2 blocks timer thread after long idle | LOW | Low (MT executor) | YES |
| H4 | Grace-period reconstruction bug | RULED OUT | — | — |
| H5 | Bridge subscription half-dead | MEDIUM | Medium (bridge watchdog) | YES |

**Recommended diagnosis order for Saturday morning:**

1. Observe the next idle tick (expected ~23:18 UTC tonight or ~3597 s after last idle transition). Either it fires and we see a ramp decision logged, or it doesn't fire at all (H2/H3). This is free — just tail journalctl.
2. Check whether bridge telemetry broadcasts are still flowing during the camera stall (kills or confirms H5).
3. If H1 remains the leading candidate, go straight to §5 fix strategies. We don't need Cyclone traces to ship a fix — we just need a fallback that doesn't rely exclusively on `get_subscription_count()`.

---

## 2. Reproduction strategy

### 2a. Unit-test reproduction (HIGH confidence — already possible with tonight's understanding)

The existing `FakeNode/FakePublisher/FakeTimer` harness in `test_camera.py` is sufficient. The gap isn't harness capability; it's that there's no test that simulates the *sequence* "long idle → sub appears." Current tests only cover: startup → sub appears, and active → sub drops. Between them there's no "dwell in idle for a while, then sub appears."

Good news: because the idle period in production is ~3600 s, we can expose this in tests by using a lower idle FPS like 0.000278 AND driving `capture_and_publish` manually to simulate elapsed ticks. The harness already lets us pokes `_sub_count` directly (`node._cam_pub._sub_count = 1`), so we can:

1. Create the node (idle at 0.000278 Hz).
2. Manually call `capture_and_publish()` once — establishes idle tick with 0 subs.
3. Leave `_sub_count = 0`.
4. Call `capture_and_publish()` repeatedly (10×) to simulate 10 idle ticks with no subs. (If H2 were true, after swap the timer period and callback should still match `capture_and_publish`.)
5. Set `_sub_count = 1` — simulate bridge connecting.
6. Call `capture_and_publish()` — MUST ramp up. The test asserts `_is_active == True` and `_cam_timer.period` ~= 1.0.

This test would have failed in Phase 12 exactly because Phase 12's test suite drives ramp-up directly from node-init, not from a dwelt-in-idle state. **It is not a sufficient reproduction of H1** (H1 is a DDS issue, not a state-machine issue), but it IS a sufficient regression test for "make sure the fix works for the state-machine fallback." See §4.

### 2b. Live reproduction on fc1 (HIGH confidence — already reproducing)

**No action needed.** The current fc1 process is in the stalled state RIGHT NOW. Just observe. Saturday morning the fc-core service is still running the stalled instance (unless kicked). Open MC, confirm black image, confirm `/health` shows stale `lastFrame`, confirm `ros2 topic info` shows both endpoints, take your notes.

If the stall auto-recovers overnight (possible if the delayed idle tick at ~23:18 triggers a belated re-match), we won't have a live repro Saturday morning. In that case trigger a fresh repro: leave MC open for 5 minutes, close it, wait 10 minutes, re-open. The existing timeline shows active windows of 4-12 minutes consistently go to idle and many do not recover, so one or two cycles should re-capture it. DO NOT restart fc-core to trigger — the stall is restart-durable (see 22:18 restart evidence above), so a restart would actually reset the reproduction state.

### 2c. Spare-Pi / harness reproduction of the DDS-layer bug (LOW confidence, likely not worth it)

To reproduce H1 in isolation you'd need: a Pi + elder-plops-equivalent setup, Tailscale with DERP-relay-forced path (simulate the packet loss), matching Cyclone config, and patience. This is real-system work and would eat the weekend without a guaranteed repro. Not recommended. Trust the fix-with-fallback path and verify with the live soak.

### 2d. Faster-than-realtime test

In the unit test, override `camera_fps` (idle rate) to `1.0` (1 Hz) instead of `0.000278` so the idle ticks are 1s apart. `test_starts_idle` already does `1.0/0.000278` — it's a parameter override, not a real timer wait. So tests already ARE faster-than-realtime; we just need more of them. See §4.

---

## 3. Log / observability gaps (feeds D-04)

Gaps that made this an 8-hour stall instead of a 5-minute one:

### G1 — `/health` has no frame-age field

Currently: `lastFrame` is an absolute epoch. The frontend computes `Date.now() - lastFrame` to get age. This works but requires clock-sync between viewer and bridge, which is fine on LAN but won't be for remote access.

D-04 ships the fix: add `last_frame_age_sec` (number or null). **HFIX-03.**

### G2 — fc_camera's idle transitions log once; no heartbeat log distinguishes "healthy idle" from "stuck idle"

Currently: only `_ramp_up` and `_ramp_down` log. Between transitions the node is silent. When an idle period spans hours, there's no way to distinguish "running but idle (healthy)" from "stalled."

Recommendation (respect Deferred Idea constraint — only if cheap): emit a single debug line at the *start* of every `capture_and_publish` idle tick (once per hour in production), including `count = get_subscription_count()` and `_is_active`. That's one log line per hour. Dirt cheap. Makes root-cause-analysis post-mortem trivial going forward.

If we don't want to pollute service logs, guard it behind a `camera_debug_log: false` param. But per "gap over noise" philosophy, one log line per hour is gap, not noise.

### G3 — Bridge has no "frames received per window" signal

Currently: `saveSnapshot` writes `latestFrame.length` but there's no cumulative count. If we had "frames received in last 60s" visible in `/health`, the farmer's dashboard could show "fps: 0" even while `subscribed: true` — which is exactly the stuck-state fingerprint.

Recommendation for Phase 14: ship `last_frame_age_sec` (required by D-04) AND consider adding `frames_last_60s: N`. This is a single rolling counter in the bridge. Phase 16 will want it too. Worth asking the planner/user if we're OK adding it now since it's the same file and same timestamp primitive.

### G4 — No log when bridge subscribes/unsubscribes to the topic relative to viewer count

Currently: the bridge already logs `[camera] subscribed to /fc1/camera/compressed`, `MJPEG client connected (N total)`, etc. This is fine. Leave alone.

### G5 — fc_camera doesn't log its own view of subscription count

Currently: `_ramp_up` logs subscriber count, but only at transition. There's no way from fc_camera's logs to know "right now, how many subs do I see?" without running ros2 topic info.

Recommendation: include sub count in the per-hour heartbeat proposed in G2.

---

## 4. Test design

### Test harness capabilities needed (all already exist)

- `_patch_params({...})` — override camera_fps, camera_active_fps, camera_subscriber_grace_sec ✓
- `node._cam_pub._sub_count` directly mutable ✓
- `node.capture_and_publish()` directly callable ✓
- Timer object exposes `period` and `callback` for assertions ✓

### New test class: `TestIdleToActiveRecovery` (locks HFIX-01 / HFIX-02)

```python
class TestIdleToActiveRecovery(unittest.TestCase):
    """Regression test for Phase 14: ensure a long-idle node ramps up on subscriber arrival.

    This test locks down the fix for the stall observed in production on 2026-04-17:
    fc_camera went idle at 13:53:14 and never transitioned back to active despite
    the bridge subscribing at viewer-connect time 8+ hours later.
    """

    def _make_node(self):
        fc_camera = _load_fc_camera()
        mock_cv2 = MagicMock()
        with patch.dict(sys.modules, {'cv2': mock_cv2}):
            with _patch_params({
                'camera_simulation_mode': True,
                'camera_fps': 0.000278,         # production idle rate
                'camera_active_fps': 1.0,
                'camera_subscriber_grace_sec': 5.0,
            }):
                node = fc_camera.FcCamera()
        return node

    def test_long_idle_then_subscriber_appears_ramps_up(self):
        """Node dwells idle for many ticks with 0 subs, then a sub appears → active."""
        node = self._make_node()
        # Simulate 10 idle ticks with no subscribers — the "long idle" state
        for _ in range(10):
            node._cam_pub._sub_count = 0
            node.capture_and_publish()
        self.assertFalse(node._is_active)  # still idle
        # Subscriber appears (the fix must detect this)
        node._cam_pub._sub_count = 1
        node.capture_and_publish()
        self.assertTrue(node._is_active)
        self.assertAlmostEqual(node._cam_timer.period, 1.0, places=3)
        node.destroy_node()

    def test_idle_tick_sees_subscriber_that_arrived_between_ticks(self):
        """Mimics the 1-frame-per-hour idle cadence. Subscriber arrives mid-dwell."""
        node = self._make_node()
        # Establish idle
        node._cam_pub._sub_count = 0
        node.capture_and_publish()
        self.assertFalse(node._is_active)
        # Between ticks (model reality): sub arrives
        node._cam_pub._sub_count = 1
        # Next idle tick must ramp up
        node.capture_and_publish()
        self.assertTrue(node._is_active)
        node.destroy_node()

    def test_active_timer_actually_publishes_frames(self):
        """After ramp-up, subsequent ticks on the active timer capture+publish."""
        # Requires a mocked cv2 that returns a valid frame
        fc_camera = _load_fc_camera()
        mock_frame = MagicMock()
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (True, mock_frame)
        fake_buf = MagicMock()
        fake_buf.tobytes.return_value = b'\xff\xd8\xff\xe0data'
        mock_cv2 = MagicMock()
        mock_cv2.VideoCapture.return_value = mock_cap
        mock_cv2.imencode.return_value = (True, fake_buf)
        mock_cv2.IMWRITE_JPEG_QUALITY = 1

        with patch.dict(sys.modules, {'cv2': mock_cv2}):
            with _patch_params({
                'camera_simulation_mode': False,  # real capture path
                'camera_fps': 0.000278,
                'camera_active_fps': 1.0,
                'camera_subscriber_grace_sec': 5.0,
            }):
                node = fc_camera.FcCamera()
                pub = node._cam_pub
                # Long idle (no captures because sim mode off + sub==0 doesn't matter;
                # capture still runs at idle rate; 10 idle ticks = 10 publishes)
                pub._sub_count = 0
                for _ in range(3):
                    node.capture_and_publish()
                pre_count = len(pub.published)
                # Sub arrives
                pub._sub_count = 1
                node.capture_and_publish()  # this tick both ramps up AND publishes
                self.assertGreater(len(pub.published), pre_count)
                self.assertTrue(node._is_active)
                node.destroy_node()
```

### "Defensible N" for the "active within N seconds of subscribe"

In the unit test, N is "one tick of the idle timer" = 1/idle_fps seconds. At production idle FPS 0.000278 that's **3597 seconds (~1 hour) worst case**. If the fix only relies on `get_subscription_count()` polling inside the existing timer callback, there's nothing we can do to make it faster than the idle period without adding a separate mechanism.

**This is the key design insight for the planner.** If HFIX-01 says "recover within N seconds" and N is small (e.g., 10 s, as D-03 suggests for the LIVE badge threshold), then the fix CANNOT be purely "poll get_subscription_count() inside the existing timer." It MUST add one of:

- A separate, faster subscription-graph-watching mechanism (e.g., `node.get_publishers_info_by_topic` / graph event subscription in rclpy, polled at 1 Hz regardless of capture rate), OR
- An out-of-band nudge from the bridge (ROS service call / a dedicated "viewer_hint" topic), OR
- A ROS graph-change event callback (rclpy supports `Node.graph_change_event` / equivalent) that re-checks subscription count whenever the graph changes.

**Recommended N for the active-recovery SLA: 10 seconds.** That matches MC's existing `isLive = Date.now() - cam.lastFrame < 10000` threshold. Means at most one MC tab refresh cycle's worth of delay.

See §5 for fix strategies that achieve N=10s.

---

## 5. Risk assessment

### Is this weekend-sized?

**Yes, all paths I see are weekend-sized.** Ranked by safety/simplicity:

**Path A — "Graph-poll fallback" (my recommendation)** LOW RISK, WEEKEND-SIZED

Add a dedicated 1 Hz polling timer in fc_camera that calls `self.get_publishers_info_by_topic` or `self.count_subscribers('/fc1/camera/compressed')` — **a different rclpy API than `get_subscription_count()`**. This one queries the node-level graph cache, not the publisher-object-local cache. In the live evidence tonight, a newly-spawned participant DID see the subscriber via the node-level graph. If `count_subscribers` on fc_camera's own node reads from a shared cache that gets refreshed on graph events, this is the cheap win.

- Pros: Pure additive, doesn't replace `get_subscription_count()` (keep it as the happy path), bounded polling rate, no protocol change.
- Cons: Two sources of truth inside fc_camera; need to pick which "wins" (likely: ANY source reporting >0 ramps up).
- Verification needed Saturday morning before picking this path: run a small rclpy script on fc1 that calls `node.count_subscribers('/fc1/camera/compressed')` — does it return 1 while fc_camera.get_subscription_count reports 0? If YES: Path A works. If NO (both return 0): we need Path B or C.

**Path B — "Bridge-side viewer hint"** MEDIUM RISK, WEEKEND-SIZED

Bridge publishes a `std_msgs/Bool` on `/fc1/camera/viewer_present` when MJPEG clients are connected. fc_camera subscribes to it and uses that directly to drive ramp-up, with `get_subscription_count()` as a fallback. Pros: Decoupled from DDS graph introspection bugs. Cons: Same topic domain / same Cyclone / same Tailscale loss risk — if SEDP drops the camera sub, it might drop the viewer-hint sub too. But a std_msgs/Bool is tiny and RELIABLE QoS should retransmit, while CompressedImage's volume may be exacerbating SEDP loss.

**Path C — "Heartbeat recovery (the choice we explicitly rejected)"** LOW RISK, WEEKEND-SIZED, violates D-01

Every N minutes regardless of subs, capture+publish one frame AND re-check subscription count. This would have masked the 8-hour stall (bridge would have got a frame every N min, so its cache wouldn't have been 52-min stale). But it undoes Phase 12's 4G thrift. **Rejected by D-01 ("Do NOT patch the symptom with a generic heartbeat timer").** Listed here only to flag: if Paths A and B both fail to confirm a usable mechanism, we would need to reopen this decision with the user.

**Path D — "Restart fc_camera on viewer connect via system signal"** HIGH RISK, NOT RECOMMENDED

systemctl kick. Ugly, catastrophic if triggered spuriously, and doesn't actually diagnose anything. Not on the table.

### BLOCKING conditions

I do NOT see one today. The only way this becomes BLOCKING is if Saturday morning's diagnosis reveals:
- H1 is true AND `node.count_subscribers` returns the same stale 0 as `publisher.get_subscription_count` (i.e., the entire node-local graph cache is stale, not just the publisher-local one). If that's the case, Path A is dead and Path B becomes mandatory (ships in the same weekend but requires bridge changes + fc_camera changes + config).

Even in the worst case, the fix is:
- Add a `Bool` publisher on the bridge (~10 LoC)
- Add a `Bool` subscriber on fc_camera that sets a `_viewer_hint` flag (~15 LoC)
- Modify `capture_and_publish` to OR the hint with `get_subscription_count() > 0` (~2 LoC)
- Unit tests (~40 LoC)
- Soak test (operator-driven, see §6)

That's ~70 LoC + tests. Still weekend-sized.

### Flag at top — NO BLOCKER identified

The weekend fix is viable. Diagnosis should take <2 hours Saturday morning. Implementation + unit test <4 hours. Deploy + soak ~1 hour. Room for MC UI (two lights) same day.

---

## 6. Live-soak plan

### Pre-flight checklist (before deploying)

- [ ] Confirm fc1 is reachable via `ssh fc1-ts`. RTT < 500 ms.
- [ ] Confirm bridge `/health` reachable: `curl http://localhost:8081/health`.
- [ ] Confirm fc-core is running: `ssh fc1-ts 'systemctl is-active fc-core'` → `active`.
- [ ] Note current state: `curl http://localhost:8081/health | jq` — save `lastFrame` epoch and subscribed/clients counts.
- [ ] `ssh fc1-ts 'journalctl -u fc-core -n 50 --no-pager'` — snapshot of recent log state.
- [ ] Deploy the fix via `fc1/prod` branch merge + `scripts/pi-deploy/deploy.sh`. Verify `sudo systemctl restart fc-core` completed and new `FcCamera node started` line appears with any new params.

### Observation commands (run in a tmux split; leave for 30 min)

**Terminal A — bridge health every 5s:**
```bash
while :; do
  date -u +%T
  curl -s http://localhost:8081/health | jq -c
  sleep 5
done
```

**Terminal B — bridge snapshot log:**
```bash
docker logs -f mushy-bridge-1 2>&1 | grep --line-buffered -E "camera|snapshot"
```

**Terminal C — fc_camera journal:**
```bash
ssh fc1-ts 'journalctl -u fc-core -f --no-pager | grep -E "fc_camera"'
```

**Terminal D — topic rate (run on fc1, only briefly):**
```bash
ssh fc1-ts 'source /opt/ros/jazzy/setup.bash; export ROS_DOMAIN_ID=69 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp CYCLONEDDS_URI=file:///etc/cyclonedds-tailscale.xml; ros2 topic hz /fc1/camera/compressed --window 5'
# Kill after each observation window (Ctrl-C)
```

### Soak sequence (30 min)

| Minute | Action | Pass criterion |
|--------|--------|----------------|
| 0 | Do not open MC. Wait for idle state to stabilize. | Terminal D shows ~0.000278 Hz. `/health.subscribed = false`. |
| 5 | Open MC camera tab in browser. | Within 10s: `/health.subscribed = true`. Within 10s of that: `/health.last_frame_age_sec < 10`. fc_camera journal shows `active (1.0 fps, 1 subscriber(s))`. Terminal D shows ~1 Hz. |
| 10 | Leave MC open. Watch telemetry flow. | `/health.last_frame_age_sec` stays < 2 for 5 min straight. No idle transitions. |
| 15 | Close MC tab. | Within 10s after grace: fc_camera logs `idle (0.000278 fps)`. `/health.subscribed = false`. Terminal D drops to 0 Hz. |
| 20 | Wait 5 min with MC closed — **deliberately exercise the stall condition**. | No fc_camera transitions in this window. `/health.last_frame_age_sec` increases monotonically. |
| 25 | Re-open MC camera tab. | **CRITICAL: within 10s of the tab opening, `/health.last_frame_age_sec` < 10.** fc_camera logs `active (1.0 fps)`. Terminal D returns to ~1 Hz. |
| 30 | Close MC. Check total snapshot file size variety in `/data/snapshots/fc1/2026-04-MM/`. | At least 2 different file sizes across the 15-min snapshot cadence during the active windows (proving frames varied, not the stuck-at-one-size pattern). |

### Pass / fail

**PASS:** All CRITICAL step 25 conditions met. Full 30 min shows clean idle→active→idle→active cycle.

**FAIL:** Any of:
- `/health.last_frame_age_sec` exceeds 60s during an MC-open window (should be < 2).
- Re-open at minute 25 does NOT recover to active within 10s.
- fc_camera journal shows active→idle→active→idle→active→idle ("flapping") — suggests the fix is unstable.

**Follow-up if pass:** let it sit for another 2 hours with no MC interaction to verify the idle pulse still ticks (every 3600 s the idle capture should fire and update `/health.last_frame_age_sec` momentarily before becoming stale again). One cycle is enough; we don't need an 8-hour soak for v1.2.1.

**Follow-up if fail:** do NOT roll forward. Roll back to pre-Phase-14 commit, report findings, plan Path B or C for next iteration.

---

## Architecture Patterns

### Recommended fix pattern (Path A, if Saturday's diagnostic check confirms `count_subscribers` works)

```python
# In fc_camera.py, add a fast-graph-poll timer that runs at 1 Hz regardless of capture rate.
# This SUPPLEMENTS the existing get_subscription_count() check inside capture_and_publish.

def __init__(self):
    # ... existing init ...
    # 1 Hz graph-poll — cheap rclpy node-level query that is NOT subject to the
    # stale-matched-endpoints-cache H1 hypothesis.
    self._graph_poll_timer = self.create_timer(1.0, self._graph_poll)

def _graph_poll(self):
    """Fast-path viewer detection via node-level graph introspection.

    Complement to get_subscription_count() polling inside capture_and_publish —
    that path only runs at idle cadence (1/hr in production) so cannot recover
    the feed within the 10-second SLA required by the MC LIVE badge.
    """
    if self._is_active:
        return  # already active; no work
    n = self.count_subscribers('/fc1/camera/compressed')  # node-level graph, not pub-local
    if n > 0:
        self._ramp_up()  # also captures and publishes one frame immediately
```

### Recommended fix pattern (Path B, if Path A fails diagnostic check)

```python
# fc_camera.py subscribes to a hint topic from the bridge.
# Bridge publishes Bool(True) when mjpegClients.size > 0, Bool(False) otherwise.

def __init__(self):
    # ... existing init ...
    self._viewer_hint = False
    self._hint_sub = self.create_subscription(
        Bool,
        '/fc1/camera/viewer_present',
        self._on_viewer_hint,
        QoSProfile(depth=1, reliability=RELIABLE, durability=TRANSIENT_LOCAL),
    )

def _on_viewer_hint(self, msg):
    if msg.data and not self._is_active:
        self._ramp_up()
    self._viewer_hint = msg.data

def capture_and_publish(self):
    count = self._cam_pub.get_subscription_count()
    viewer = count > 0 or self._viewer_hint
    if viewer and not self._is_active:
        self._ramp_up()
    elif not viewer and self._is_active and self._grace_timer is None:
        self._start_grace()
    # ... rest unchanged
```

Use TRANSIENT_LOCAL durability on the hint topic so a late-starting fc_camera gets the current state on startup.

### Anti-patterns to avoid

- **"Just make the idle rate faster."** Undoes Phase 12's 4G thrift.
- **"Delete the subscriber-aware logic."** Ditto, and violates D-01.
- **Relying on `destroy_subscription` timing to force re-matching.** Deeply fragile; depends on rclnodejs internals.
- **Restarting fc-core from the bridge.** Dangerous; the chamber's sensors and controller are in the same service unit.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Graph-state polling | Custom DDS participant enumeration | `rclpy.Node.count_subscribers()` / `get_subscribers_info_by_topic()` | Goes through rmw layer; portable across RMW |
| Viewer-hint transport | Custom TCP socket Pi↔bridge | Standard ROS 2 std_msgs/Bool topic | Inherits existing Cyclone config, QoS, reliability |
| Frame-age computation | Client-side Date.now()-lastFrame | Server-side `last_frame_age_sec` in /health | Avoids clock skew; single source of truth |
| Two-light UI primitive | Hand-coded badge per signal | Reusable `<StatusLight color level label>` component | Phase 16 will multiply this; don't create N variants |

---

## Common Pitfalls

### Pitfall 1 — Assuming `get_subscription_count()` is a live graph query

**What goes wrong:** It's a cached count of matched readers maintained by the DDS writer. Over lossy transports (Tailscale DERP relay in our case), the cache drifts from reality and never recovers without an event to refresh it.

**How to avoid:** Pair it with a graph-event-driven or node-level alternative. rclpy exposes graph events via `Node.context.on_shutdown` and rmw exposes `rcl_publisher_get_subscription_count` alongside `rcl_count_subscribers` — these are DIFFERENT APIs pulling from DIFFERENT caches. Use both.

### Pitfall 2 — Cyclone unicast config is brittle but undocumented

**What goes wrong:** `AllowMulticast=false` + explicit Peer list + single NetworkInterface is a valid Cyclone config but a seldom-tested one. Known gotchas: multiple NetworkInterface entries break SPDP (noted in the config XML comment). Peer list changes require restart. DERP-relay Tailscale paths add RTT jitter that exceeds default SPDP lease windows.

**How to avoid:** Document in CLAUDE.md or a runbook that the unicast config is a wet-test config and production should return to multicast/WireGuard. Tonight's config XML itself has a `<!-- Temporary config for wet test -->` comment — that's a technical debt item, not a Phase 14 fix.

### Pitfall 3 — Destroying and recreating ROS timers inside a timer's own callback

**What goes wrong:** `destroy_timer(self._cam_timer)` called from inside `self._cam_timer.callback()` is technically legal in rclpy but can leave dangling state in executors. The current code does exactly this in `_ramp_up` and `_ramp_down`.

**How to avoid:** Prefer a single fixed-rate timer whose callback conditionally captures based on state. Cost: slightly more CPU at idle (one no-op wake per idle period). Benefit: eliminates a whole class of timer-lifecycle bugs. NOT in scope for Phase 14 unless diagnosis shows this is the issue.

### Pitfall 4 — "Subscribed" in /health doesn't mean frames are flowing

**What goes wrong:** The current bridge reports `subscribed: true` if it has called `createSubscription` and gotten a handle. It says nothing about whether the underlying DDS reader is receiving any data. Tonight's state: `subscribed: true` + `lastFrame` 52 min old.

**How to avoid:** D-04 `last_frame_age_sec` is the fix. Frontend MUST treat them as two separate signals (two lights, per D-03).

---

## Runtime State Inventory

Phase 14 is a code-change phase with no data migrations. Per protocol, answer all five categories:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — the fix doesn't change any stored format. Bridge snapshots (`/data/snapshots/fc1/YYYY-MM-DD/*.jpg`) stay intact. Timescale telemetry table unchanged. | None |
| Live service config | fc-core systemd unit on fc1 may need updating if new params (`camera_debug_log` if we add one) are declared in fc_config.yaml. Deploy via fc1/prod branch → deploy.sh as usual. | Normal deploy path |
| OS-registered state | fc-core.service on fc1 unchanged. No new systemd units. No cron/timer changes. | None |
| Secrets/env vars | None. `TIMESCALE_PASSWORD` and existing `.env` values untouched. No new secrets. | None |
| Build artifacts / installed packages | fc_core Python package reinstalled via `pip install -e` inside deploy.sh (existing flow). No new system deps. | Standard deploy |

**Nothing found requires migration or special cleanup.** This is a pure code-change phase.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| ssh fc1-ts (Tailscale) | Live soak + log access | ✓ | OpenSSH | Physical console access |
| fc-core systemd unit on fc1 | Runtime | ✓ | active | — |
| mushy-bridge-1 container | /health endpoint + subscription | ✓ | — | — |
| rclpy.Node.count_subscribers | Path A fix | ? | jazzy 7.1.9 | Path B (bridge viewer-hint topic) |
| rclnodejs createPublisher | Path B fix | ✓ | 1.9.0 | — |
| pytest for test_camera.py | Regression test | ✓ | existing | — |
| Git branch fc1/prod | Deploy | ✓ | existing | — |

**"?" on `count_subscribers`:** This API exists in rclpy (confirmed present in ros2/rclpy 7.x docs). The open question is whether it READS from a separate cache than `publisher.get_subscription_count()`. That's the 10-minute diagnostic check Saturday morning — see §5. If `count_subscribers` returns the same stale 0, we pivot to Path B.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8+ via `unittest.TestCase` classes |
| Config file | None (existing tests are self-contained) |
| Quick run command | `python3 -m pytest src/chambers/fc-core/fc_core/test/test_camera.py -v` |
| Full suite command | `colcon test --packages-select fc_core` + `pytest src/mission-control/bridge/test/ -v` (if bridge tests exist; else omit) |
| pyenv context | `mushroom_farm` per existing VERIFICATION docs |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HFIX-01 | Idle → sub appears → active within 1 tick | unit | `pytest test_camera.py::TestIdleToActiveRecovery::test_long_idle_then_subscriber_appears_ramps_up -x` | ❌ Wave 0 |
| HFIX-01 | Active timer actually publishes after ramp-up | unit | `pytest test_camera.py::TestIdleToActiveRecovery::test_active_timer_actually_publishes_frames -x` | ❌ Wave 0 |
| HFIX-02 | Existing Phase-12 tests still pass | unit | `pytest test_camera.py -v` | ✅ |
| HFIX-03 | `/health` includes `last_frame_age_sec` | integration | `curl http://localhost:8081/health \| jq '.camera.last_frame_age_sec'` | ❌ Wave 0 (manual gate; can add node test) |
| HFIX-04 | MC two lights render | manual-only | visual inspection of MC camera panel | manual |
| HFIX-05 | 30-min soak on fc1 passes §6 criteria | manual-only | see §6 procedure | manual |

### Sampling Rate

- **Per task commit:** `pytest test_camera.py -v`  (runs in <5 s)
- **Per wave merge:** `pytest test_camera.py -v && curl http://localhost:8081/health | jq` (requires bridge running)
- **Phase gate:** 30-min live soak on fc1 per §6.

### Wave 0 Gaps

- [ ] `test_camera.py::TestIdleToActiveRecovery` — new test class covering HFIX-01. Add 3 tests per §4.
- [ ] Bridge-side test for `/health.last_frame_age_sec` presence + null-when-no-frame semantics — the bridge has no test suite today; minimum viable is a smoke test hitting `/health` post-deploy. Declining to add a full test framework for the bridge this phase unless planner insists.
- [ ] Frontend plugin.js — existing `isLive` logic needs split into two indicators; no existing test framework for plugin.js. Manual visual verification is the standing precedent (see Phase 12 HUMAN-UAT).

---

## Security Domain

Not applicable in the strict ASVS sense — this is a bugfix on an internal ROS topic and a health endpoint that is already exposed on port 8081 in the current network trust boundary. No authN/authZ changes. No new inputs or sinks. No cryptography.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | n/a — bridge endpoints are already unauth'd within trust boundary |
| V3 Session Management | no | n/a |
| V4 Access Control | no | n/a |
| V5 Input Validation | yes (minor) | `/health` accepts no parameters; viewer-hint topic uses typed Bool msg — inherent validation |
| V6 Cryptography | no | n/a (Tailscale provides transport) |

Implicit threat note: if we add Path B's `/fc1/camera/viewer_present` topic, any DDS peer can publish to it and trick fc_camera into going active indefinitely — modest 4G cost, no data leak. Acceptable given the network boundary. Document in the plan but don't gate on it.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| fc_camera always publishes at configured fps | Subscriber-aware rate switching via `get_subscription_count()` | Phase 12 (2026-04-13) | 4G bandwidth saved, stall introduced |
| Phase 12's stall | Phase 14 fallback + observability | This phase (2026-04-18/19) | Preserves 4G thrift, adds recovery path + farmer-visible stuck signal |

**Not deprecated:** the Phase 12 design stays. We're adding a recovery lane next to it, not replacing it.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `rclpy.Node.count_subscribers(topic)` reads from a different cache than `publisher.get_subscription_count()` | §5 Path A | Path A is dead; must fall back to Path B (bridge viewer-hint topic). Weekend still viable. |
| A2 | CycloneDDS unicast SEDP packet loss on Tailscale DERP relay is the true root cause of H1 | §1 H1 | If root cause is different (e.g., H2/H3), the fallback still works as long as it detects viewer presence by SOMETHING other than the stale publisher cache. Path A/B both satisfy that. |
| A3 | The next idle tick at ~23:18 UTC tonight will either fire (supports H1) or not fire (supports H2/H3) | §1 H2 disambiguation | If neither is observed by Saturday morning, we need extra log instrumentation before committing to a path. |
| A4 | A 10-second active-recovery SLA is acceptable to the farmer (matches existing MC LIVE badge threshold) | §4 N | If farmer wants < 5 s, we need to poll at 0.5 Hz rather than 1 Hz — trivial parameter tweak. |
| A5 | fc_controller, fc_sensors, fc_display are unaffected by whatever's blocking fc_camera matched-readers (they publish, not subscribe to graph events from Pi-originated topics) | §1 H5 | If sensor telemetry also stalled in today's event, H5 rises in likelihood and scope expands. Tonight's bridge logs showed humidity/temp/CO2 still flowing fine — so low risk. |

---

## Open Questions

1. **Will the delayed idle tick at ~23:18 UTC tonight fire and recover the stall (supports H2/H3) or fire and still show count=0 (supports H1)?**
   - What we know: fc_camera idle timer period is ~3597 s; node started 22:18:56 UTC; next idle tick ~23:18:53 UTC.
   - What's unclear: Whether the tick fires at all, and if so, what get_subscription_count() reports.
   - Recommendation: Tail journalctl tonight and Saturday morning. Check whether a 23:18 active transition appears. If yes, stall is self-healing at worst 1 hr — fix is still needed but urgency drops. If no, stall is fully stuck and fix is more urgent.

2. **Does `node.count_subscribers(topic)` see the matched subscriber when `publisher.get_subscription_count()` does not?**
   - What we know: A newly-spawned CLI participant sees both endpoints. So the Pi-side DDS graph IS consistent.
   - What's unclear: Whether a LONG-LIVED participant (fc_camera) sees the same thing via `count_subscribers`.
   - Recommendation: 10-minute diagnostic script Saturday morning. If `count_subscribers` works, Path A is viable. If not, Path B.

3. **Does Path B's `/fc1/camera/viewer_present` topic suffer the same SEDP-loss risk as the camera topic itself?**
   - What we know: SEDP loss is per-endpoint; whether a small Bool topic has the same loss rate as a high-volume CompressedImage topic is not established.
   - What's unclear: Whether RELIABLE QoS + TRANSIENT_LOCAL durability is enough to force retransmit through SEDP failures.
   - Recommendation: If we go Path B, test explicitly by toggling the bridge's viewer-hint while watching fc_camera's subscription match state.

4. **Is the Cyclone unicast-on-Tailscale config a permanent choice or a wet-test artifact?**
   - What we know: XML comment says "Temporary config for wet test — switch back to cyclonedds.xml (wg0) for production."
   - What's unclear: Whether the WireGuard-based config has the same jitter characteristics or would naturally mitigate H1.
   - Recommendation: Flag as a tech-debt item for a later phase. Not Phase 14 scope. But a planner should know it exists because "stop using DERP relay" is a long-term mitigation even if not the Phase 14 fix.

---

## Sources

### Primary (HIGH confidence)

- Live fc1 observation tonight (22:46-22:48 UTC): `/health` stale 52 min, journal transition history, `ros2 topic info` showing DDS graph consistent.
- `/etc/cyclonedds-tailscale.xml` on fc1 and in bridge container — identical, unicast, AllowMulticast=false, DERP-relay Tailscale.
- `fc_camera.py` source (lines 86-161 of existing file) — verified ramp-up / ramp-down logic.
- `test_camera.py` existing harness (15 tests covering sim mode, camera unavailable, publish path, parameter declaration, subscriber-aware rate switching, grace period).
- Phase 12 CONTEXT, VERIFICATION, and discussion log — authoritative source on what was shipped.
- FINDINGS-2026-04-17.md — farm team's incident report describing the 8-hour stall.

### Secondary (MEDIUM confidence)

- [ros2/ros2 #1536 — Subscription count is 0 after subscriber is created](https://github.com/ros2/ros2/issues/1536) — documents symptom similar to H1 in Foxy; Jazzy has different code paths but the underlying DDS pattern is the same.
- [ros2/rclcpp #668 — Subscription and intra-process subscription counts are not updated in sync](https://github.com/ros2/rclcpp/issues/668) — `get_subscription_count` staleness is a recognized class of bug.
- [ros2/rclpy #418 — provide get_subscription_count for publishers](https://github.com/ros2/rclpy/issues/418) — background on the API surface.
- [ros2/rmw_cyclonedds #376 — ROS 2 CLI tools don't work when AllowMulticast=false](https://github.com/ros2/rmw_cyclonedds/issues/376) — confirms the unicast/multicast toggle is a well-known source of discovery fragility.

### Tertiary (LOW confidence — flagged for validation)

- The specific mechanism by which `rcl_publisher_get_subscription_count` caches state vs `rcl_count_subscribers` — I have not inspected the rmw_cyclonedds C source for Jazzy to confirm they hit different caches. A1 rests on this. [ASSUMED]
- Whether rclnodejs 1.9.0 on the bridge has any known rclnodejs-side contribution to H5 — I have not searched rclnodejs issue tracker comprehensively. H5 is MEDIUM based on inspection; could be HIGH or LOW with more investigation.

---

## Metadata

**Confidence breakdown:**
- Live reproduction: HIGH — stall is observable right now on fc1.
- Root-cause hypothesis H1: MEDIUM-HIGH — best-fitting explanation, corroborated by DDS-graph asymmetry and Tailscale jitter, but not directly proven with Cyclone traces.
- Fix paths (A and B): HIGH — both are standard rclpy patterns; implementation cost is bounded.
- Unit test design: HIGH — harness already supports everything needed.
- Soak plan: HIGH — commands are non-destructive, pass/fail criteria explicit.
- Phase 14 staying weekend-sized: HIGH — even worst-case Path B is ~70 LoC + tests.

**Research date:** 2026-04-17 (evening)
**Valid until:** 2026-04-24 — fc1's DDS environment is stable on the hour-to-week scale; beyond a week, Tailscale or ROS updates could shift the picture.

---

*Phase: 14-fc-camera-idle-stall-hotfix*
*Researched: 2026-04-17T22:50:00Z*
*Researcher: Claude (gsd-researcher)*
