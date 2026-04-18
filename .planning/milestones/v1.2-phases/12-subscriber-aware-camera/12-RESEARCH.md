# Phase 12: Subscriber-Aware Camera - Research

**Researched:** 2026-04-13
**Domain:** ROS2 rclpy timer management, publisher subscriber count, rclnodejs subscription lifecycle
**Confidence:** HIGH

## Summary

This phase is a focused, self-contained change to two files: `fc_camera.py` (Pi side) and `bridge/src/index.js` (elder-plops side). The user decisions in CONTEXT.md are fully locked. Research confirms all required APIs exist in the installed stack. There are no new dependencies to install.

The core mechanism is straightforward: `publisher.get_subscription_count()` in rclpy returns an integer cheaply on every timer tick. When count transitions from 0 to >0, the idle timer is cancelled and a new active-rate timer is created. When it drops to 0 and stays 0 past a grace period, the active timer is cancelled and the idle timer is recreated. On the bridge side, `node.createSubscription()` / `node.destroySubscription(sub)` in rclnodejs (v1.9.0) are the conditional subscribe/unsubscribe hooks that make fc_camera's count actually reflect viewer presence.

**Primary recommendation:** Use `timer.cancel()` + store reference for rate switching (avoids ROS2 create/destroy overhead on every tick), with a fallback `_grace_timer` (a separate one-shot timer) to handle the 5-second disconnect grace period. The existing test harness in `test_camera.py` supports this with minor extensions to `FakeTimer` and `FakePublisher`.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Active FPS is 1.0 when subscribers are present (live enough to check chamber, low enough for 4G — ~20-40KB/frame at 640x480 q65)
- **D-02:** Idle FPS is ~1 frame/hour (0.000278) when no subscribers — down from current 0.0167 (1 frame/min)
- **D-03:** Existing `camera_fps` parameter becomes the idle rate. Two new params: `camera_active_fps` (default 1.0) and `camera_subscriber_grace_sec` (default 5.0)
- **D-04:** Use `publisher.get_subscription_count()` on `/fc1/camera/compressed` — checked on every timer tick (cheap integer read, no separate polling timer)
- **D-05:** When subscriber count goes from 0 to >0, destroy idle timer and create new timer at active FPS rate
- **D-06:** When subscriber count drops to 0, start a grace countdown (D-07); if still 0 after grace period, destroy active timer and create idle timer
- **D-07:** 5-second grace period before dropping from active to idle — survives a page refresh. Configurable via `camera_subscriber_grace_sec`

### Claude's Discretion

- Timer swap implementation details (destroy/recreate vs. other ROS2 patterns)
- Logging verbosity for rate transitions
- Whether to capture+publish immediately on ramp-up or wait for next timer tick
- Test structure for new subscriber-aware behavior

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CAM-01 | fc_camera publishes at full configured rate only when subscribers are present on `/fc1/camera/compressed` | `publisher.get_subscription_count()` verified in rclpy (Jazzy); timer cancel/recreate pattern documented |
| CAM-02 | fc_camera drops to idle rate (1 frame/min or less) when no subscribers are connected | Locked idle rate is 1 frame/hour (0.000278 fps) — lower than requirement floor of "1 frame/min or less" |
| CAM-03 | Transition between idle and active is automatic and transparent to bridge/Mission Control | Bridge conditional subscribe/unsubscribe via `node.destroySubscription()` confirmed in rclnodejs v1.9.x |
</phase_requirements>

## Standard Stack

### Core (no new installs)

| Library | Version | Purpose | Notes |
|---------|---------|---------|-------|
| rclpy (rclpy.node.Node) | Jazzy (3.x) | Timer management, publisher subscriber count | Already installed on Pi |
| rclnodejs | ^1.9.0 (package.json) | Bridge Node destroy/create subscription | Already in bridge container |
| OpenCV (cv2) | system apt | Frame capture — no change | No change needed |

### New Parameters (fc_config.yaml)

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `camera_active_fps` | 1.0 | FPS when subscribers are present |
| `camera_subscriber_grace_sec` | 5.0 | Seconds before dropping to idle after last subscriber disconnects |
| `camera_fps` (existing) | 0.000278 | Becomes the idle FPS (1 frame/hour) |

**Installation:** None required. All dependencies are already present.

## Architecture Patterns

### Recommended Project Structure (no changes)

```
src/chambers/fc-core/fc_core/
├── fc_camera.py              # All changes happen here
├── test/test_camera.py       # New tests appended here
src/chambers/fc-core/config/
└── fc_config.yaml            # Two new params added
src/mission-control/bridge/src/
└── index.js                  # Conditional subscribe/unsubscribe added
```

### Pattern 1: Timer Cancel/Recreate for Rate Switching (fc_camera.py)

**What:** Store the active timer reference. To switch rates: cancel the current timer, create a new one at the new period.
**Why over destroy/recreate:** `timer.cancel()` + new `create_timer()` is the documented approach. `node.destroy_timer()` is also valid but slightly heavier (unregisters from the executor); for a once-per-subscriber-change operation either works fine. Given D-05 says "destroy idle timer and create new timer," use `node.destroy_timer()` as specified.
**When to use:** At the moment subscriber count crosses 0↔N boundary.

Implementation outline:
```python
# Source: rclpy docs (https://docs.ros.org/en/jazzy/p/rclpy/rclpy.html)
# [VERIFIED: official ROS2 Jazzy docs]

class FcCamera(Node):
    def __init__(self):
        # ... existing setup ...
        self._idle_fps = self.get_parameter('camera_fps').value          # 0.000278
        self._active_fps = self.get_parameter('camera_active_fps').value # 1.0
        self._grace_sec = self.get_parameter('camera_subscriber_grace_sec').value  # 5.0

        self._is_active = False
        self._grace_timer = None
        # Start in idle mode
        self._cam_timer = self.create_timer(1.0 / self._idle_fps, self.capture_and_publish)

    def capture_and_publish(self):
        # Check subscriber count on every tick (cheap integer read)
        count = self._cam_pub.get_subscription_count()

        if count > 0 and not self._is_active:
            self._ramp_up()
        elif count == 0 and self._is_active and self._grace_timer is None:
            self._start_grace()

        # ... rest of capture logic unchanged ...

    def _ramp_up(self):
        if self._grace_timer is not None:
            self.destroy_timer(self._grace_timer)
            self._grace_timer = None
        self.destroy_timer(self._cam_timer)
        self._cam_timer = self.create_timer(1.0 / self._active_fps, self.capture_and_publish)
        self._is_active = True
        self.get_logger().info(f'fc_camera: active ({self._active_fps} fps)')

    def _start_grace(self):
        self._grace_timer = self.create_timer(self._grace_sec, self._grace_expired)

    def _grace_expired(self):
        self.destroy_timer(self._grace_timer)
        self._grace_timer = None
        if self._cam_pub.get_subscription_count() == 0:
            self._ramp_down()

    def _ramp_down(self):
        self.destroy_timer(self._cam_timer)
        self._cam_timer = self.create_timer(1.0 / self._idle_fps, self.capture_and_publish)
        self._is_active = False
        self.get_logger().info(f'fc_camera: idle ({self._idle_fps} fps)')
```

### Pattern 2: Conditional Subscribe/Unsubscribe in Bridge (index.js)

**What:** Keep the camera subscription reference. Subscribe when first MJPEG client connects, unsubscribe when last disconnects.
**Why:** This is what makes `get_subscription_count()` on fc_camera accurately reflect viewer presence. Without it, the bridge would be a permanent subscriber and fc_camera would stay in active mode forever.

```javascript
// Source: rclnodejs docs + GitHub issue #628
// [VERIFIED: github.com/RobotWebTools/rclnodejs/issues/628]

let cameraSubscription = null;

function ensureCameraSubscribed(node) {
    if (cameraSubscription !== null) return;
    cameraSubscription = node.createSubscription(
        'sensor_msgs/msg/CompressedImage',
        '/fc1/camera/compressed',
        (msg) => {
            const buf = Buffer.from(msg.data);
            pushFrame(buf);
        }
    );
    console.log('[camera] subscribed to /fc1/camera/compressed');
}

function maybeCameraUnsubscribe(node) {
    if (mjpegClients.size > 0 || cameraSubscription === null) return;
    node.destroySubscription(cameraSubscription);
    cameraSubscription = null;
    console.log('[camera] unsubscribed from /fc1/camera/compressed');
}
```

Hook into the `/camera/mjpeg` endpoint and `req.on('close', ...)` handler:
```javascript
app.get('/camera/mjpeg', (req, res) => {
    // ... writeHead ...
    mjpegClients.add(res);
    ensureCameraSubscribed(node);  // <-- add this
    req.on('close', () => {
        mjpegClients.delete(res);
        maybeCameraUnsubscribe(node);  // <-- add this
    });
});
```

Note: `node` must be in scope. Currently it's declared inside the `.then()` callback — these functions need to close over it or receive it as a parameter.

### Anti-Patterns to Avoid

- **Polling subscriber count in a separate timer:** Not needed — check inline on every capture tick (D-04). Adding a second timer is unnecessary complexity.
- **Starting grace period on every tick where count==0:** Only start grace when transitioning FROM active (i.e., when `self._is_active` is True). The `_grace_timer is None` guard prevents re-entering.
- **Recreating the grace timer before the old one fires:** Always `destroy_timer(self._grace_timer)` before creating a new one (ramp-up path does this).
- **Bridge staying permanently subscribed:** The whole mechanism depends on the bridge unsubscribing when no MJPEG clients are connected. If this is skipped, `get_subscription_count()` on fc_camera always returns 1 and the node never idles.
- **Immediate publish on ramp-up:** The grace is 5s so the first frame after ramp-up is already in flight. No special "publish immediately" logic is needed — next timer tick fires at 1.0 fps which is fast enough.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Subscriber presence detection | Custom topic echo/counter | `publisher.get_subscription_count()` | Built into rcl_publisher; free, atomic, no race condition |
| Timed grace period | Custom sleep/time.time() counter | `node.create_timer()` (one-shot via destroy after fire) | Integrates with ROS executor loop; no threads needed |
| Bridge conditional subscribe | WebSocket message protocol | `node.destroySubscription()` | Native rclnodejs API; clean resource lifecycle |

**Key insight:** ROS2 already solves the subscriber-counting and timer-management problems natively. The entire implementation is wiring together three existing primitives.

## Common Pitfalls

### Pitfall 1: Grace Timer Leaking on Node Destroy
**What goes wrong:** If `destroy_node()` is called while `_grace_timer` is non-None, the timer handle leaks.
**Why it happens:** `destroy_node()` in the current code only releases `self.cap`. The grace timer is not tracked by the standard node cleanup unless explicitly destroyed.
**How to avoid:** Override `destroy_node()` to call `self.destroy_timer(self._grace_timer)` if it is not None, before calling `super().destroy_node()`.
**Warning signs:** Log warning about uncleaned handles at shutdown.

### Pitfall 2: Race Between Grace Expiry and Ramp-Up
**What goes wrong:** A subscriber connects during the 5-second grace window; the grace timer fires anyway and drops to idle.
**Why it happens:** Grace timer callback is queued in the executor — by the time it fires, count may be >0.
**How to avoid:** In `_grace_expired()`, re-check `get_subscription_count()` before calling `_ramp_down()`. The pattern above already does this.

### Pitfall 3: Bridge Node Scope for destroySubscription
**What goes wrong:** `ensureCameraSubscribed` / `maybeCameraUnsubscribe` are defined at module scope but need the `node` object which is created inside the `rclnodejs.init().then()` callback.
**Why it happens:** `node` is a local variable inside the async callback.
**How to avoid:** Either (a) make the functions accept `node` as parameter, or (b) store node in a module-level variable (`let rosNode = null`) set inside the `.then()` callback.

### Pitfall 4: Idle Rate at 1/hour Creates Long Startup Latency
**What goes wrong:** First frame from fc_camera on boot takes up to 1 hour. Phase 13 snapshot logic depends on `latestFrame` being populated within its capture window.
**Why it happens:** Timer period is 3600 seconds.
**How to avoid:** Not a problem for this phase — the bridge's `/camera/snapshot` endpoint uses `latestFrame` which gets populated once fc_camera captures. Phase 13 research should verify the snapshot window vs. idle tick timing.
**Note:** The bridge currently also runs `saveSnapshot()` on a 15-minute interval timer. If `latestFrame` is null for the first hour, no snapshot is saved. This is acceptable per the CONTEXT.md decision ("Phase 13 daily snapshot still has 24 frames/day to pick from") but the first day may have fewer snapshots.

### Pitfall 5: FakePublisher Missing get_subscription_count
**What goes wrong:** Tests fail with AttributeError because `FakePublisher` in `test_camera.py` does not implement `get_subscription_count()`.
**Why it happens:** Existing FakePublisher was written before subscriber-aware behavior existed.
**How to avoid:** Add `get_subscription_count(self) -> int` to FakePublisher in the test harness, with a settable `_sub_count` attribute for test control.

### Pitfall 6: FakeTimer Missing for Grace Timer
**What goes wrong:** Tests that call `_ramp_up` or `_start_grace` fail because `create_timer` returns a `FakeTimer` but `_grace_timer` is compared against `None`.
**Why it happens:** `FakeTimer` is already present; no issue here — just need `destroy_timer` implemented on FakeNode.
**How to avoid:** Add `destroy_timer(self, timer)` to FakeNode — remove from `self._timers` list if present.

## Code Examples

### Verified: get_subscription_count on rclpy Publisher
```python
# Source: https://docs.ros.org/en/jazzy/p/rclpy/rclpy.html
# [VERIFIED: official Jazzy docs — get_subscription_count listed in Publisher methods]
count = self._cam_pub.get_subscription_count()  # returns int
```

### Verified: destroy_timer on rclpy Node
```python
# Source: https://docs.ros2.org/foxy/api/rclpy/api/node.html (stable since Foxy, present in Jazzy)
# [VERIFIED: destroy_timer returns True if successful, False otherwise]
success = self.destroy_timer(self._cam_timer)
self._cam_timer = self.create_timer(new_period, self.capture_and_publish)
```

### Verified: timer.cancel() for temporary pause (NOT used here, for reference)
```python
# Source: https://docs.ros.org/en/rolling/p/rclpy/api/timers.html
# [VERIFIED: cancel() pauses; reset() resumes; does not unregister from executor]
self._cam_timer.cancel()   # pause
self._cam_timer.reset()    # resume
```

### Verified: node.destroySubscription in rclnodejs
```javascript
// Source: https://github.com/RobotWebTools/rclnodejs/issues/628
// [VERIFIED: confirmed by maintainer, available since at least rclnodejs 0.22]
node.destroySubscription(subscription);
```

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Fixed 1 frame/min (0.0167 fps) | Idle 1/hour + active 1 fps | ~60x less bandwidth at idle; full rate when viewed |
| Bridge always subscribed | Bridge conditionally subscribed | fc_camera subscriber count accurately reflects viewer presence |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `node.destroySubscription()` is available in rclnodejs ^1.9.0 (package.json pin) | Bridge pattern | LOW risk — confirmed in 0.22+ GitHub issue; 1.9.x is far newer |
| A2 | `publisher.get_subscription_count()` reflects bridge subscription in real time | Architecture | LOW risk — backed by rcl_publisher C layer; standard ROS2 behavior |
| A3 | Grace timer as a one-shot `create_timer` + `destroy_timer` in callback is safe under the ROS2 executor | Pitfalls | MEDIUM risk if there are re-entrancy issues; but this is a single-threaded node |

## Open Questions

1. **Immediate capture on ramp-up (Claude's Discretion)**
   - What we know: First active-rate frame won't fire until 1.0 second after ramp-up
   - What's unclear: Whether user wants instant frame at the moment of ramp-up (sub-second visual feedback)
   - Recommendation: Skip it — 1 fps means the first frame arrives within 1 second, which is imperceptible in Mission Control's MJPEG stream. Avoids complexity.

2. **Logging verbosity (Claude's Discretion)**
   - Recommendation: Log at INFO on every rate transition (ramp-up/ramp-down). Do not log on each tick where count is checked. This gives operators visibility without log spam.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| rclpy (Jazzy) | fc_camera.py timer/publisher APIs | ✓ on Pi (fc1) | Jazzy | — |
| rclnodejs | bridge conditional subscribe | ✓ in bridge container | ^1.9.0 | — |
| python3-opencv | Frame capture | ✓ on Pi | system apt | simulation_mode=true for test |
| pytest | Test execution | ✓ (existing tests run) | system | — |

[VERIFIED: package.json shows rclnodejs ^1.9.0; fc_camera.py and bridge already deployed and running]

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (unittest.TestCase in test_camera.py) |
| Config file | none — run directly via pytest |
| Quick run command | `pytest src/chambers/fc-core/fc_core/test/test_camera.py -x` |
| Full suite command | `colcon test --packages-select fc_core` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CAM-01 | fc_camera publishes at active FPS when subscriber count > 0 | unit | `pytest src/chambers/fc-core/fc_core/test/test_camera.py::TestSubscriberAwareCamera -x` | Wave 0 |
| CAM-02 | fc_camera stays at idle FPS when subscriber count == 0 | unit | `pytest src/chambers/fc-core/fc_core/test/test_camera.py::TestSubscriberAwareCamera -x` | Wave 0 |
| CAM-03 | Grace period prevents drop to idle during page refresh window | unit | `pytest src/chambers/fc-core/fc_core/test/test_camera.py::TestSubscriberGracePeriod -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest src/chambers/fc-core/fc_core/test/test_camera.py -x`
- **Per wave merge:** `colcon test --packages-select fc_core`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `TestSubscriberAwareCamera` class in `test_camera.py` — covers CAM-01, CAM-02
- [ ] `TestSubscriberGracePeriod` class in `test_camera.py` — covers CAM-03
- [ ] Extend `FakePublisher` with `get_subscription_count()` method and settable `_sub_count`
- [ ] Extend `FakeNode` with `destroy_timer(timer)` method
- [ ] Bridge tests are manual-only (no JS test harness in this project)

## Security Domain

> No new attack surfaces introduced. This phase changes publish rate based on subscriber count — no user input, no new HTTP endpoints, no new data paths. Existing CORS and input validation in bridge are unchanged. Security section skipped per phase scope.

## Sources

### Primary (HIGH confidence)
- [rclpy Jazzy Publisher docs](https://docs.ros.org/en/jazzy/p/rclpy/rclpy.html) — `get_subscription_count()` verified in Publisher methods
- [rclpy Node docs (Foxy stable)](https://docs.ros2.org/foxy/api/rclpy/api/node.html) — `destroy_timer()`, `create_timer()`, `destroy_subscription()` verified
- [rclpy Timer docs (Rolling)](https://docs.ros.org/en/rolling/p/rclpy/api/timers.html) — `cancel()`, `reset()`, `is_canceled()` verified on Timer object
- [rclnodejs GitHub issue #628](https://github.com/RobotWebTools/rclnodejs/issues/628) — `node.destroySubscription(sub)` confirmed by maintainer

### Secondary (MEDIUM confidence)
- [rclpy issue #418](https://github.com/ros2/rclpy/issues/418) — `get_subscription_count()` added in 2019, closed via PR #429; stable across all subsequent versions including Jazzy

### Tertiary (LOW confidence — not needed for this phase)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all APIs verified in official docs or maintainer confirmation
- Architecture: HIGH — pattern follows existing FcCamera code; no new paradigms
- Pitfalls: HIGH — derived from reading the actual code and known ROS2 timer lifecycle docs
- Bridge pattern: HIGH — rclnodejs destroySubscription confirmed via GitHub issue maintainer response

**Research date:** 2026-04-13
**Valid until:** 2026-10-13 (stable ROS2 APIs change infrequently)
