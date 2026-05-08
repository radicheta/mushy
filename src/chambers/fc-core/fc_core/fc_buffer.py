#!/usr/bin/env python3
"""fc_buffer — local telemetry ring buffer + HTTP replay endpoint (Phase 999.1).

On-Pi half of the edge buffer:
  - Subscribes to every topic in `buffered_topics.yaml`
  - Writes each message to /var/lib/fc-core/buffer.sqlite (WAL) keyed (topic, time_ns)
  - Evicts rows older than `retention_seconds` every `prune_interval_seconds`
  - Serves GET /telemetry/since?ts=<ns>&limit=<N> as application/x-ndjson

Bind address is parameter-driven (default: fc1's tailscale0 address); the bridge polls
this endpoint on reconnect to backfill anything it missed.

Module-level helpers (`init_schema`, `_write_row`, `_prune`, `_serve_since`,
`_load_topics`, `_extract`) are pure and unit-testable WITHOUT rclpy. The FcBuffer
rclpy.Node subclass is constructed only inside main() / when ROS deps are available.
"""
import json
import os
import re
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import yaml


# --- Module constants --------------------------------------------------------

CAMERA_PATTERN = re.compile(r'/fc1/camera')
HTTP_LIMIT_CAP = 50000  # absolute ceiling on /telemetry/since rows per request

DEFAULT_DB_PATH = '/var/lib/fc-core/buffer.sqlite'
DEFAULT_HTTP_BIND = '172.16.10.5'  # fc1 wg0 (D-09); never the wildcard interface — was tailscale0 100.96.239.75 until 2026-05-03
DEFAULT_HTTP_PORT = 8765
DEFAULT_RETENTION_SECONDS = 86400
DEFAULT_PRUNE_INTERVAL_SECONDS = 60.0

# Phase 28 plan 28-06 — Layer 2 transport (28-01-SPIKE.md §C, D-B1).
# Bridge POSTs runtime_overrides.yaml here; fc_buffer owns the atomic write.
# T-28-20 path-traversal mitigation: writes are restricted to OVERLAY_DIR,
# `.bak`/`.tmp` suffix submissions are rejected (those are bookkeeping suffixes
# fc_buffer derives itself), and a realpath() check defeats symlink-escape.
OVERLAY_DIR = '/var/lib/fc-core/'
OVERLAY_MAX_BYTES = 64 * 1024  # 64 KiB cap on persisted overlay payload
PERSIST_REQUEST_MAX_BYTES = 128 * 1024  # request body cap (allows headroom)


def _is_safe_overlay_path(p):
    """Return True iff `p` is a writeable overlay path inside OVERLAY_DIR.

    T-28-20: rejects `..` traversal, symlink escape (via realpath),
    and `.bak`/`.tmp` suffixes (caller must not own those — fc_buffer derives them).
    """
    if not isinstance(p, str) or not p:
        return False
    if p.endswith('.bak') or p.endswith('.tmp'):
        return False
    if not p.startswith(OVERLAY_DIR):
        return False
    # realpath collapses `..` and follows symlinks; the resolved path must still
    # live under OVERLAY_DIR. We resolve the parent directory rather than the
    # file itself (which may not exist yet on first persist).
    parent = os.path.dirname(p) or '/'
    try:
        real_parent = os.path.realpath(parent)
    except OSError:
        return False
    # Append a trailing slash to OVERLAY_DIR for prefix safety
    # (`/var/lib/fc-core-evil/` must NOT match `/var/lib/fc-core`).
    overlay_dir_real = os.path.realpath(OVERLAY_DIR).rstrip('/') + '/'
    return (real_parent.rstrip('/') + '/').startswith(overlay_dir_real)


def _atomic_write_overlay(path, content):
    """Atomically write `content` to `path` with one-generation .bak retention.

    Sequence (T-28-21): write `path+'.tmp'`, fsync, rename existing path → `.bak`,
    rename `.tmp` → path. Either the previous version or the new version is on
    disk at all times. ROS2 launch fails hard on missing/bad yaml — fall-open
    is impossible by design — and the .bak enables one-step manual revert.
    """
    if not _is_safe_overlay_path(path):
        raise ValueError(f'unsafe overlay path: {path!r}')
    if not isinstance(content, str):
        raise TypeError('content must be str')
    if len(content.encode('utf-8')) > OVERLAY_MAX_BYTES:
        raise ValueError(f'overlay exceeds {OVERLAY_MAX_BYTES} bytes')

    tmp = path + '.tmp'
    bak = path + '.bak'
    # Ensure parent directory exists (writer side owns this — bridge can't mkdir).
    parent = os.path.dirname(path) or '/'
    os.makedirs(parent, exist_ok=True)

    # Write tmp + fsync.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, content.encode('utf-8'))
        os.fsync(fd)
    finally:
        os.close(fd)

    # Rotate prior version → .bak (if it exists).
    if os.path.exists(path):
        os.replace(path, bak)
    # Atomic rename tmp → path.
    os.replace(tmp, path)


def _read_overlay(path):
    """Return overlay file contents or None if missing. Path is allowlist-checked."""
    if not _is_safe_overlay_path(path):
        raise ValueError(f'unsafe overlay path: {path!r}')
    try:
        with open(path, encoding='utf-8') as fh:
            return fh.read()
    except FileNotFoundError:
        return None


# --- Pure helpers (rclpy-free, testable in isolation) ------------------------

def init_schema(db):
    """Apply WAL pragma and create the telemetry_buffer table if missing."""
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=NORMAL')
    db.execute(
        '''CREATE TABLE IF NOT EXISTS telemetry_buffer (
            topic TEXT NOT NULL,
            time_ns INTEGER NOT NULL,
            value REAL,
            extra TEXT,
            PRIMARY KEY (topic, time_ns)
        )'''
    )
    db.commit()


def _write_row(db, topic, time_ns, value, extra):
    """Append a row; duplicates on (topic, time_ns) are silently ignored."""
    db.execute(
        'INSERT OR IGNORE INTO telemetry_buffer (topic, time_ns, value, extra) '
        'VALUES (?,?,?,?)',
        (
            topic,
            int(time_ns),
            float(value) if value is not None else None,
            extra,
        ),
    )
    db.commit()


def _prune(db, retention_seconds, now_ns):
    """Delete rows whose time_ns falls outside the retention window."""
    cutoff_ns = int(now_ns) - int(retention_seconds) * 1_000_000_000
    db.execute('DELETE FROM telemetry_buffer WHERE time_ns < ?', (cutoff_ns,))
    db.commit()


def _serve_since(db_path, since_ns, limit=10000):
    """Read rows newer than `since_ns`, oldest first, capped at HTTP_LIMIT_CAP.

    Raises ValueError on bad `since_ns` (caller catches and returns HTTP 400).
    Uses a separate read-only connection so writers are not blocked.
    """
    since_ns = int(since_ns)  # raises ValueError → caller maps to 400
    limit = min(int(limit), HTTP_LIMIT_CAP)
    if limit < 0:
        raise ValueError('limit must be non-negative')
    ro = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    try:
        rows = list(
            ro.execute(
                'SELECT topic, time_ns, value, extra FROM telemetry_buffer '
                'WHERE time_ns > ? ORDER BY time_ns LIMIT ?',
                (since_ns, limit),
            )
        )
    finally:
        ro.close()
    return [
        {'topic': r[0], 'time_ns': r[1], 'value': r[2], 'extra': r[3]}
        for r in rows
    ]


def _load_topics(yaml_path):
    """Parse buffered_topics.yaml and refuse any camera entries (D-11 hard exclude)."""
    with open(yaml_path) as fh:
        data = yaml.safe_load(fh)
    topics = data.get('buffered', []) if data else []
    for t in topics:
        if CAMERA_PATTERN.search(t['ros_topic']):
            raise ValueError(
                f"camera topic forbidden in buffer: {t['ros_topic']}"
            )
    return topics


def _extract(bridge_topic, msg):
    """Return (time_ns, value_float, extra_json_or_none) for any supported msg type.

    Discriminates by attribute presence so tests can use SimpleNamespace fakes
    without importing real ROS message classes.
    """
    if hasattr(msg, 'header') and getattr(msg.header.stamp, 'sec', 0):
        ts_ns = (
            int(msg.header.stamp.sec) * 1_000_000_000
            + int(msg.header.stamp.nanosec)
        )
    else:
        ts_ns = time.time_ns()

    if hasattr(msg, 'relative_humidity'):
        frame_id = getattr(msg.header, 'frame_id', '') if hasattr(msg, 'header') else ''
        extra = json.dumps({'frame_id': frame_id}) if frame_id else None
        return ts_ns, float(msg.relative_humidity) * 100.0, extra
    if hasattr(msg, 'temperature'):
        frame_id = getattr(msg.header, 'frame_id', '') if hasattr(msg, 'header') else ''
        extra = json.dumps({'frame_id': frame_id}) if frame_id else None
        return ts_ns, float(msg.temperature), extra
    if hasattr(msg, 'data'):
        if isinstance(msg.data, bool):
            return ts_ns, 1.0 if msg.data else 0.0, None
        return ts_ns, float(msg.data), None
    raise TypeError(f'unhandled msg shape for {bridge_topic}')


# --- HTTP handler ------------------------------------------------------------

def _make_http_handler(db_path, logger=None):
    """Build a BaseHTTPRequestHandler subclass closed over the db path."""

    class TelemetryHandler(BaseHTTPRequestHandler):
        # Suppress the noisy default request log; route to ROS logger if provided.
        def log_message(self, fmt, *args):
            if logger is not None:
                logger.debug('http: ' + (fmt % args))

        def _send_json(self, code, payload):
            body = json.dumps(payload).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
            parsed = urlparse(self.path)
            if parsed.path == '/telemetry/since':
                qs = parse_qs(parsed.query)
                ts_raw = (qs.get('ts') or ['0'])[0]
                limit_raw = (qs.get('limit') or ['10000'])[0]
                try:
                    rows = _serve_since(db_path, ts_raw, limit_raw)
                except ValueError as e:
                    self.send_error(400, f'Bad Request: {e}')
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'application/x-ndjson')
                self.end_headers()
                for row in rows:
                    line = json.dumps(row, separators=(',', ':')) + '\n'
                    self.wfile.write(line.encode('utf-8'))
                return

            if parsed.path == '/control/overlay':
                # Phase 28 plan 28-06 (D-B1): bridge reads existing overlay.
                qs = parse_qs(parsed.query)
                p = (qs.get('path') or [''])[0]
                if not _is_safe_overlay_path(p):
                    self._send_json(400, {'error': f'unsafe overlay path: {p!r}'})
                    return
                try:
                    content = _read_overlay(p)
                except ValueError as e:
                    self._send_json(400, {'error': str(e)})
                    return
                if content is None:
                    self._send_json(404, {'error': 'overlay not found'})
                    return
                body = content.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/yaml; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            self.send_error(404, 'Not Found')

        def do_POST(self):  # noqa: N802 (BaseHTTPRequestHandler API)
            parsed = urlparse(self.path)
            if parsed.path != '/control/persist':
                self.send_error(404, 'Not Found')
                return

            # Phase 28 plan 28-06 (D-B1): bridge POSTs rendered overlay yaml here;
            # fc_buffer owns the atomic write (T-28-21) and the path allowlist (T-28-20).
            length_raw = self.headers.get('Content-Length')
            try:
                length = int(length_raw) if length_raw else 0
            except ValueError:
                self._send_json(400, {'error': 'invalid Content-Length'})
                return
            if length <= 0:
                self._send_json(400, {'error': 'empty body'})
                return
            if length > PERSIST_REQUEST_MAX_BYTES:
                self._send_json(413, {'error': 'request too large'})
                return

            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode('utf-8'))
            except (ValueError, UnicodeDecodeError) as e:
                self._send_json(400, {'error': f'invalid json: {e}'})
                return
            if not isinstance(payload, dict):
                self._send_json(400, {'error': 'body must be a json object'})
                return

            p = payload.get('path')
            content = payload.get('content')
            if not isinstance(content, str):
                self._send_json(400, {'error': 'content must be string'})
                return
            try:
                _atomic_write_overlay(p, content)
            except ValueError as e:
                self._send_json(400, {'error': str(e)})
                return
            except OSError as e:
                self._send_json(500, {'error': f'write failed: {e}'})
                return
            self._send_json(200, {'ok': True, 'path': p, 'bytes': len(content.encode('utf-8'))})

    return TelemetryHandler


# --- ROS node ----------------------------------------------------------------

def _build_msg_class_map():
    """Resolve YAML msg-type strings to actual rclpy message classes.

    Imported lazily so the module is importable without ROS installed.
    """
    from sensor_msgs.msg import RelativeHumidity, Temperature
    from std_msgs.msg import Bool, Float32

    return {
        'sensor_msgs/RelativeHumidity': RelativeHumidity,
        'sensor_msgs/Temperature': Temperature,
        'std_msgs/Float32': Float32,
        'std_msgs/Bool': Bool,
    }


def _qos_for(label):
    """Map YAML qos label to a rclpy QoSProfile."""
    from rclpy.qos import (
        DurabilityPolicy,
        HistoryPolicy,
        QoSProfile,
        ReliabilityPolicy,
    )

    if label == 'transient_local':
        return QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
        )
    return QoSProfile(
        depth=10,
        durability=DurabilityPolicy.VOLATILE,
        reliability=ReliabilityPolicy.RELIABLE,
        history=HistoryPolicy.KEEP_LAST,
    )


def _make_fc_buffer_class():
    """Construct FcBuffer lazily so module import does not require rclpy."""
    import os

    from ament_index_python.packages import get_package_share_directory
    from rclpy.node import Node

    class FcBuffer(Node):
        """rclpy node — subscribers + SQLite writer + http.server thread + pruner."""

        def __init__(self):
            super().__init__('fc_buffer')

            default_topics_config = os.path.join(
                get_package_share_directory('fc_core'),
                'config',
                'buffered_topics.yaml',
            )

            self.declare_parameters(
                namespace='',
                parameters=[
                    ('db_path', DEFAULT_DB_PATH),
                    ('http_bind', DEFAULT_HTTP_BIND),
                    ('http_port', DEFAULT_HTTP_PORT),
                    ('retention_seconds', DEFAULT_RETENTION_SECONDS),
                    ('prune_interval_seconds', DEFAULT_PRUNE_INTERVAL_SECONDS),
                    ('topics_config', default_topics_config),
                ],
            )

            self._db_path = self.get_parameter('db_path').value
            self._http_bind = self.get_parameter('http_bind').value
            self._http_port = int(self.get_parameter('http_port').value)
            self._retention_seconds = int(
                self.get_parameter('retention_seconds').value
            )
            prune_interval = float(
                self.get_parameter('prune_interval_seconds').value
            )
            topics_path = self.get_parameter('topics_config').value

            # SQLite writer (single connection, serialised by lock).
            self._db_lock = threading.Lock()
            self._db = sqlite3.connect(self._db_path, check_same_thread=False)
            init_schema(self._db)

            # Subscribers.
            self._subs = []
            topics = _load_topics(topics_path)
            msg_classes = _build_msg_class_map()
            for entry in topics:
                ros_topic = entry['ros_topic']
                bridge_topic = entry['bridge_topic']
                msg_cls = msg_classes.get(entry['msg_type'])
                if msg_cls is None:
                    self.get_logger().error(
                        f"[fc_buffer] unknown msg_type {entry['msg_type']} for "
                        f'{ros_topic}; skipping'
                    )
                    continue
                qos = _qos_for(entry.get('qos', 'default'))

                # Per-topic closure binds bridge_topic so the callback knows the key.
                def _cb(msg, _bridge_topic=bridge_topic):
                    self._on_msg(_bridge_topic, msg)

                self._subs.append(
                    self.create_subscription(msg_cls, ros_topic, _cb, qos)
                )

            # Pruner timer.
            self._prune_timer = self.create_timer(
                prune_interval, self._prune_tick
            )

            # HTTP server thread.
            handler_cls = _make_http_handler(self._db_path, self.get_logger())
            self._http_server = ThreadingHTTPServer((self._http_bind, self._http_port), handler_cls)
            self._http_thread = threading.Thread(
                target=self._http_server.serve_forever,
                name='fc_buffer_http',
                daemon=True,
            )
            self._http_thread.start()

            self.get_logger().info(
                f'[fc_buffer] HTTP listening on {self._http_bind}:{self._http_port}, '
                f'db={self._db_path}, topics={len(self._subs)}'
            )

        def _on_msg(self, bridge_topic, msg):
            try:
                ts_ns, value, extra = _extract(bridge_topic, msg)
            except Exception as e:  # noqa: BLE001
                self.get_logger().warning(
                    f'[fc_buffer] extract failed for {bridge_topic}: {e}'
                )
                return
            with self._db_lock:
                _write_row(self._db, bridge_topic, ts_ns, value, extra)

        def _prune_tick(self):
            with self._db_lock:
                _prune(self._db, self._retention_seconds, time.time_ns())

        def destroy_node(self):
            try:
                if getattr(self, '_http_server', None) is not None:
                    self._http_server.shutdown()
                    self._http_server.server_close()
            except Exception:  # noqa: BLE001
                pass
            try:
                if getattr(self, '_db', None) is not None:
                    self._db.close()
            except Exception:  # noqa: BLE001
                pass
            return super().destroy_node()

    return FcBuffer


def main(args=None):
    import rclpy

    rclpy.init(args=args)
    FcBuffer = _make_fc_buffer_class()
    node = FcBuffer()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
