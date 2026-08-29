"""HUMID-02: sigma-delta relay driver (MUSHY-129): min pulse (D-11), duty cap (D-12),
defensive OFF (D-13), edge-only publishing."""
import pytest
from unittest.mock import patch
from std_msgs.msg import Float32
from rclpy.qos import DurabilityPolicy
from rclpy.parameter import Parameter

from fc_core.fc_pwm_driver import SlowPwmDriver
from conftest import _mock_clock_at


def _make_driver(ros_context, **params):
    node = SlowPwmDriver()
    if params:
        node.set_parameters([Parameter(k, Parameter.Type.DOUBLE, float(v)) for k, v in params.items()])
    return node


def _tick(node, t_s, duty):
    """One tick at t_s seconds with the duty topic fresh."""
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(t_s * 1e9))):
        node._duty_callback(Float32(data=duty))
        node._tick()
    return node._current_state


def _run(node, duty, seconds, t0=0.0):
    """Tick 1 Hz for `seconds`; returns (states, t_end)."""
    states = [_tick(node, t0 + i, duty) for i in range(int(seconds))]
    return states, t0 + seconds


def _pulses(states):
    out, run = [], 0
    for s in states + [False]:
        if s:
            run += 1
        elif run:
            out.append(run)
            run = 0
    return out


def test_pwm_driver_initialization(ros_context):
    node = _make_driver(ros_context)
    assert node.get_parameter('humidifier_pin').value == 27
    assert node.get_parameter('pwm_window_seconds').value == 120.0
    assert node.get_parameter('min_pulse_seconds').value == 10.0
    assert node.get_parameter('max_duty_5min_avg').value == 0.40
    assert node.get_parameter('cap_horizon_seconds').value == 300.0
    assert node.get_parameter('actuator_simulation_mode').value is True
    assert node.get_parameter('duty_topic_timeout_seconds').value == 5.0
    node.destroy_node()


def test_step_fires_within_one_min_pulse(ros_context):
    """The 2026-08-29 miss: quiet at 0.03, then demand steps to 0.8. The old
    window waited for its next rollover (up to 480s); now min_pulse/d."""
    node = _make_driver(ros_context, pwm_window_seconds=480.0, min_pulse_seconds=30.0,
                        max_duty_5min_avg=0.90, cap_horizon_seconds=960.0)
    states, t = _run(node, 0.03, 100)
    assert not any(states)
    states, _ = _run(node, 0.8, 60, t)
    first_on = states.index(True)
    assert first_on <= 40
    node.destroy_node()


def test_steady_state_reproduces_the_window(ros_context):
    """duty 0.2 at T=480: the window gave 96s ON / 384s OFF. So must this."""
    node = _make_driver(ros_context, pwm_window_seconds=480.0, min_pulse_seconds=30.0,
                        max_duty_5min_avg=0.90, cap_horizon_seconds=960.0)
    states, _ = _run(node, 0.2, 480 * 4)
    pulses = _pulses(states)
    assert len(pulses) == 4
    assert all(p == pytest.approx(96, abs=2) for p in pulses[1:])
    node.destroy_node()


def test_never_emits_a_short_pulse(ros_context):
    node = _make_driver(ros_context)
    t = 0.0
    all_states = []
    for duty in (0.05, 0.02, 0.5, 0.0):
        states, t = _run(node, duty, 600, t)
        all_states += states
    pulses = _pulses(all_states)
    assert pulses and min(pulses) >= 10
    node.destroy_node()


def test_subthreshold_demand_is_banked_not_discarded(ros_context):
    """duty 0.05 at 10s/120s: unexpressible as a window pulse, but must still
    come out as full-length pulses with the mean preserved."""
    node = _make_driver(ros_context)
    states, _ = _run(node, 0.05, 4800)
    assert sum(states) / 4800 == pytest.approx(0.05, rel=0.25)
    node.destroy_node()


def test_demand_collapse_ends_pulse_at_the_floor(ros_context):
    node = _make_driver(ros_context)
    before, t = _run(node, 1.0, 10)     # bank reaches 10s on the 10th tick -> ON
    assert before[-1] is True
    after, _ = _run(node, 0.0, 30, t)
    assert _pulses(before + after) == [10]
    node.destroy_node()


def test_rolling_max_cap_engages(ros_context):
    """Sustained 1.0 must average <= cap over the horizon."""
    node = _make_driver(ros_context)
    states, _ = _run(node, 1.0, 1200)
    assert sum(states[300:]) / 900 <= 0.40 + 0.02
    node.destroy_node()


def test_duty_silence_forces_off(ros_context):
    node = _make_driver(ros_context)
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(0)):
        node._tick()
    assert node._current_state is False

    _run(node, 1.0, 12)
    assert node._current_state is True
    with patch.object(node, 'get_clock', return_value=_mock_clock_at(int(18e9))):
        node._tick()          # last duty msg at t=11, now t=18 -> silent > 5s
    assert node._current_state is False
    node.destroy_node()


def test_stalled_timer_does_not_bank_minutes_of_demand(ros_context):
    node = _make_driver(ros_context)
    _tick(node, 0.0, 0.5)
    _tick(node, 120.0, 0.5)   # 2 min gap -> clamped to 5s of banking
    assert node._bank_s <= 5.0 * 0.5 + 0.5
    node.destroy_node()


def test_bool_published_on_edge_only(ros_context):
    node = _make_driver(ros_context)
    published = []
    node._state_pub.publish = lambda msg: published.append(msg.data)
    states, _ = _run(node, 0.5, 240)
    edges = sum(1 for i in range(1, len(states)) if states[i] != states[i - 1]) + int(states[0])
    assert published and len(published) == edges
    assert published[0] is True
    node.destroy_node()


def test_duty_subscription_qos_transient_local(ros_context):
    node = _make_driver(ros_context)
    assert node._duty_sub.qos_profile.durability == DurabilityPolicy.TRANSIENT_LOCAL
    node.destroy_node()


def test_humidifier_pub_qos_transient_local(ros_context):
    node = _make_driver(ros_context)
    assert node._state_pub.qos_profile.durability == DurabilityPolicy.TRANSIENT_LOCAL
    node.destroy_node()


def test_clamps_negative_duty_to_zero(ros_context):
    node = _make_driver(ros_context)
    node._duty_callback(Float32(data=-0.5))
    assert node._latest_duty == 0.0
    node.destroy_node()


def test_clamps_above_one_to_one(ros_context):
    node = _make_driver(ros_context)
    node._duty_callback(Float32(data=1.5))
    assert node._latest_duty == 1.0
    node.destroy_node()
