# Phase 08: Pi Camera Feed in Mission Control - Research

**Researched:** 2026-04-08
**Domain:** ROS2 camera publishing, Node.js MJPEG streaming, OpenMCT custom view plugin
**Confidence:** HIGH (core stack verified), MEDIUM (OpenMCT view API specifics)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Camera publishes as a ROS2 node using `sensor_msgs/Image` or `sensor_msgs/CompressedImage` topics. Rover-ready pattern — any future camera just publishes to the same topic pattern.
- **D-02:** Use compressed JPEG over ROS topics (`fc/camera/compressed`) to minimize bandwidth. Cellular link is the constraint.
- **D-03:** MJPEG stream served from the bridge on elder-plops. Bridge subscribes to the ROS compressed image topic and re-serves as an HTTP MJPEG endpoint. Browser-native, no transcoding, no WebRTC.
- **D-04:** Low framerate by default — 1-2 FPS for live monitoring.
- **D-05:** Resolution capped at 640x480 or 720p max. Configurable in `fc_config.yaml`.
- **D-06:** JPEG compression quality configurable (default ~60-70%).
- **D-07:** USB webcam accessed via v4l2 (Video4Linux2).
- **D-08:** Camera node is a ROS2 Python node in `fc_core` package, launched alongside sensor/controller nodes. Auto-starts with the systemd service.
- **D-09:** Topic naming: `fc/camera/compressed` for frames, `fc/camera/info` for camera metadata.
- **D-10:** Bridge captures periodic snapshots (configurable interval, default every 15 minutes) and saves to elder-plops filesystem.
- **D-11:** Snapshots stored in date-organized directory structure on elder-plops (e.g., `/data/snapshots/fc1/2026-04-08/`).
- **D-12:** Snapshot metadata (timestamp, camera ID) logged — ready for future time-lapse or FarmOS observation attachments.
- **D-13:** Camera feed appears as a dedicated view/panel in Mission Control. Simple `<img>` tag pointing at the MJPEG endpoint from the bridge.
- **D-14:** OpenMCT plugin registers the camera as a telemetry source with a custom view type (image stream, not chart).

### Claude's Discretion
- Exact v4l2 configuration and device detection
- ROS2 node implementation details (cv_bridge vs raw v4l2 + manual JPEG)
- MJPEG endpoint implementation in the Node.js bridge
- OpenMCT plugin structure for camera view
- Snapshot directory cleanup/rotation policy
- Error handling when camera is disconnected

### Deferred Ideas (OUT OF SCOPE)
- Time-lapse assembly (ffmpeg/stitch)
- Contamination detection (ML/visual anomaly)
- Growth stage classification (ML)
- Multi-camera support (camera ID namespacing)
- FarmOS image observations
- Pan/tilt/zoom control
</user_constraints>

---

## Summary

This phase adds a USB webcam feed from the fc1 Raspberry Pi to Mission Control (OpenMCT). There are three distinct implementation domains: (1) the ROS2 camera node on the Pi capturing frames and publishing as `sensor_msgs/CompressedImage`, (2) the Node.js bridge on elder-plops subscribing to the ROS topic and re-serving frames as an HTTP MJPEG stream, and (3) an OpenMCT plugin registering a custom view type that displays a live `<img>` element pointing at the MJPEG endpoint.

The key architectural insight: because the bridge already runs `network_mode: host` and already has rclnodejs for ROS subscriptions, adding MJPEG serving is additive. The camera node on the Pi follows the exact same Python ROS2 node pattern as `fc_sensors.py` — timer-based, config-driven, publish to a topic. The MJPEG stream is implemented inline in Express with no heavy library needed.

The OpenMCT side is the most novel. The existing plugin pattern (telemetry provider + object provider) is for numeric values charted over time. Camera view needs a different object type with a custom view provider — one that renders an `<img>` tag rather than a chart. The simplest correct approach registers a `fruiting-chamber.camera` type, adds it to the root composition, and installs a view provider whose `view()` method sets `innerHTML` to `<img src="http://...:8081/camera/mjpeg">`.

**Primary recommendation:** Custom Python ROS2 node using `cv2` (OpenCV) for v4l2 capture and manual JPEG encoding + CompressedImage publish. Bridge adds an Express route serving multipart MJPEG from a push-based frame buffer. OpenMCT gets a minimal custom view provider — no Imagery plugin, just `objectViews.addProvider` with a custom `canView` check and `view()` that injects the `<img>` element.

---

## Standard Stack

### Core (Pi — Camera Node)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `opencv-python` | `4.x` (system pip) | v4l2 capture + JPEG encode | Universally available on Pi, supports all V4L2 webcams, one-line capture |
| `sensor_msgs` | ROS2 Jazzy (system) | `CompressedImage` message type | Standard ROS image message, already in workspace |
| `rclpy` | ROS2 Jazzy (system) | ROS2 Python node runtime | Already installed and in use by fc_sensors.py |

**Why not ros-jazzy-v4l2-camera:** D-08 locks camera as a Python node in `fc_core`. The `v4l2_camera` apt package is a standalone C++ node that runs separately — it doesn't integrate into the existing launch/systemd setup without significant restructuring. A custom Python node is 80 lines and follows the exact fc_sensors.py pattern. [VERIFIED: docs.ros.org/en/jazzy/p/v4l2_camera/]

**Why not cv_bridge:** `cv_bridge` is used to convert between OpenCV `Mat` and `sensor_msgs/Image`. Since D-02 requires compressed JPEG directly, we can skip cv_bridge entirely: capture with `cv2.VideoCapture`, encode with `cv2.imencode('.jpg', frame)`, wrap in `CompressedImage`. No bridge step needed. [ASSUMED: cv_bridge adds dependency weight without benefit here]

### Core (Bridge — MJPEG Server)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `express` | `^5.2.1` (already installed) | HTTP route for MJPEG endpoint | Already in bridge; no new dependency |
| `rclnodejs` | `^1.9.0` (already installed) | Subscribe to `CompressedImage` topic | Already in bridge; handles all ROS subscriptions |
| Node.js built-in streams | — | Multipart response writing | No library needed for MJPEG |

**MJPEG library situation:** `mjpeg-server` (npm) is last updated 2022, last version 0.3.1. [VERIFIED: npm registry 2026-04-08]. `node-mjpeg-server` has 10 total commits, is minimally maintained. The raw multipart write pattern is 15 lines of Express — no library needed or warranted.

### Core (Bridge — Snapshot Storage)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Node.js `fs` (built-in) | — | Write JPEG buffer to date-organized path | No dependency, filesystem write |
| Node.js `path` (built-in) | — | Construct `/data/snapshots/fc1/YYYY-MM-DD/` paths | Standard |

### Core (OpenMCT — Camera View Plugin)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Vanilla JS | — | View provider registering `<img>` tag | Plugin follows same pattern as existing plugin.js |
| No new npm package | — | Camera view is HTML, not a chart | `<img src="...">` is browser-native for MJPEG |

**Installation on Pi:**
```bash
pip3 install opencv-python-headless
```
`opencv-python-headless` is preferred over `opencv-python` on headless Pi (no GUI dependencies). [ASSUMED: verify pip3 install works in Pi venv/system environment]

**Version verification:**
```bash
# On Pi
python3 -c "import cv2; print(cv2.__version__)"
# On elder-plops bridge
npm view rclnodejs version  # 1.9.0 as of 2026-04-08
```

---

## Architecture Patterns

### Recommended Project Structure

**Pi additions:**
```
src/chambers/fc-core/
├── fc_core/
│   ├── fc_sensors.py           # existing
│   ├── fc_controller.py        # existing
│   └── fc_camera.py            # NEW — camera capture + publish node
├── config/
│   └── fc_config.yaml          # add camera_* params
└── launch/
    └── fc.launch.py            # add fc_camera node
```

**Bridge additions:**
```
src/mission-control/bridge/
└── src/
    └── index.js                # add: camera subscription + MJPEG route + snapshot logic
```

**Frontend additions:**
```
src/mission-control/frontend/
├── plugins/
│   └── fruiting-chamber/
│       └── plugin.js           # add: camera object + custom view provider
└── index.html                  # already loads plugin.js (no change needed)
```

---

### Pattern 1: ROS2 CompressedImage publish from OpenCV capture

**What:** Timer-based ROS2 node captures frame via VideoCapture, encodes as JPEG, publishes as `CompressedImage`.

**When to use:** Any USB webcam (v4l2) where you want bandwidth-efficient frames on a ROS topic.

```python
# Source: ROS2 Jazzy sensor_msgs docs + fc_sensors.py pattern
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
import cv2

class FcCamera(Node):
    def __init__(self):
        super().__init__('fc_camera')
        self.declare_parameters('', [
            ('camera_simulation_mode', False),
            ('camera_device', 0),           # /dev/video0
            ('camera_width', 640),
            ('camera_height', 480),
            ('camera_fps', 1),              # 1-2 FPS for cellular bandwidth
            ('camera_jpeg_quality', 65),    # 60-70% per D-06
        ])

        self.pub = self.create_publisher(CompressedImage, 'fc/camera/compressed', 10)
        fps = self.get_parameter('camera_fps').value
        self.timer = self.create_timer(1.0 / fps, self.capture_and_publish)

        if not self.get_parameter('camera_simulation_mode').value:
            dev = self.get_parameter('camera_device').value
            self.cap = cv2.VideoCapture(dev)
            w = self.get_parameter('camera_width').value
            h = self.get_parameter('camera_height').value
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        else:
            self.cap = None

    def capture_and_publish(self):
        try:
            if self.cap is None:
                return  # simulation mode: skip publish
            ret, frame = self.cap.read()
            if not ret:
                self.get_logger().warn('Camera read failed')
                return
            quality = self.get_parameter('camera_jpeg_quality').value
            ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
            if not ok:
                return
            msg = CompressedImage()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.format = 'jpeg'
            msg.data = buf.tobytes()
            self.pub.publish(msg)
        except Exception as e:
            self.get_logger().error(f'Camera capture failed: {e}')

    def destroy_node(self):
        if self.cap:
            self.cap.release()
        super().destroy_node()
```

**CompressedImage.data field:** `uint8[]` — in Python this is `bytes`, which `buf.tobytes()` produces from a NumPy buffer. [VERIFIED: docs.ros.org/en/jazzy/p/sensor_msgs/msg/CompressedImage.html]

---

### Pattern 2: MJPEG endpoint in Express (no library)

**What:** Express route that keeps response open, writes multipart/x-mixed-replace frames as subscribers push JPEG buffers. Bridge receives CompressedImage from rclnodejs, extracts `.data` as a Buffer, pushes to active MJPEG connections.

**When to use:** Any scenario where browser needs a live image stream from a Node.js HTTP server.

```javascript
// Source: Total.js MJPEG blog post pattern (blog.totaljs.com/posts/786717001ow61b/)
// adapted for express + rclnodejs

const BOUNDARY = 'frameboundary';
const mjpegClients = new Set();

// Store latest frame for snapshot
let latestFrame = null;
let lastFrameTime = null;

// MJPEG stream endpoint
app.get('/camera/mjpeg', (req, res) => {
    res.writeHead(200, {
        'Content-Type': `multipart/x-mixed-replace; boundary="${BOUNDARY}"`,
        'Cache-Control': 'no-cache, no-store',
        'Connection': 'close',
        'Pragma': 'no-cache'
    });
    mjpegClients.add(res);
    req.on('close', () => mjpegClients.delete(res));
});

// Called for each incoming CompressedImage frame
function pushFrame(jpegBuffer) {
    latestFrame = jpegBuffer;
    lastFrameTime = Date.now();
    const header = [
        `--${BOUNDARY}`,
        'Content-Type: image/jpeg',
        `Content-Length: ${jpegBuffer.length}`,
        '',
        ''
    ].join('\r\n');

    mjpegClients.forEach(res => {
        try {
            res.write(header, 'ascii');
            res.write(jpegBuffer);
            res.write('\r\n', 'ascii');
        } catch (e) {
            mjpegClients.delete(res);
        }
    });
}

// Bridge subscription
node.createSubscription(
    'sensor_msgs/msg/CompressedImage',
    '/fc/camera/compressed',
    (msg) => {
        // msg.data is a Uint8Array in rclnodejs
        const buf = Buffer.from(msg.data);
        pushFrame(buf);
    }
);
```

**rclnodejs CompressedImage.data type:** rclnodejs returns `uint8[]` fields as `Uint8Array` in Node.js. `Buffer.from(msg.data)` converts it to a Node.js Buffer for writing. [ASSUMED: based on rclnodejs general uint8[] handling pattern — verify against rclnodejs source if needed]

---

### Pattern 3: Snapshot saving at configurable interval

**What:** Bridge maintains a timer that writes `latestFrame` to a date-organized directory on the local filesystem every N minutes.

```javascript
// Source: Node.js fs built-in pattern
const fs = require('fs');
const path = require('path');

const SNAPSHOT_DIR = process.env.SNAPSHOT_DIR || '/data/snapshots';
const SNAPSHOT_INTERVAL_MS = parseInt(process.env.SNAPSHOT_INTERVAL_MIN || '15') * 60 * 1000;
const CAMERA_ID = process.env.CAMERA_ID || 'fc1';

function saveSnapshot() {
    if (!latestFrame) return;
    const now = new Date();
    const dateDir = now.toISOString().slice(0, 10); // YYYY-MM-DD
    const dir = path.join(SNAPSHOT_DIR, CAMERA_ID, dateDir);
    fs.mkdirSync(dir, { recursive: true });
    const filename = `${now.toISOString().replace(/[:.]/g, '-')}.jpg`;
    const filepath = path.join(dir, filename);
    fs.writeFile(filepath, latestFrame, (err) => {
        if (err) console.error('[camera] snapshot write failed:', err.message);
        else console.log(`[camera] snapshot saved: ${filepath}`);
    });
}

setInterval(saveSnapshot, SNAPSHOT_INTERVAL_MS);
```

**Snapshot directory:** `/data/snapshots` should be a volume mount in docker-compose pointing to elder-plops local storage. Since bridge runs `network_mode: host`, this just needs to be an absolute path on the host. [VERIFIED: docker-compose.yml shows bridge has `network_mode: host`; volumes can be added]

---

### Pattern 4: OpenMCT custom view provider for camera

**What:** A view provider in the existing `plugin.js` that registers a custom `fruiting-chamber.camera` type and a view provider that renders an `<img>` element.

**When to use:** Any non-chart telemetry object in OpenMCT that needs custom HTML rendering.

```javascript
// Source: OpenMCT objectViews.addProvider pattern (vwoeltjen.github.io/openmct-api)
// Add to existing SENSORS array or as a separate CAMERA object:

var CAMERA = {
    identifier: { namespace: 'fruiting-chamber', key: 'fc.camera' },
    name: 'FC-1 Camera',
    mjpegUrl: 'http://elder-plops:8081/camera/mjpeg'  // or relative via env
};

// In install(openmct):
openmct.types.addType('fruiting-chamber.camera', {
    name: 'Chamber Camera',
    description: 'Live camera feed from the mushroom fruiting chamber',
    cssClass: 'icon-image',
    creatable: false
});

// Object provider returns camera object in root composition
// (add CAMERA.identifier to root composition array)

// View provider:
openmct.objectViews.addProvider({
    key: 'fruiting-chamber.camera-view',
    name: 'Camera Feed',
    canView: function(domainObject) {
        return domainObject.type === 'fruiting-chamber.camera';
    },
    view: function(domainObject, objectPath) {
        return {
            show: function(container) {
                container.innerHTML = '<img src="' + CAMERA.mjpegUrl + '"'
                    + ' style="max-width:100%;height:auto;display:block;margin:auto;"'
                    + ' alt="FC-1 Camera Feed" />';
            },
            destroy: function() {
                container.innerHTML = '';
            }
        };
    }
});
```

**CORS consideration:** The `<img>` MJPEG tag is loaded by the browser from `http://elder-plops:8081`. Since image tags don't trigger CORS preflight (they're simple GET requests), the existing CORS middleware in the bridge (which only sets the header for the OpenMCT origin) does not block this. [ASSUMED: verify that the browser's same-origin policy allows cross-origin `<img src>` — standard behavior is it does for images]

**mjpegUrl configuration:** The URL must be accessible from the browser (the client machine), not from inside Docker. Since OpenMCT and bridge are on elder-plops (bridge is `network_mode: host`), the browser accesses `http://elder-plops:8081/camera/mjpeg` directly. The `mjpegUrl` should be configurable (passed as a plugin option from `index.html`) rather than hardcoded. [ASSUMED: same pattern as `bridgeUrl` option in existing `FruitingChamberPlugin`]

---

### Anti-Patterns to Avoid

- **Don't use `ros-jazzy-v4l2-camera` apt package as the camera node:** D-08 requires a Python node in `fc_core`. The apt package is a standalone C++ node that won't integrate into the existing launch file and systemd setup cleanly.
- **Don't use cv_bridge:** Adds a dependency (and build complexity) for no gain when D-02 specifies compressed JPEG output. `cv2.imencode` is sufficient.
- **Don't use an MJPEG npm library:** `mjpeg-server` is stale (2022). The raw Express pattern is 15 lines and has no maintenance risk.
- **Don't use WebRTC or WebSocket for the video stream:** D-03 explicitly chose MJPEG for browser-native simplicity. An `<img>` tag consuming MJPEG requires zero client-side JavaScript.
- **Don't publish `sensor_msgs/Image` (raw, uncompressed):** Over the WireGuard cellular link, a 640x480 raw BGR8 frame is ~900KB. At 1 FPS that is ~72MB/hr. JPEG at 65% quality is ~15-30KB/frame — 40-60x smaller.
- **Don't store snapshots in a Docker volume:** Bridge is `network_mode: host`. Snapshots should write to the host filesystem directly via a bind mount to `/data/snapshots` — not a named volume, which doesn't persist cleanly outside Docker.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JPEG encode from frame | Custom YUV/RGB → JPEG encoder | `cv2.imencode('.jpg', ...)` | OpenCV handles all pixel format conversion, quality control, and JPEG standard compliance |
| V4L2 device control | Direct ioctl calls | `cv2.VideoCapture(dev)` with `cap.set(cv2.CAP_PROP_*)` | OpenCV abstracts V4L2 ioctl negotiation completely |
| Multipart HTTP framing | Custom HTTP chunked write | Inline Express pattern (15 lines) | Simple enough to inline; avoid stale MJPEG libraries |
| Date-organized directory path | Custom date formatter | `new Date().toISOString().slice(0, 10)` | Standard ISO 8601 date string, YYYY-MM-DD, already sorts lexicographically |

---

## Common Pitfalls

### Pitfall 1: Camera topic name `fc/camera/compressed` but existing topics use `fc1/`

**What goes wrong:** The bridge subscribes to `/fc1/humidity`, `/fc1/temperature` etc. (with `fc1/` prefix). The CONTEXT.md D-09 says `fc/camera/compressed`. If implemented literally, the camera topic is on a different namespace pattern from all other topics.
**Why it happens:** CONTEXT.md uses `fc/camera/compressed` but the sensors node publishes to `fc1/humidity`, `fc1/temperature`, etc.
**How to avoid:** Decide on one convention and apply it. Either use `fc1/camera/compressed` (matching existing sensors) or accept the discrepancy as intentional (future multi-chamber: `fc2/camera/compressed`). The planner should pick `fc1/camera/compressed` for consistency with the live system — confirm before coding.
**Warning signs:** Bridge subscribes but never receives frames; `ros2 topic list` shows mismatch.

### Pitfall 2: `cv2.VideoCapture` fails silently on Pi if camera not present

**What goes wrong:** `VideoCapture(0)` returns a capture object without raising an exception even if `/dev/video0` doesn't exist or is busy. `cap.isOpened()` returns False, but subsequent `cap.read()` also returns `(False, None)` silently.
**Why it happens:** OpenCV doesn't raise Python exceptions for device open failures.
**How to avoid:** In `__init__`, call `self.cap.isOpened()` immediately after `VideoCapture()` and log a warning if False. In `capture_and_publish`, if `not ret`, log the error and do not publish. Camera node must NOT crash fc-core.service on camera disconnection.
**Warning signs:** Node starts successfully but no messages on `fc/camera/compressed`; `ros2 topic hz fc1/camera/compressed` shows 0 Hz.

### Pitfall 3: MJPEG stream blocks Express event loop if client is slow

**What goes wrong:** `res.write()` to a slow/stale MJPEG client can back-pressure and block other routes.
**Why it happens:** Node.js HTTP writes are not fully async by default when the response buffer fills.
**How to avoid:** Track `mjpegClients` in a `Set`, catch errors on `res.write()`, and delete stale clients immediately on write failure. Also check `res.writable` before writing.
**Warning signs:** Bridge becomes unresponsive to `/health` checks or `/history/` requests when MJPEG viewer is open.

### Pitfall 4: Snapshot directory not created before first write

**What goes wrong:** `fs.writeFile()` fails if the date-organized directory doesn't exist yet (first snapshot of a new day).
**Why it happens:** `fs.writeFile` does not create parent directories.
**How to avoid:** Use `fs.mkdirSync(dir, { recursive: true })` before every snapshot write, or ensure it's called on bridge startup for today's date.
**Warning signs:** Bridge logs `ENOENT` on first snapshot of the day.

### Pitfall 5: OpenMCT `<img>` MJPEG URL hardcoded to `localhost`

**What goes wrong:** If `mjpegUrl` is hardcoded to `http://localhost:8081/camera/mjpeg` in `plugin.js` or `index.html`, it works only when the browser is on the same machine as the bridge. Over WireGuard/LAN, the browser is on a different host.
**Why it happens:** Developers test locally and forget that `localhost` in the browser context means the browser's machine, not the bridge server.
**How to avoid:** Pass the full bridge hostname/IP as a plugin option in `index.html` (same pattern as `bridgeUrl` and `historyUrl` in `FruitingChamberPlugin`). Default to relative URL or configurable env var.
**Warning signs:** Camera view shows broken image; browser console shows `net::ERR_CONNECTION_REFUSED` on `localhost:8081/camera/mjpeg`.

### Pitfall 6: `opencv-python` vs `opencv-python-headless` on Pi

**What goes wrong:** `opencv-python` pulls in GUI libraries (`libgtk-3`, Qt) that aren't needed on a headless Pi and may conflict with system packages.
**Why it happens:** Default opencv package includes display capabilities.
**How to avoid:** Install `opencv-python-headless` instead of `opencv-python`. Both provide identical `cv2` API; headless just omits GUI dependencies.
**Warning signs:** Pip install errors about missing display libraries; excessive disk usage on Pi.

### Pitfall 7: rclnodejs `msg.data` for CompressedImage is Uint8Array, not Buffer

**What goes wrong:** `res.write(msg.data)` may not work as expected because `Uint8Array` is not a Node.js `Buffer`.
**Why it happens:** rclnodejs returns ROS `uint8[]` as JavaScript `Uint8Array`. Node.js `http.ServerResponse.write()` accepts `Buffer`, `string`, or `Uint8Array` — but passing `Uint8Array` directly may produce unexpected encoding on older Node versions.
**How to avoid:** Always convert: `const buf = Buffer.from(msg.data);` before writing or using `.length`.
**Warning signs:** MJPEG stream received by browser but displays garbled images; `Content-Length` mismatch.

---

## Code Examples

### fc_camera.py — Full minimum viable implementation

```python
# Source: Pattern derived from fc_sensors.py (existing) + sensor_msgs CompressedImage docs
#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage

class FcCamera(Node):
    def __init__(self):
        super().__init__('fc_camera')
        self.declare_parameters('', [
            ('camera_simulation_mode', False),
            ('camera_device', 0),
            ('camera_width', 640),
            ('camera_height', 480),
            ('camera_fps', 1),
            ('camera_jpeg_quality', 65),
        ])

        self.pub = self.create_publisher(CompressedImage, 'fc1/camera/compressed', 10)
        fps = self.get_parameter('camera_fps').value
        self.timer = self.create_timer(1.0 / fps, self.capture_and_publish)

        self.cap = None
        if not self.get_parameter('camera_simulation_mode').value:
            import cv2
            dev = self.get_parameter('camera_device').value
            self.cap = cv2.VideoCapture(dev)
            if not self.cap.isOpened():
                self.get_logger().warn(f'Camera /dev/video{dev} not available — node will idle')
            else:
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,
                             self.get_parameter('camera_width').value)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT,
                             self.get_parameter('camera_height').value)
                self.get_logger().info(f'Camera opened at /dev/video{dev}')
        else:
            self.get_logger().info('Camera node in simulation mode — no frames published')

    def capture_and_publish(self):
        if self.cap is None or not self.cap.isOpened():
            return
        try:
            import cv2
            ret, frame = self.cap.read()
            if not ret:
                self.get_logger().warn('Camera frame read failed')
                return
            quality = self.get_parameter('camera_jpeg_quality').value
            ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
            if not ok:
                self.get_logger().warn('JPEG encode failed')
                return
            msg = CompressedImage()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.format = 'jpeg'
            msg.data = buf.tobytes()
            self.pub.publish(msg)
        except Exception as e:
            self.get_logger().error(f'Camera capture error: {e}')

    def destroy_node(self):
        if self.cap:
            self.cap.release()
        super().destroy_node()

def main(args=None):
    rclpy.init(args=args)
    node = FcCamera()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
```

### fc_config.yaml additions

```yaml
# Camera parameters (add to existing fc_config.yaml under /**:ros__parameters:)
camera_simulation_mode: false   # false = use real USB webcam
camera_device: 0                # /dev/video0
camera_width: 640               # pixels
camera_height: 480              # pixels
camera_fps: 1                   # frames per second (cellular bandwidth constraint)
camera_jpeg_quality: 65         # 0-100, 60-70 per D-06
```

### launch/fc.launch.py addition

```python
# Add alongside existing Node() entries in generate_launch_description()
Node(
    package='fc_core',
    executable='fc_camera',
    name='fc_camera',
    parameters=[LaunchConfiguration('config_file')],
    output='screen'
),
```

### setup.py entry_points addition

```python
'fc_camera = fc_core.fc_camera:main',
```

### bridge index.js snapshot volume in docker-compose.yml

```yaml
# In the bridge service, add snapshot volume:
volumes:
  - ./mission-control/bridge/cyclonedds.xml:/opt/bridge/cyclonedds.xml:ro
  - /data/snapshots:/data/snapshots  # elder-plops host path
environment:
  - SNAPSHOT_DIR=/data/snapshots
  - SNAPSHOT_INTERVAL_MIN=15
  - CAMERA_ID=fc1
```

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| rosbridge WebSocket for images | Direct rclnodejs CompressedImage subscription + MJPEG re-serve | No base64 encoding overhead; JPEG bytes transmitted as-is |
| WebRTC for browser video | MJPEG via `<img>` tag | Browser-native, zero JS, lower latency for 1-2 FPS |
| cv_bridge for format conversion | `cv2.imencode` directly to JPEG | Eliminates ROS↔OpenCV image format conversion step |

**Topic naming note:** Existing topics use `fc1/` prefix (`/fc1/humidity`, `/fc1/temperature`). CONTEXT.md D-09 says `fc/camera/compressed`. For consistency with the live system, the implementation should use `fc1/camera/compressed`. This is a minor discrepancy between CONTEXT.md notation and the actual topic namespace — the planner should standardize on `fc1/` prefix to match all other topics.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `opencv-python-headless` is installable via pip3 on Pi Ubuntu 24.04 without conflicts | Standard Stack | Camera node would fail to start; workaround: `apt install python3-opencv` |
| A2 | rclnodejs returns `CompressedImage.data` as `Uint8Array` | Pattern 2 + Pitfall 7 | Frame write to MJPEG clients could be garbled; fix: test `typeof msg.data` |
| A3 | OpenMCT `<img>` tag consuming cross-origin MJPEG from bridge doesn't trigger CORS block | Pattern 4 | Camera view shows broken image; fix: add `Access-Control-Allow-Origin: *` to MJPEG route specifically |
| A4 | `cv2.VideoCapture` is the correct v4l2 interface on Pi Ubuntu 24.04 (vs libcamera stack) | Pattern 1 | USB webcam not opened; Pi Camera Module 3 would need `libcamera` API instead; USB webcam is unaffected by this |
| A5 | Snapshot path `/data/snapshots` on bridge container maps to host filesystem via bind mount | Pattern 3 | Snapshots written to container's ephemeral layer, lost on restart |
| A6 | `camera_fps: 1` + `640x480` + JPEG quality 65 produces frames of approximately 15-30 KB each | Bandwidth estimation | Actual frame size depends on scene complexity; verify with `wc -c` on captured JPEG |

---

## Open Questions

1. **Topic prefix: `fc/camera/compressed` vs `fc1/camera/compressed`**
   - What we know: All existing topics are `/fc1/humidity`, `/fc1/temperature`, `/fc1/co2`, `/fc1/actuators/humidifier`. CONTEXT.md D-09 says `fc/camera/compressed`.
   - What's unclear: Is `fc/` intentional (future-proofing for multi-chamber where camera might be shared) or a typo in CONTEXT.md?
   - Recommendation: Use `fc1/camera/compressed` to match all existing topics. This is consistent with the current single-chamber deployment and avoids a namespace anomaly.

2. **opencv-python availability on Pi**
   - What we know: Pi is Ubuntu 24.04, Python 3.12+. `opencv-python-headless` is available via pip. `python3-opencv` is available via apt.
   - What's unclear: Which install method is correct for the ROS2 venv/system Python context. fc_sensors.py imports adafruit libs via system Python (not a venv).
   - Recommendation: Use `apt install python3-opencv` for system Python consistency; check apt version satisfies cv2 >= 4.x.

3. **Snapshot volume persistence for bridge container**
   - What we know: Bridge runs `network_mode: host`. Docker named volumes don't persist to a predictable host path.
   - What's unclear: Is `/data/snapshots` a pre-existing directory on elder-plops or should it be created by the plan?
   - Recommendation: Plan should include a Wave 0 task to `mkdir -p /data/snapshots/fc1` on elder-plops and add the bind mount to docker-compose.yml.

4. **CORS for MJPEG endpoint**
   - What we know: The bridge CORS middleware restricts headers to `CORS_ORIGIN` (defaults to `http://localhost:8080`). Image tags don't trigger CORS for display, but if the plugin ever needs to fetch the image as a blob (e.g., for snapshots page), it would.
   - What's unclear: Whether future snapshot history view needs fetch() access.
   - Recommendation: For Phase 8 scope (just `<img>` tag), no CORS change needed for the MJPEG endpoint. Document for future.

---

## Environment Availability

| Dependency | Required By | Available | Notes | Fallback |
|------------|------------|-----------|-------|---------|
| USB webcam `/dev/video0` | fc_camera.py | Unknown — not verified | Pi fc1 has no webcam connected yet; needs physical setup | `camera_simulation_mode: true` skips capture |
| `opencv-python-headless` | fc_camera.py | Unknown — not installed yet | Available via pip or apt on Ubuntu 24.04 | No fallback; required for capture |
| `v4l-utils` (`v4l2-ctl`) | Camera diagnostics | Likely available via apt | Not confirmed on Pi | Not required for operation |
| `/data/snapshots` dir | Bridge snapshot storage | Unknown | elder-plops filesystem; needs creation | `fs.mkdirSync` with `recursive: true` |
| rclnodejs 1.9.0 | Bridge CompressedImage sub | Available | npm registry 2026-04-07 | Already installed in bridge |
| Node.js express | MJPEG route | Available | Already in bridge dependencies | Already installed |

**Missing dependencies with no fallback:**
- USB webcam hardware must be physically connected to fc1 Pi before camera node testing. Camera node has `camera_simulation_mode` to start without a camera, but live feed requires hardware.
- `opencv-python-headless` or `python3-opencv` must be installed on Pi before `fc_camera.py` node can start in real mode.

**Missing dependencies with fallback:**
- Snapshot directory: created by plan Wave 0 task.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing in fc_core) |
| Config file | None — uses `colcon test` |
| Quick run command | `pytest src/chambers/fc-core/fc_core/test/ -x -q` |
| Full suite command | `colcon test --packages-select fc_core && colcon test-result` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| N/A | Camera node starts without error in simulation mode | unit | `pytest src/chambers/fc-core/fc_core/test/test_camera.py::test_camera_sim_mode -x` | No — Wave 0 |
| N/A | Camera node handles VideoCapture failure gracefully (no exception) | unit | `pytest src/chambers/fc-core/fc_core/test/test_camera.py::test_camera_unavailable -x` | No — Wave 0 |
| N/A | JPEG encode produces valid bytes | unit | `pytest src/chambers/fc-core/fc_core/test/test_camera.py::test_jpeg_encode -x` | No — Wave 0 |
| N/A | MJPEG endpoint responds with correct Content-Type | integration/smoke | Manual or curl: `curl -I http://localhost:8081/camera/mjpeg` | No — manual |
| N/A | Snapshot saved to correct date directory | unit | `pytest` (bridge — not currently tested) | No — manual verify |

### Wave 0 Gaps
- [ ] `src/chambers/fc-core/fc_core/test/test_camera.py` — unit tests for fc_camera node (simulation mode, graceful failure)
- [ ] Camera node entry point registered in `setup.py`
- [ ] `opencv-python-headless` installed on Pi: `ssh fc1 'sudo apt install -y python3-opencv'`

*(Bridge and OpenMCT plugin changes have no automated tests in current project — verify manually)*

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Camera endpoint is local/VPN-only; no public exposure |
| V3 Session Management | No | MJPEG is stateless |
| V4 Access Control | Low | MJPEG route should not be publicly exposed; bridge is on VPN/LAN only |
| V5 Input Validation | No | No user input to camera endpoint |
| V6 Cryptography | No | Frames are not sensitive data |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| MJPEG endpoint exposed to internet | Information Disclosure | Bridge is on elder-plops LAN/VPN; no public port forwarding |
| Snapshot dir path traversal | Tampering | `CAMERA_ID` is env var controlled by ops, not user input; no path from HTTP request |
| Resource exhaustion from many MJPEG clients | Denial of Service | Track `mjpegClients` set size; optionally cap at N connections; low risk in home LAN |

No new security surface is introduced beyond the existing bridge port 8081, which is already accessible only via the WireGuard VPN topology documented in Phase 6.

---

## Sources

### Primary (HIGH confidence)
- [VERIFIED: docs.ros.org/en/jazzy/p/v4l2_camera/] — v4l2_camera package parameters, topic names, image_transport plugin requirement
- [VERIFIED: docs.ros.org/en/jazzy/p/sensor_msgs/msg/CompressedImage.html] — CompressedImage message fields (header, format, data)
- [VERIFIED: npm registry 2026-04-08] — rclnodejs 1.9.0 (2026-04-07), mjpeg-server 0.3.1 (2022-06-19)
- [VERIFIED: /mnt/slime-kingdom/opt/mushy/src/mission-control/bridge/src/index.js] — bridge uses express, rclnodejs, port 8081, network_mode: host
- [VERIFIED: /mnt/slime-kingdom/opt/mushy/src/chambers/fc-core/fc_core/fc_sensors.py] — ROS2 Python node pattern for camera to follow
- [VERIFIED: /mnt/slime-kingdom/opt/mushy/src/docker-compose.yml] — bridge network_mode: host; timescale on frontend-net
- [VERIFIED: /mnt/slime-kingdom/opt/mushy/src/mission-control/frontend/plugins/fruiting-chamber/plugin.js] — existing plugin pattern; objectViews is not yet used

### Secondary (MEDIUM confidence)
- [CITED: blog.totaljs.com/posts/786717001ow61b/] — MJPEG multipart/x-mixed-replace Node.js pattern with exact write sequence
- [CITED: nasa.github.io/openmct/plugins-documentation + github.com/nasa/openmct discussions #3873] — OpenMCT has no built-in video plugin; Web Page Plugin (iframe) or custom objectViews.addProvider are the approaches
- [CITED: vwoeltjen.github.io/openmct-api] — objectViews.addProvider with canView + view pattern (older but consistent with current codebase usage)

### Tertiary (LOW confidence)
- [ASSUMED] rclnodejs returns uint8[] as Uint8Array — needs test verification
- [ASSUMED] opencv-python-headless install path on Pi system Python (apt vs pip)

---

## Metadata

**Confidence breakdown:**
- Standard stack (camera node): HIGH — fc_sensors.py pattern is verified, CompressedImage is standard
- Standard stack (bridge MJPEG): HIGH — raw Express pattern verified, no library needed
- Standard stack (OpenMCT view): MEDIUM — API pattern found but objectViews.addProvider specifics are lightly documented
- Architecture: HIGH — all three domains are well-understood given existing codebase
- Pitfalls: HIGH — all derived from verified code inspection and known OpenCV/Node.js behaviors
- OpenMCT view internals: MEDIUM — API is stable but official docs are sparse

**Research date:** 2026-04-08
**Valid until:** 2026-07-08 (stable: ROS2 Jazzy LTS, Express 5.x stable, OpenMCT core API stable)
