---
phase: 10-bridge-qos-mjpeg-delivery
reviewed: 2026-04-12T00:00:00Z
depth: standard
files_reviewed: 3
files_reviewed_list:
  - scripts/pi-deploy/cyclonedds-tailscale.xml
  - scripts/pi-deploy/cyclonedds.xml
  - src/mission-control/bridge/src/index.js
findings:
  critical: 1
  warning: 3
  info: 3
  total: 7
status: issues_found
---

# Phase 10: Code Review Report

**Reviewed:** 2026-04-12
**Depth:** standard
**Files Reviewed:** 3
**Status:** issues_found

## Summary

Three files reviewed: two CycloneDDS XML configs and the Node.js bridge. The bridge code is
generally well-structured with good security posture (parameterized queries, CORS allowlist,
topic allowlist). One critical bug in snapshot timer initialization can cause the timer to fire
at ~1ms intervals if `SNAPSHOT_INTERVAL_MIN` is set to an empty string. Three warnings cover
an unhandled HTTP response stream error event, a misleading/stale header comment in one XML
config, and a `mkdirSync` call on the hot event-loop path. Three info items address cosmetic
issues.

---

## Critical Issues

### CR-01: `NaN` interval from empty env var causes snapshot timer to fire at ~1ms rate

**File:** `src/mission-control/bridge/src/index.js:35`

**Issue:** `parseInt(process.env.SNAPSHOT_INTERVAL_MIN || '15', 10)` only falls back to `'15'`
when the env var is **absent** (falsy). If `SNAPSHOT_INTERVAL_MIN` is set to an empty string
`""` in the environment or `.env` file (a common misconfiguration), the `||` short-circuit does
not trigger, `parseInt('', 10)` returns `NaN`, and `SNAPSHOT_INTERVAL_MS` becomes `NaN`.
`setInterval(saveSnapshot, NaN)` in Node.js treats a `NaN` delay as `0` / immediate — the
callback fires on every event loop tick, thrashing the filesystem with `mkdirSync` +
`fs.writeFile` calls until the process is killed or runs out of disk space.

**Fix:**
```js
const _rawIntervalMin = parseInt(process.env.SNAPSHOT_INTERVAL_MIN || '15', 10);
const SNAPSHOT_INTERVAL_MS = (isNaN(_rawIntervalMin) || _rawIntervalMin <= 0 ? 15 : _rawIntervalMin) * 60 * 1000;
```
Or equivalently add a guard before `setInterval`:
```js
if (isNaN(SNAPSHOT_INTERVAL_MS) || SNAPSHOT_INTERVAL_MS <= 0) {
    console.error('[camera] Invalid SNAPSHOT_INTERVAL_MIN — defaulting to 15 minutes');
    // reassign or use literal
}
```

---

## Warnings

### WR-01: HTTP response `error` event not handled in `pushFrame` — potential process crash

**File:** `src/mission-control/bridge/src/index.js:54-60`

**Issue:** When a client disconnects mid-stream, Node.js HTTP response objects emit an `'error'`
event on the stream rather than (or in addition to) making `res.write()` throw synchronously.
The `try/catch` around `res.write()` catches synchronous throws but does **not** catch
asynchronous `'error'` events on the stream. An unhandled `'error'` event on any EventEmitter
in Node.js causes an uncaught exception and crashes the process. Under normal browser
disconnects this may or may not throw synchronously depending on the Node.js version and
buffering state — it is not guaranteed to be caught.

**Fix:** Attach a no-op (or logging) error handler when each MJPEG client is registered:
```js
app.get('/camera/mjpeg', (req, res) => {
    res.writeHead(200, { ... });
    res.on('error', () => {
        mjpegClients.delete(res);
        console.log('[camera] MJPEG client stream error, removed');
    });
    mjpegClients.add(res);
    ...
});
```
This ensures errors are handled regardless of whether `res.write()` throws or emits.

---

### WR-02: `cyclonedds.xml` deploy-path comment says `cyclonedds-tailscale.xml` — misleading and diverging configs

**File:** `scripts/pi-deploy/cyclonedds.xml:3`

**Issue:** The comment on line 3 reads:
```xml
<!-- Deployed to: /etc/cyclonedds-tailscale.xml on Pi (CYCLONEDDS_URI in fc-core.service) -->
```
This is identical to the comment in `cyclonedds-tailscale.xml`, implying both files deploy to
the same path. If `cyclonedds.xml` is a general/fallback config and `cyclonedds-tailscale.xml`
is the production config, their deploy paths must differ — or one file is dead/redundant. In
addition, `cyclonedds.xml` contains `<LeaseDuration>5 s</LeaseDuration>` (line 19) that is
absent from `cyclonedds-tailscale.xml`, meaning the two files that appear to serve the same
role have silently diverged in behavior: the lease duration on tailscale.xml falls back to the
CycloneDDS default (10 s), while cyclonedds.xml shortens it to 5 s. If only one file is
actually deployed, the 5 s lease is either accidentally missing or accidentally present.

**Fix:** Clarify the intended purpose of each file:
- If `cyclonedds.xml` is the production-deployed file, update its comment to reflect the
  correct target path (e.g., `/etc/cyclonedds.xml`) and decide whether the 5 s lease duration
  is intentional.
- If `cyclonedds-tailscale.xml` is the deployed file and `cyclonedds.xml` is a draft or local
  fallback, add a comment to that effect and ensure the `<LeaseDuration>` is present in the
  file that actually gets deployed.
- If they should be identical, merge them into one file and use a symlink or deploy script to
  put them in place.

---

### WR-03: `fs.mkdirSync` called synchronously on the timer callback — blocks event loop

**File:** `src/mission-control/bridge/src/index.js:69`

**Issue:** `saveSnapshot()` is invoked on a `setInterval` callback and calls `fs.mkdirSync(dir,
{ recursive: true })` synchronously before the async `fs.writeFile`. On an NFS mount, a slow
SD card, or during filesystem pressure, this synchronous call blocks the entire Node.js event
loop — stalling WebSocket broadcasts and HTTP responses for all connected clients for the
duration of the mkdir. Under normal conditions on a local filesystem this is fast, but it is
a latent reliability issue on embedded hardware (Raspberry Pi + SD card).

**Fix:** Use `fs.mkdir` (async) with a callback, or hoist the directory creation to startup
(since the date-based subdirectory only changes at midnight):
```js
function saveSnapshot() {
    if (!latestFrame) return;
    const frame = latestFrame; // capture reference
    const now = new Date();
    const dateDir = now.toISOString().slice(0, 10);
    const dir = path.join(SNAPSHOT_DIR, CAMERA_ID, dateDir);
    fs.mkdir(dir, { recursive: true }, (mkErr) => {
        if (mkErr && mkErr.code !== 'EEXIST') {
            console.error('[camera] mkdir failed:', mkErr.message);
            return;
        }
        const filename = `${now.toISOString().replace(/[:.]/g, '-')}.jpg`;
        fs.writeFile(path.join(dir, filename), frame, (err) => {
            if (err) console.error('[camera] snapshot write failed:', err.message);
            else console.log(`[camera] snapshot saved: ${filename} (${frame.length} bytes)`);
        });
    });
}
```
Note the captured `frame` local reference also fixes the stale-closure log issue (IN-03).

---

## Info

### IN-01: Camera stream has no authentication — any host that reaches port 8081 gets the feed

**File:** `src/mission-control/bridge/src/index.js:202`

**Issue:** `/camera/mjpeg` and `/camera/snapshot` endpoints serve live camera frames with no
token or session check. The WebSocket and history endpoints are similarly unauthenticated. In
the current deployment this is mitigated by Tailscale network access control and Docker
internal networking, so it is not an immediately exploitable vulnerability. However, if the
bridge port is ever exposed directly (e.g., for testing), anyone on the network gets the
camera stream.

**Fix:** No immediate code change required given the Tailscale trust boundary. Document the
assumption explicitly with a comment. If external exposure is ever needed, add a
`BRIDGE_TOKEN` env-var check middleware.

---

### IN-02: `CompressedImage` data not validated as JPEG before pushing to clients

**File:** `src/mission-control/bridge/src/index.js:337-340`

**Issue:** The camera subscription receives `sensor_msgs/msg/CompressedImage` and converts
`msg.data` directly to a Buffer and pushes it to all MJPEG clients and the snapshot file.
The `format` field of `CompressedImage` (e.g., `"jpeg"`) is never checked. If the camera
node sends a PNG or other format, clients receive a malformed MJPEG stream without a clear
error message.

**Fix:** Add a format guard:
```js
node.createSubscription(
    'sensor_msgs/msg/CompressedImage',
    '/fc1/camera/compressed',
    (msg) => {
        if (!msg.format || !msg.format.includes('jpeg')) {
            console.warn(`[camera] Unexpected image format: ${msg.format} — skipping`);
            return;
        }
        const buf = Buffer.from(msg.data);
        pushFrame(buf);
    }
);
```

---

### IN-03: Snapshot log prints current `latestFrame.length`, not the length of the frame that was written

**File:** `src/mission-control/bridge/src/index.js:74`

**Issue:** The `fs.writeFile` callback closure captures `latestFrame` by reference (not by
value). By the time the callback fires, `latestFrame` may have been replaced by a newer frame.
The log line `${latestFrame.length} bytes` then reports the size of the most-recent frame, not
the frame actually persisted to disk. This is a cosmetic/diagnostic accuracy issue only.

**Fix:** Capture the frame reference before the async call (also see WR-03 fix above):
```js
function saveSnapshot() {
    if (!latestFrame) return;
    const frame = latestFrame; // snapshot the reference
    ...
    fs.writeFile(filepath, frame, (err) => {
        if (err) console.error('[camera] snapshot write failed:', err.message);
        else console.log(`[camera] snapshot saved: ${filepath} (${frame.length} bytes)`);
    });
}
```

---

_Reviewed: 2026-04-12_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
