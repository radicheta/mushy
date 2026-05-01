"""HUMID-02: Slow-PWM windowing (D-08 120s, D-11 10s min pulse, D-12 rolling cap, defensive OFF)."""

import pytest
from std_msgs.msg import Float32, Bool
from rclpy.qos import DurabilityPolicy
from conftest import _mock_clock_at
from unittest.mock import patch

# This import WILL fail until Wave 1 creates fc_pwm_driver.py — that is the correct RED state.
from fc_core.fc_pwm_driver import SlowPwmDriver  # noqa: E402


def _make_driver(ros_context):
    """Instantiate SlowPwmDriver in simulation mode."""
    from rclpy.parameter import Parameter
    node = SlowPwmDriver()
    node.set_parameters([Parameter('actuator_simulation_mode', value=True)])
    return node


def test_pwm_driver_initialization(ros_context):
    """SlowPwmDriver instantiates and declares required parameters."""
    node = _make_driver(ros_context)
    # All required params must be declared
    node.get_parameter('humidifier_pin')
    node.get_parameter('pwm_window_seconds')
    node.get_parameter('min_pulse_seconds')
    node.get_parameter('max_duty_5min_avg')
    node.get_parameter('actuator_simulation_mode')
    node.get_parameter('duty_topic_timeout_seconds')
    node.destroy_node()


def test_window_on_then_off(ros_context):
    """With duty=0.5, relay is HIGH for first 60s of 120s window, then LOW at 61s."""
    node = _make_driver(ros_context)

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(0)):
        node._duty_callback(Float32(data=0.5))
        node._tick()
        assert node._current_state is True, 'Relay should be HIGH at window start with duty=0.5'

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(60e9))):
        node._tick()
        assert node._current_state is True, 'Relay should still be HIGH at 60s (on_seconds=60)'

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(61e9))):
        node._tick()
        assert node._current_state is False, 'Relay should be LOW at 61s (past on_seconds=60)'

    node.destroy_node()


def test_min_pulse_skip(ros_context):
    """duty=0.05 → on_seconds=6s < 10s min_pulse → entire window emits OFF."""
    node = _make_driver(ros_context)

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(0)):
        node._duty_callback(Float32(data=0.05))  # 120s * 0.05 = 6s < 10s floor
        node._tick()
        assert node._current_state is False, (
            'Relay should be OFF: requested on_seconds (6s) is below min_pulse_seconds (10s)'
        )

    node.destroy_node()


def test_min_pulse_passes_at_floor(ros_context):
    """duty=0.0833333 → on_seconds≈10s exactly at min_pulse_seconds → emits ON then OFF."""
    node = _make_driver(ros_context)

    # 120s * 0.0833333 ≈ 10.0s exactly — must pass the floor check
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(0)):
        node._duty_callback(Float32(data=0.0833333))
        node._tick()
        assert node._current_state is True, (
            'Relay should be ON: requested on_seconds (~10s) meets min_pulse_seconds (10s)'
        )

    # Past on_seconds — relay should drop to OFF
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(11e9))):
        node._tick()
        assert node._current_state is False, 'Relay should be OFF past on_seconds'

    node.destroy_node()


def test_rolling_max_cap_engages(ros_context):
    """Rolling 5-min duty cap (max_duty_5min_avg=0.40) prevents sustained duty > cap."""
    node = _make_driver(ros_context)

    # Feed duty=1.0 for many windows. After enough windows the rolling avg should
    # cause the driver to reduce effective on_seconds so avg stays ≤ 0.40.
    # We simulate 10 complete 120s windows (1200s total) at duty=1.0 and verify
    # that the rolling average reported by the driver stays at or below the cap.
    t = 0
    window = int(node.get_parameter('pwm_window_seconds').value)
    cap = node.get_parameter('max_duty_5min_avg').value

    for i in range(10):
        with patch.object(node, 'get_clock', return_value=_mock_clock_at(t * int(1e9))):
            node._duty_callback(Float32(data=1.0))
            node._tick()
        t += window

    # After many full-duty windows, rolling average must be capped
    rolling_avg = node._rolling_duty_avg()
    assert rolling_avg <= cap + 0.01, (
        f'Rolling duty average {rolling_avg:.3f} exceeds cap {cap}'
    )

    node.destroy_node()


def test_duty_silence_forces_off(ros_context):
    """No _duty_callback ever fires → tick → relay LOW (defensive OFF)."""
    node = _make_driver(ros_context)

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(0)):
        node._tick()
        assert node._current_state is False, 'Relay should be OFF when no duty message received'

    node.destroy_node()


def test_duty_stale_forces_off(ros_context):
    """Callback fires once, then 6s pass with no new msg → relay LOW."""
    node = _make_driver(ros_context)

    with patch.object(node, 'get_clock', return_value=_mock_clock_at(0)):
        node._duty_callback(Float32(data=0.8))
        node._tick()
        assert node._current_state is True, 'Relay should be ON immediately after duty=0.8'

    # 6s later — past duty_topic_timeout_seconds=5.0 — no new msg
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(6e9))):
        node._tick()
        assert node._current_state is False, 'Relay should be OFF after duty msg goes stale (>5s)'

    node.destroy_node()


def test_bool_published_on_edge_only(ros_context):
    """Over 120s at duty=0.5: exactly 2 Bool publications (OFF→ON at t=0, ON→OFF at t=61s)."""
    node = _make_driver(ros_context)

    published = []
    node._state_pub.publish = lambda msg: published.append(msg.data)

    # t=0: duty=0.5, window starts → OFF→ON edge
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(0)):
        node._duty_callback(Float32(data=0.5))
        node._tick()

    # t=30s: still ON, no new edge
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(30e9))):
        node._tick()

    # t=61s: ON→OFF edge
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(61e9))):
        node._tick()

    # t=90s: still OFF, no new edge
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(90e9))):
        node._tick()

    assert len(published) == 2, (
        f'Expected exactly 2 edge publications, got {len(published)}: {published}'
    )
    assert published[0] is True, 'First edge should be OFF→ON (True)'
    assert published[1] is False, 'Second edge should be ON→OFF (False)'

    node.destroy_node()


def test_duty_subscription_qos_transient_local(ros_context):
    """Duty subscription QoS durability is TRANSIENT_LOCAL (Pitfall 5)."""
    node = _make_driver(ros_context)
    qos = node._duty_sub.qos_profile
    assert qos.durability == DurabilityPolicy.TRANSIENT_LOCAL, (
        'Duty subscription must use TRANSIENT_LOCAL to match controller publisher'
    )
    node.destroy_node()


def test_humidifier_pub_qos_transient_local(ros_context):
    """Humidifier Bool publisher QoS durability is TRANSIENT_LOCAL (ACTR-03 contract)."""
    node = _make_driver(ros_context)
    qos = node._state_pub.qos_profile
    assert qos.durability == DurabilityPolicy.TRANSIENT_LOCAL, (
        'Humidifier state publisher must use TRANSIENT_LOCAL (Phase 04 ACTR-03 contract)'
    )
    node.destroy_node()


def test_clamps_negative_duty_to_zero(ros_context):
    """_duty_callback(Float32(data=-0.5)) → latest_duty == 0.0."""
    node = _make_driver(ros_context)
    node._duty_callback(Float32(data=-0.5))
    assert node._latest_duty == 0.0, (
        f'Negative duty must be clamped to 0.0, got {node._latest_duty}'
    )
    node.destroy_node()


def test_clamps_above_one_to_one(ros_context):
    """_duty_callback(Float32(data=1.5)) → latest_duty == 1.0."""
    node = _make_driver(ros_context)
    node._duty_callback(Float32(data=1.5))
    assert node._latest_duty == 1.0, (
        f'Duty above 1.0 must be clamped to 1.0, got {node._latest_duty}'
    )
    node.destroy_node()
