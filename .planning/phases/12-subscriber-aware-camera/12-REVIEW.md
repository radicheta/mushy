---
phase: 12-subscriber-aware-camera
reviewed: 2026-04-13T00:00:00Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - src/chambers/fc-core/config/fc_config.yaml
  - src/chambers/fc-core/fc_core/fc_camera.py
  - src/chambers/fc-core/fc_core/test/test_camera.py
  - src/mission-control/bridge/src/index.js
  - src/mission-control/frontend/plugins/fruiting-chamber/plugin.js
findings:
  critical: 0
  warning: 4
  info: 4
  total: 8
status: issues_found
---

# Phase 12: Code Review Report

**Reviewed:** 2026-04-13
**Depth:** standard
**Files Reviewed:** 5
**Status:** issues_found

## Summary

Five files were reviewed covering the Phase 12 subscriber-aware camera feature: the ROS2 camera node, its tests, the bridge server, the frontend plugin, and the config. The overall implementation is solid — the subscriber-count-driven rate switching logic is clean, error handling is non-blocking throughout, and the bridge correctly gates the ROS subscription on MJPEG client presence.

Four warnings were found: a ZeroDivisionError that crashes the camera node on startup if `camera_fps` or `camera_active_fps` is configured to zero; a race condition in the bridge where an early-connecting MJPEG client never gets camera frames; a fragile URL string replacement in the frontend badge; and a latent ROS topic name inconsistency between the camera node and bridge. Four informational items cover a misleading `noqa` comment, stale test documentation, a redundant in-function import, and a minor `innerHTML` hygiene note.

---

## Warnings

### WR-01: ZeroDivisionError crashes camera node if fps param is zero

**File:** `src/chambers/fc-core/fc_core/fc_camera.py:79` (also lines 138, 159)

**Issue:** `self.create_timer(1.0 / self._idle_fps, ...)` and `1.0 / self._active_fps` are bare divisions with no guard. If `camera_fps` or `camera_active_fps` is set to `0` in config or overridden at launch, the node crashes with `ZeroDivisionError` during `__init__` or inside `_ramp_up`/`_ramp_down`. The current YAML values (`0.000278` and `1.0`) are safe, but a misconfiguration silently kills the node with no explanatory log message.

**Fix:**
```python
# After reading fps parameters, add validation:
if self._idle_fps <= 0:
    self.get_logger().warn(
        f'fc_camera: camera_fps={self._idle_fps} is invalid; defaulting to 0.000278'
    )
    self._idle_fps = 0.000278
if self._active_fps <= 0:
    self.get_logger().warn(
        f'fc_camera: camera_active_fps={self._active_fps} is invalid; defaulting to 1.0'
    )
    self._active_fps = 1.0
```

---

### WR-02: MJPEG client connecting before ROS init never receives frames

**File:** `src/mission-control/bridge/src/index.js:69`

**Issue:** `ensureCameraSubscribed()` returns early when `rosNode === null`. `rosNode` is set only after `rclnodejs.init().then()` completes. If an HTTP client hits `/camera/mjpeg` during the ROS initialization window, `ensureCameraSubscribed()` is a no-op and no retry is scheduled. That client will hang in the MJPEG stream forever receiving no frames. Typical ROS startup takes a few hundred milliseconds so this window is small but real, especially on the Pi 3B.

**Fix:**
```javascript
app.get('/camera/mjpeg', (req, res) => {
    // ... write headers, add to mjpegClients ...
    mjpegClients.add(res);
    ensureCameraSubscribed();  // no-op if rosNode not ready yet

    req.on('close', () => {
        mjpegClients.delete(res);
        maybeCameraUnsubscribe();
    });
});

// In rclnodejs.init().then(), after setting rosNode:
rosNode = node;
// Catch clients that connected before ROS was ready
if (mjpegClients.size > 0) {
    ensureCameraSubscribed();
}
```

---

### WR-03: Badge health URL derived via fragile string replacement

**File:** `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js:315`

**Issue:** `cameraUrl.replace('/camera/mjpeg', '/health')` silently produces a wrong URL if `options.cameraUrl` is customised to any path that does not contain the literal substring `/camera/mjpeg` (e.g. `http://host:8081/camera/stream`). The `replace` call returns the original string unchanged, so `healthUrl === cameraUrl`, and `fetch(healthUrl)` hits the MJPEG endpoint and returns non-JSON, causing the badge to stay in its initial state indefinitely with no error surfaced.

**Fix:** Derive `healthUrl` from the base URL rather than by string surgery:
```javascript
// Replace string-replacement with URL parsing:
var baseUrl = cameraUrl.replace(/\/camera\/.*$/, '');
var healthUrl = baseUrl + '/health';
// Or better, accept healthUrl as a separate plugin option:
var healthUrl = (options && options.healthUrl) || 'http://localhost:8081/health';
```

---

### WR-04: Latent ROS topic name inconsistency (relative vs absolute)

**File:** `src/mission-control/bridge/src/index.js:72` vs `src/chambers/fc-core/fc_core/fc_camera.py:75`

**Issue:** The bridge subscribes to `'/fc1/camera/compressed'` (absolute path, leading slash). The camera node publishes to `'fc1/camera/compressed'` (relative path, no leading slash). In ROS2, a relative topic name is resolved against the node's namespace. With the default empty namespace both resolve to `/fc1/camera/compressed` and the system works. If a namespace is ever added to the camera node (e.g. for multi-chamber support — a stated roadmap goal), the resolved topic becomes `/<namespace>/fc1/camera/compressed` while the bridge still subscribes to `/fc1/camera/compressed`, silently breaking camera streaming.

**Fix:** Make the camera publisher use an absolute topic name to match the bridge:
```python
# fc_camera.py line 75 — use absolute path
self._cam_pub = self.create_publisher(
    CompressedImage, '/fc1/camera/compressed', 10
)
```

---

## Info

### IN-01: Misleading `# noqa: F401` comment on used import

**File:** `src/chambers/fc-core/fc_core/fc_camera.py:56`

**Issue:** `import cv2  # noqa: F401 -- available on Pi via apt`. The `F401` rule flags unused imports. `cv2` is used immediately on the next line (`cv2.VideoCapture(device)`), so the noqa tag is unnecessary and the comment is misleading — it implies the import might look unused, when it is clearly used.

**Fix:** Remove the `# noqa: F401` annotation; keep the explanatory comment if desired:
```python
import cv2  # system package (python3-opencv) on the Pi
```

---

### IN-02: Redundant `import cv2` inside `capture_and_publish`

**File:** `src/chambers/fc-core/fc_core/fc_camera.py:107`

**Issue:** `import cv2` appears twice — once at construction (line 56, inside the non-simulation branch) and again at the top of `capture_and_publish` (line 107). Python caches the module after the first import so this is not a performance issue, but it implies cv2 might not be available at call time, which is confusing and inconsistent with the constructor-level import pattern.

**Fix:** Remove the redundant `import cv2` from `capture_and_publish`. The module is guaranteed to be importable if `self.cap` is not None (since construction would have failed otherwise), and early-exit at line 103 handles the `cap is None` / closed cases.

---

### IN-03: Test class docstring and parameter count stale after Phase 12 params added

**File:** `src/chambers/fc-core/fc_core/test/test_camera.py:272`

**Issue:** `TestCameraParametersDeclared` has the docstring `"All 6 required parameters are declared on the node"` and the `required_params` list contains only the original 6 parameters. The node now declares 8 parameters (`camera_active_fps` and `camera_subscriber_grace_sec` were added in Phase 12). The new params are covered by `TestSubscriberAwareCamera.test_new_params_declared`, but the docstring count is wrong and a reader of `TestCameraParametersDeclared` gets an incomplete picture.

**Fix:** Update the docstring and extend `required_params`:
```python
"""Test 4: All 8 required parameters are declared on the node."""
required_params = [
    'camera_simulation_mode',
    'camera_device',
    'camera_width',
    'camera_height',
    'camera_fps',
    'camera_jpeg_quality',
    'camera_active_fps',
    'camera_subscriber_grace_sec',
]
```

---

### IN-04: `container.innerHTML` built via string concatenation with unescaped option value

**File:** `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js:329`

**Issue:** `cameraUrl` is embedded directly into an HTML string as an `src` attribute value delimited by double quotes: `'<img src="' + cameraUrl + '"'`. If `cameraUrl` contains a double-quote character (e.g. a malformed option), it would break out of the attribute. Risk is low since `cameraUrl` is operator-configured rather than user-supplied, but it is an innerHTML injection pattern.

**Fix:** Set the `src` via DOM API after inserting the element, or encode the URL:
```javascript
// After setting container.innerHTML, find the img and set src programmatically:
var img = container.querySelector('img');
if (img) img.src = cameraUrl;
```

---

_Reviewed: 2026-04-13_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
