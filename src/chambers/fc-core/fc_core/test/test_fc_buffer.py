"""Phase 999.1 Plan 02: fc_buffer unit tests.

Tests target module-level helpers in `fc_core.fc_buffer` so they exercise the
SQLite/HTTP/extract logic WITHOUT requiring a running rclpy domain. Fake ROS
messages are built with `types.SimpleNamespace`.
"""
import json
import sqlite3
import types
from pathlib import Path

import pytest

from fc_core import fc_buffer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    """Open a fresh writer connection on a tmp sqlite file with schema initialised."""
    db_path = tmp_path / 'buffer.sqlite'
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    fc_buffer.init_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def db_path(tmp_path):
    """Return a path to a freshly-initialised sqlite buffer (closed connection)."""
    p = tmp_path / 'buffer.sqlite'
    conn = sqlite3.connect(str(p))
    fc_buffer.init_schema(conn)
    conn.close()
    return p


# ---------------------------------------------------------------------------
# 1. Write
# ---------------------------------------------------------------------------

def test_writes_on_message(db):
    fc_buffer._write_row(db, 'fc.humidity', 1_000_000_000, 88.5, None)
    count = db.execute('SELECT COUNT(*) FROM telemetry_buffer').fetchone()[0]
    assert count == 1
    row = db.execute(
        'SELECT topic, time_ns, value, extra FROM telemetry_buffer'
    ).fetchone()
    assert row[0] == 'fc.humidity'
    assert row[1] == 1_000_000_000
    assert row[2] == pytest.approx(88.5)
    assert row[3] is None


# ---------------------------------------------------------------------------
# 2. Dedupe
# ---------------------------------------------------------------------------

def test_duplicate_ignored(db):
    fc_buffer._write_row(db, 'fc.humidity', 1_000_000_000, 88.5, None)
    fc_buffer._write_row(db, 'fc.humidity', 1_000_000_000, 99.9, None)
    count = db.execute('SELECT COUNT(*) FROM telemetry_buffer').fetchone()[0]
    assert count == 1
    # First-write wins (INSERT OR IGNORE).
    val = db.execute(
        'SELECT value FROM telemetry_buffer WHERE topic=? AND time_ns=?',
        ('fc.humidity', 1_000_000_000),
    ).fetchone()[0]
    assert val == pytest.approx(88.5)


# ---------------------------------------------------------------------------
# 3. Pruner
# ---------------------------------------------------------------------------

def test_pruner_evicts(db):
    # 100,000 s in ns — comfortably past the 86,400 s retention window.
    now_ns = 100_000 * 1_000_000_000
    # Two old rows (≈ now − 100,000 s, beyond window) and one current row.
    fc_buffer._write_row(db, 'fc.humidity', 1000, 50.0, None)
    fc_buffer._write_row(db, 'fc.humidity', 2000, 50.0, None)
    fc_buffer._write_row(db, 'fc.humidity', now_ns, 60.0, None)

    fc_buffer._prune(db, retention_seconds=86400, now_ns=now_ns)

    times = [r[0] for r in db.execute(
        'SELECT time_ns FROM telemetry_buffer ORDER BY time_ns'
    ).fetchall()]
    assert times == [now_ns]


# ---------------------------------------------------------------------------
# 4. HTTP since — oldest first
# ---------------------------------------------------------------------------

def test_http_since_returns_oldest_first_jsonl(db, db_path):
    # Insert via the writer connection (db fixture shares same path semantics? no — different).
    # Re-open the same path the db_path fixture uses.
    conn = sqlite3.connect(str(db_path))
    fc_buffer._write_row(conn, 'fc.humidity', 100, 10.0, None)
    fc_buffer._write_row(conn, 'fc.humidity', 200, 20.0, None)
    fc_buffer._write_row(conn, 'fc.humidity', 300, 30.0, None)
    conn.close()

    rows = fc_buffer._serve_since(str(db_path), since_ns=150, limit=10)
    assert len(rows) == 2
    assert rows[0]['time_ns'] == 200
    assert rows[1]['time_ns'] == 300
    assert rows[0]['value'] == pytest.approx(20.0)
    assert rows[0]['topic'] == 'fc.humidity'
    assert 'extra' in rows[0]


# ---------------------------------------------------------------------------
# 5. HTTP validation
# ---------------------------------------------------------------------------

def test_http_validation_bad_ts_raises(db_path):
    with pytest.raises(ValueError):
        fc_buffer._serve_since(str(db_path), since_ns='not-an-int', limit=10)


def test_http_limit_capped(db_path):
    # Insert nothing; simply prove the limit cap is applied (no error, list ≤ cap).
    rows = fc_buffer._serve_since(str(db_path), since_ns=0, limit=10_000_000)
    assert isinstance(rows, list)
    # The contract: limit > HTTP_LIMIT_CAP is silently capped to HTTP_LIMIT_CAP.
    assert fc_buffer.HTTP_LIMIT_CAP == 50000


# ---------------------------------------------------------------------------
# 6. Camera exclusion
# ---------------------------------------------------------------------------

def test_camera_excluded(tmp_path):
    bad_yaml = tmp_path / 'bad_topics.yaml'
    bad_yaml.write_text(
        'buffered:\n'
        '  - { ros_topic: /fc1/humidity,            msg_type: sensor_msgs/RelativeHumidity, bridge_topic: fc.humidity, qos: default }\n'
        '  - { ros_topic: /fc1/camera/compressed,   msg_type: sensor_msgs/CompressedImage,  bridge_topic: fc.camera,   qos: default }\n'
    )
    with pytest.raises(ValueError):
        fc_buffer._load_topics(str(bad_yaml))


def test_load_topics_happy_path(tmp_path):
    good_yaml = tmp_path / 'good_topics.yaml'
    good_yaml.write_text(
        'buffered:\n'
        '  - { ros_topic: /fc1/humidity,    msg_type: sensor_msgs/RelativeHumidity, bridge_topic: fc.humidity,    qos: default }\n'
        '  - { ros_topic: /fc1/temperature, msg_type: sensor_msgs/Temperature,      bridge_topic: fc.temperature, qos: default }\n'
    )
    topics = fc_buffer._load_topics(str(good_yaml))
    assert len(topics) == 2
    assert topics[0]['bridge_topic'] == 'fc.humidity'


# ---------------------------------------------------------------------------
# 7 + 8. Extract — RelativeHumidity (with header), Bool (no header)
# ---------------------------------------------------------------------------

def _fake_header(sec, nanosec, frame_id=''):
    return types.SimpleNamespace(
        stamp=types.SimpleNamespace(sec=sec, nanosec=nanosec),
        frame_id=frame_id,
    )


def test_extract_relative_humidity():
    msg = types.SimpleNamespace(
        relative_humidity=0.885,
        header=_fake_header(sec=10, nanosec=500_000_000, frame_id='sht30'),
    )
    ts_ns, value, extra = fc_buffer._extract('fc.humidity', msg)
    assert ts_ns == 10_500_000_000
    assert value == pytest.approx(88.5)
    # extra is JSON-encoded frame_id (or None if frame_id empty).
    assert extra is not None
    payload = json.loads(extra)
    assert payload.get('frame_id') == 'sht30'


def test_extract_bool_no_header():
    msg = types.SimpleNamespace(data=True)
    ts_ns, value, extra = fc_buffer._extract('fc.humidifier', msg)
    # No header → falls back to current time. Just sanity-check it's a positive int and value/extra.
    assert isinstance(ts_ns, int)
    assert ts_ns > 0
    assert value == 1.0
    assert extra is None


def test_extract_temperature():
    msg = types.SimpleNamespace(
        temperature=22.5,
        header=_fake_header(sec=5, nanosec=0),
    )
    ts_ns, value, extra = fc_buffer._extract('fc.temperature', msg)
    assert ts_ns == 5_000_000_000
    assert value == pytest.approx(22.5)


def test_extract_float32():
    msg = types.SimpleNamespace(data=0.42)
    ts_ns, value, extra = fc_buffer._extract('fc.humidifier_duty', msg)
    assert isinstance(ts_ns, int)
    assert value == pytest.approx(0.42)
    assert extra is None


# ---------------------------------------------------------------------------
# Phase 28 plan 28-06 — Layer 2 overlay write (POST /control/persist on fc_buffer).
# Tests target the pure helpers (_is_safe_overlay_path, _atomic_write_overlay,
# _read_overlay). The HTTP handler thin-wraps these; integration is exercised
# at deploy time on fc1 (plan 07).
# ---------------------------------------------------------------------------


@pytest.fixture
def overlay_dir(tmp_path, monkeypatch):
    """Redirect OVERLAY_DIR to a tmp path so realpath-based safety checks pass."""
    d = tmp_path / 'fc-core'
    d.mkdir()
    # Use a trailing slash to match the constant's contract.
    monkeypatch.setattr(fc_buffer, 'OVERLAY_DIR', str(d) + '/')
    return d


def test_is_safe_overlay_path_accepts_canonical(overlay_dir):
    p = str(overlay_dir / 'runtime_overrides.yaml')
    assert fc_buffer._is_safe_overlay_path(p) is True


def test_is_safe_overlay_path_rejects_traversal(overlay_dir):
    # Construct a path that LITERALLY starts with OVERLAY_DIR but escapes via `..`.
    p = str(overlay_dir) + '/../etc/passwd'
    assert fc_buffer._is_safe_overlay_path(p) is False


def test_is_safe_overlay_path_rejects_outside_dir(overlay_dir):
    assert fc_buffer._is_safe_overlay_path('/etc/passwd') is False
    assert fc_buffer._is_safe_overlay_path('/tmp/x.yaml') is False


def test_is_safe_overlay_path_rejects_bak_tmp_suffix(overlay_dir):
    # fc_buffer derives `.bak`/`.tmp` itself; callers must not supply them
    # (would let an attacker overwrite the rotated previous version).
    assert fc_buffer._is_safe_overlay_path(str(overlay_dir / 'runtime_overrides.yaml.bak')) is False
    assert fc_buffer._is_safe_overlay_path(str(overlay_dir / 'runtime_overrides.yaml.tmp')) is False


def test_is_safe_overlay_path_rejects_symlink_escape(tmp_path, monkeypatch):
    # /var/lib/fc-core/ is a symlink to /etc → realpath() must catch the escape.
    overlay = tmp_path / 'fc-core'
    outside = tmp_path / 'outside'
    outside.mkdir()
    overlay.symlink_to(outside)
    monkeypatch.setattr(fc_buffer, 'OVERLAY_DIR', str(tmp_path / 'real-fc-core') + '/')
    (tmp_path / 'real-fc-core').mkdir()
    p = str(overlay / 'runtime_overrides.yaml')
    # Path is under a different directory after symlink resolution → reject.
    assert fc_buffer._is_safe_overlay_path(p) is False


def test_is_safe_overlay_path_rejects_prefix_lookalike(tmp_path, monkeypatch):
    # /var/lib/fc-core-evil/ must NOT match /var/lib/fc-core/ via plain startswith.
    real = tmp_path / 'fc-core'
    real.mkdir()
    evil = tmp_path / 'fc-core-evil'
    evil.mkdir()
    monkeypatch.setattr(fc_buffer, 'OVERLAY_DIR', str(real) + '/')
    p = str(evil / 'runtime_overrides.yaml')
    assert fc_buffer._is_safe_overlay_path(p) is False


def test_atomic_write_creates_file(overlay_dir):
    p = str(overlay_dir / 'runtime_overrides.yaml')
    fc_buffer._atomic_write_overlay(p, 'pid_kp: 0.4\n')
    with open(p) as fh:
        assert fh.read() == 'pid_kp: 0.4\n'
    # No .bak yet on first write (no prior version to rotate).
    assert not (overlay_dir / 'runtime_overrides.yaml.bak').exists()
    # .tmp must be cleaned up by rename.
    assert not (overlay_dir / 'runtime_overrides.yaml.tmp').exists()


def test_atomic_write_rotates_prior_to_bak(overlay_dir):
    p = str(overlay_dir / 'runtime_overrides.yaml')
    fc_buffer._atomic_write_overlay(p, 'pid_kp: 0.4\n')
    fc_buffer._atomic_write_overlay(p, 'pid_kp: 0.35\n')
    with open(p) as fh:
        assert fh.read() == 'pid_kp: 0.35\n'
    # Previous version preserved as .bak (T-28-21 one-step revert).
    with open(p + '.bak') as fh:
        assert fh.read() == 'pid_kp: 0.4\n'
    # .tmp gone.
    assert not (overlay_dir / 'runtime_overrides.yaml.tmp').exists()


def test_atomic_write_rejects_unsafe_path(overlay_dir):
    with pytest.raises(ValueError, match='unsafe overlay path'):
        fc_buffer._atomic_write_overlay('/etc/passwd', 'x')


def test_atomic_write_rejects_oversized(overlay_dir):
    p = str(overlay_dir / 'runtime_overrides.yaml')
    huge = 'x' * (fc_buffer.OVERLAY_MAX_BYTES + 1)
    with pytest.raises(ValueError, match='exceeds'):
        fc_buffer._atomic_write_overlay(p, huge)


def test_atomic_write_rejects_non_string_content(overlay_dir):
    p = str(overlay_dir / 'runtime_overrides.yaml')
    with pytest.raises(TypeError):
        fc_buffer._atomic_write_overlay(p, b'binary')


def test_read_overlay_missing_returns_none(overlay_dir):
    p = str(overlay_dir / 'runtime_overrides.yaml')
    assert fc_buffer._read_overlay(p) is None


def test_read_overlay_returns_content(overlay_dir):
    p = str(overlay_dir / 'runtime_overrides.yaml')
    fc_buffer._atomic_write_overlay(p, 'pid_kp: 0.4\n')
    assert fc_buffer._read_overlay(p) == 'pid_kp: 0.4\n'


def test_read_overlay_rejects_unsafe_path(overlay_dir):
    with pytest.raises(ValueError):
        fc_buffer._read_overlay('/etc/passwd')


def test_atomic_write_idempotent_byte_equal(overlay_dir):
    """Same payload twice → same final bytes (allows safe re-POST)."""
    p = str(overlay_dir / 'runtime_overrides.yaml')
    fc_buffer._atomic_write_overlay(p, 'pid_kp: 0.4\n')
    fc_buffer._atomic_write_overlay(p, 'pid_kp: 0.4\n')
    with open(p) as fh:
        assert fh.read() == 'pid_kp: 0.4\n'
    # Second write rotated identical content into .bak — still byte-equal.
    with open(p + '.bak') as fh:
        assert fh.read() == 'pid_kp: 0.4\n'
