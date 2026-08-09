"""HUMID-02: Slow-PWM windowing (D-08 120s, D-11 10s min pulse, D-12 rolling cap, defensive OFF)."""
import pytest
from unittest.mock import patch
from std_msgs.msg import Float32, Bool
from rclpy.qos import DurabilityPolicy
from rclpy.parameter import Parameter

from fc_core.fc_pwm_driver import SlowPwmDriver
from conftest import _mock_clock_at


def _make_driver(ros_context):
    """Instantiate SlowPwmDriver with simulation mode ON (default; config overrides on Pi)."""
    node = SlowPwmDriver()
    return node


def _advance_to_new_window(node, duty, t_before_ns, t_after_ns):
    """Arm duty at t_before, advance to t_after (>= window) to lock in on_seconds."""
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(t_before_ns)):
        node._duty_callback(Float32(data=duty))
        node._window_start_ts = node.get_clock().now()
        node._last_duty_msg_ts = node.get_clock().now()
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(t_after_ns)):
        node._last_duty_msg_ts = node.get_clock().now()
        node._tick()  # triggers new window, locks on_seconds


def test_pwm_driver_initialization(ros_context):
    node = _make_driver(ros_context)
    # All params must be declared
    assert node.get_parameter('humidifier_pin').value == 27
    assert node.get_parameter('pwm_window_seconds').value == 120.0
    assert node.get_parameter('min_pulse_seconds').value == 10.0
    assert node.get_parameter('max_duty_5min_avg').value == 0.40
    assert node.get_parameter('actuator_simulation_mode').value is True
    assert node.get_parameter('duty_topic_timeout_seconds').value == 5.0
    node.destroy_node()


def test_duty_history_maxlen_matches_5min_window(ros_context):
    """999.31: deque maxlen scales to pwm_window_seconds (≥5 min coverage),
    not a constant 300 (which would be 10 hours at default 120s window).

    At default window=120s: maxlen = ceil(300/120) = 3 entries (= 360s ≥ 5min).
    A duty-history capacity of 3 means the cap engages over the last 3 windows,
    not over 300 windows (10h), so the rolling-5min cap actually behaves as named.
    """
    import math
    node = _make_driver(ros_context)
    window = node.get_parameter('pwm_window_seconds').value
    expected = max(1, math.ceil(300.0 / window))
    assert node._duty_history.maxlen == expected
    # Sanity: default 120s window → 3 entries, NOT the legacy 300
    assert node._duty_history.maxlen == 3
    node.destroy_node()


def test_window_on_then_off(ros_context):
    """Relay is HIGH for the first on_seconds within a window, LOW thereafter.

    Window: duty=0.5, window=120s → on_sec=60.
    After the new window locks in at t=121s:
      - at elapsed 0s (t=121): HIGH
      - at elapsed 60s (t=181): LOW (60 < 60 is False)
      - at elapsed 61s (t=182): still LOW
    """
    node = _make_driver(ros_context)

    # Step 1: arm duty=0.5 at t=0, advance to t=121 to trigger new window
    _advance_to_new_window(node, duty=0.5, t_before_ns=0, t_after_ns=int(121e9))
    # At new window start (elapsed=0): 0 < 60 → HIGH
    assert node._current_state is True
    assert node._window_on_seconds == 60.0

    # Step 2: within window at elapsed=60s (t = window_start + 60s = 121+60 = 181)
    t_window_start_ns = int(121e9)
    t_elapsed60_ns = t_window_start_ns + int(60e9)
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(t_elapsed60_ns)):
        node._last_duty_msg_ts = node.get_clock().now()
        node._tick()
    # elapsed=60, on_sec=60 → 60 < 60 is False → LOW
    assert node._current_state is False

    # Step 3: at elapsed=61s still LOW
    t_elapsed61_ns = t_window_start_ns + int(61e9)
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(t_elapsed61_ns)):
        node._last_duty_msg_ts = node.get_clock().now()
        node._tick()
    assert node._current_state is False

    node.destroy_node()


def test_min_pulse_skip(ros_context):
    """Duty so low that on_sec < min_pulse → entire window is OFF."""
    node = _make_driver(ros_context)
    # duty=0.05, window=120 → on_sec=6s < 10s min_pulse → round down to 0
    _advance_to_new_window(node, duty=0.05, t_before_ns=0, t_after_ns=int(121e9))
    assert node._window_on_seconds == 0.0
    assert node._current_state is False

    node.destroy_node()


def test_min_pulse_passes_at_floor(ros_context):
    """Duty at exactly the min-pulse boundary (10s/120s=0.0833) should emit ON."""
    node = _make_driver(ros_context)
    duty_at_floor = 10.0 / 120.0  # exactly 10s

    _advance_to_new_window(node, duty=duty_at_floor, t_before_ns=0, t_after_ns=int(121e9))
    # on_sec = 10.0 which is == min_pulse (not < min_pulse) → should be kept
    assert node._window_on_seconds == pytest.approx(10.0, abs=0.001)

    node.destroy_node()


def test_rolling_max_cap_engages(ros_context):
    """Rolling 5-min cap keeps average duty ≤ 0.40."""
    node = _make_driver(ros_context)
    cap = 0.40

    # Feed duty=1.0 over enough windows to fill the history.
    # 999.31 fix: deque appends once per window rollover, maxlen scales to
    # ~5min/window — for window=120s that's 3 entries; for window=60s that's 5.
    # After a few windows of 100% duty, cap should kick in.
    for i in range(12):  # 12 windows × 121s = enough for cap to engage
        t_before_ns = int(i * 121e9)
        t_after_ns = int((i + 1) * 121e9)
        with patch.object(node, 'get_clock', return_value=_mock_clock_at(t_before_ns)):
            node._duty_callback(Float32(data=1.0))
            node._last_duty_msg_ts = node.get_clock().now()
        with patch.object(node, 'get_clock', return_value=_mock_clock_at(t_after_ns)):
            node._last_duty_msg_ts = node.get_clock().now()
            node._tick()

    # All recorded duty values in history should result in avg ≤ cap
    if len(node._duty_history) > 0:
        avg = sum(node._duty_history) / len(node._duty_history)
        assert avg <= cap + 0.01  # small tolerance for the window where cap just engages

    node.destroy_node()


def test_duty_silence_forces_off(ros_context):
    """If duty topic goes silent, relay is forced OFF."""
    node = _make_driver(ros_context)

    t0_ns = 0
    # No callback ever fired → _last_duty_msg_ts is None → must be OFF
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(t0_ns)):
        node._tick()
    assert node._current_state is False

    # Now fire callback at t=0, then advance 6s (> 5s timeout) → force OFF
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(t0_ns)):
        node._duty_callback(Float32(data=0.9))
        node._window_start_ts = node.get_clock().now()
        node._last_duty_msg_ts = node.get_clock().now()

    t6_ns = int(6e9)
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(t6_ns)):
        node._tick()
    assert node._current_state is False

    node.destroy_node()


def test_bool_published_on_edge_only(ros_context):
    """Bool is published ONLY on state transitions (edges), not every tick.

    Strategy: trigger one window at duty=0.5 (on_sec=60).
    Window starts at t=121s, advances to t=181s (60s ON) then t=182s (OFF).
    Expect exactly 2 publications: one OFF→ON at window start, one ON→OFF at t=60.
    """
    node = _make_driver(ros_context)
    published = []
    node._state_pub.publish = lambda msg: published.append(msg.data)

    # Lock in duty=0.5 (on_sec=60) at the new window (t_before=0, t_new_window=121s)
    t_new_window_ns = int(121e9)
    _advance_to_new_window(node, duty=0.5, t_before_ns=0, t_after_ns=t_new_window_ns)
    # OFF→ON edge fires here (published[0] = True)

    # Tick at elapsed=1..59s inside window → no new edges (still HIGH)
    for tick_offset_ns in [int(i * 1e9) for i in range(1, 60)]:
        t = t_new_window_ns + tick_offset_ns
        with patch.object(node, 'get_clock', return_value=_mock_clock_at(t)):
            node._last_duty_msg_ts = node.get_clock().now()
            node._tick()

    # At elapsed=60s: ON→OFF edge fires
    t_off_ns = t_new_window_ns + int(60e9)
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(t_off_ns)):
        node._last_duty_msg_ts = node.get_clock().now()
        node._tick()

    # More ticks in OFF region → no additional edges
    for tick_offset_ns in [int(i * 1e9) for i in range(61, 65)]:
        t = t_new_window_ns + tick_offset_ns
        with patch.object(node, 'get_clock', return_value=_mock_clock_at(t)):
            node._last_duty_msg_ts = node.get_clock().now()
            node._tick()

    # Exactly 2 publications
    assert len(published) == 2
    assert published[0] is True    # OFF→ON edge
    assert published[1] is False   # ON→OFF edge

    node.destroy_node()


def test_duty_subscription_qos_transient_local(ros_context):
    """Duty subscription must use TRANSIENT_LOCAL QoS (Pitfall 5)."""
    node = _make_driver(ros_context)
    qos = node._duty_sub.qos_profile
    assert qos.durability == DurabilityPolicy.TRANSIENT_LOCAL
    node.destroy_node()


def test_humidifier_pub_qos_transient_local(ros_context):
    """Humidifier Bool publisher must use TRANSIENT_LOCAL QoS (Phase 04 ACTR-03)."""
    node = _make_driver(ros_context)
    qos = node._state_pub.qos_profile
    assert qos.durability == DurabilityPolicy.TRANSIENT_LOCAL
    node.destroy_node()


def test_clamps_negative_duty_to_zero(ros_context):
    """Negative duty values are clamped to 0.0 before windowing."""
    node = _make_driver(ros_context)
    node._duty_callback(Float32(data=-0.5))
    assert node._latest_duty == 0.0
    node.destroy_node()


def test_clamps_above_one_to_one(ros_context):
    """Duty values above 1.0 are clamped to 1.0 before windowing."""
    node = _make_driver(ros_context)
    node._duty_callback(Float32(data=1.5))
    assert node._latest_duty == 1.0
    node.destroy_node()


# ---------------------------------------------------------------------------
# Sub-threshold pulse accumulation (2026-08-09). Default OFF -- the first test
# pins that, because turning it on by accident changes actuator behaviour on a
# live grow.
# ---------------------------------------------------------------------------

def test_accumulate_subthreshold_defaults_off(ros_context):
    node = _make_driver(ros_context)
    assert node.get_parameter('accumulate_subthreshold').value is False
    node.destroy_node()


def test_accumulation_off_still_discards_subthreshold(ros_context):
    """Default path must be byte-identical to the pre-change behaviour."""
    node = _make_driver(ros_context)
    _advance_to_new_window(node, duty=0.05, t_before_ns=0, t_after_ns=int(121e9))
    assert node._window_on_seconds == 0.0
    node.destroy_node()


def test_accumulation_banks_then_fires_a_full_pulse(ros_context):
    """duty=0.05 -> 6s/window. Banks until >= 10s, then emits exactly 10s."""
    node = _make_driver(ros_context)
    node.set_parameters([Parameter(
        'accumulate_subthreshold', Parameter.Type.BOOL, True)])

    t = 0
    fired = []
    for _ in range(6):
        t += int(121e9)
        _advance_to_new_window(node, duty=0.05, t_before_ns=t - int(121e9), t_after_ns=t)
        fired.append(node._window_on_seconds)

    # 6s banked per window: windows 1 and 2 bank (0s out), window 2 reaches 12s
    # so it fires 10s and carries 2s. Never a pulse shorter than min_pulse.
    assert any(f > 0.0 for f in fired), f'accumulation never fired: {fired}'
    assert all(f == 0.0 or f >= 10.0 for f in fired), f'short pulse emitted: {fired}'


def test_accumulation_preserves_mean_duty(ros_context):
    """Banked demand must come out, not vanish. Mean over many windows ~= 0.05."""
    node = _make_driver(ros_context)
    node.set_parameters([Parameter(
        'accumulate_subthreshold', Parameter.Type.BOOL, True)])

    t = 0
    total_on = 0.0
    windows = 40
    for _ in range(windows):
        t += int(121e9)
        _advance_to_new_window(node, duty=0.05, t_before_ns=t - int(121e9), t_after_ns=t)
        total_on += node._window_on_seconds

    mean_duty = total_on / (windows * 120.0)
    assert mean_duty == pytest.approx(0.05, rel=0.25), f'got {mean_duty:.4f}'
    node.destroy_node()


def test_accumulation_is_noop_above_the_floor(ros_context):
    """Duty above min_pulse/window must be untouched by accumulation."""
    node = _make_driver(ros_context)
    node.set_parameters([Parameter(
        'accumulate_subthreshold', Parameter.Type.BOOL, True)])
    _advance_to_new_window(node, duty=0.25, t_before_ns=0, t_after_ns=int(121e9))
    assert node._window_on_seconds == pytest.approx(30.0, abs=0.001)
    node.destroy_node()
