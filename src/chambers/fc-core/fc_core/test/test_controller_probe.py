#!/usr/bin/env python3
"""MUSHY-138: identification probe wiring in fc_controller."""
import pytest
import rclpy

from fc_core.fc_controller import FruitingChamberController
from fc_core.test.test_controller import _mock_clock_at


@pytest.fixture
def ros_context():
    rclpy.init()
    yield
    rclpy.shutdown()


def _tick(node, t_ns):
    """One control_loop tick with fresh, in-band (midpoint) readings.

    RH pinned at the band midpoint: project_error_pct is exactly 0 there, so
    the PID's in-band integrator decay keeps commanded duty near 0 forever
    (idle_duty_max=0.5) while still satisfying the probe's own in-band gate.
    """
    node.get_clock = lambda t_ns=t_ns: _mock_clock_at(t_ns)
    node.current_humidity = 0.94
    node._last_humidity_timestamp = node.get_clock().now()
    node.control_loop()


def test_probe_params_declared(ros_context):
    node = FruitingChamberController()
    assert node.get_parameter('probe_seconds').value == 150.0
    assert node.get_parameter('probe_interval_h').value == 0.0
    assert node.get_parameter('fill_g_per_h').value == pytest.approx(3.890)
    assert node.get_parameter('surface_g_per_k').value == pytest.approx(2.77)
    node.destroy_node()


def test_probe_publishes_marker_and_full_duty(ros_context):
    node = FruitingChamberController()
    node._grace_active = lambda: False  # bypass grace — not under test here
    node.set_parameters([rclpy.parameter.Parameter('probe_interval_h', value=0.001)])

    published = []
    node._probe_pub.publish = lambda m: published.append(('probe', m.data))
    node._duty_pub.publish = lambda m: published.append(('duty', m.data))

    node.current_temp = 15.0
    t_ns = 0
    for _ in range(1200):
        _tick(node, t_ns)
        t_ns += int(1e9)

    assert ('probe', 1.0) in published
    i = published.index(('probe', 1.0))
    assert ('duty', 1.0) in published[i:i + 4]

    pre_probe_duty = [m for (topic, m) in published[:i] if topic == 'duty'][-1]

    # Probe ends: marker goes back to 0.0, and the loop re-engages with the
    # PRE-probe duty, not the Mode C 1.0.
    assert ('probe', 0.0) in published[i:]
    j = published.index(('probe', 0.0), i)
    duties_after_end = [m for (topic, m) in published[j:] if topic == 'duty']
    assert duties_after_end
    assert duties_after_end[0] == pytest.approx(pre_probe_duty)
    node.destroy_node()


def test_probe_aborted_by_param_change_mid_probe(ros_context):
    node = FruitingChamberController()
    node._grace_active = lambda: False  # bypass grace — not under test here
    node.set_parameters([rclpy.parameter.Parameter('probe_interval_h', value=0.001)])

    published = []
    node._probe_pub.publish = lambda m: published.append(('probe', m.data))
    node._duty_pub.publish = lambda m: published.append(('duty', m.data))

    node.current_temp = 15.0
    t_ns = 0
    for _ in range(1200):
        _tick(node, t_ns)
        t_ns += int(1e9)
        if ('probe', 1.0) in published:
            break
    assert ('probe', 1.0) in published, 'probe never started'

    # Mid-probe: a live parameter change (e.g. an operator adjusting
    # probe_seconds) must abort the in-flight probe cleanly rather than
    # leaving the marker latched at 1.0 or preloading the integrator at
    # full duty.
    node.set_parameters([rclpy.parameter.Parameter('probe_seconds', value=120.0)])
    assert ('probe', 0.0) in published

    published.clear()
    _tick(node, t_ns)
    assert ('duty', 1.0) not in published
    node.destroy_node()


def _start_probe(node, published):
    """Run ticks until the probe is commanding; returns the next tick time."""
    node._grace_active = lambda: False  # bypass grace — not under test here
    node.set_parameters([rclpy.parameter.Parameter('probe_interval_h', value=0.001)])
    node._probe_pub.publish = lambda m: published.append(('probe', m.data))
    node._duty_pub.publish = lambda m: published.append(('duty', m.data))
    node.current_temp = 15.0
    t_ns = 0
    for _ in range(1200):
        _tick(node, t_ns)
        t_ns += int(1e9)
        if ('probe', 1.0) in published:
            break
    assert ('probe', 1.0) in published, 'probe never started'
    return t_ns


def test_probe_aborted_by_force_duty_mid_probe(ros_context):
    """A force experiment starting mid-probe must not leave the marker latched
    (and the probe must not resume commanding 1.0 on the live humidifier)."""
    node = FruitingChamberController()
    published = []
    t_ns = _start_probe(node, published)

    # band_low/band_high too: left at their NaN sentinel, _resolve_active_mode
    # takes the legacy synthesize-from-target path, which hardcodes force_duty
    # to NaN and would make this test vacuous.
    node.set_parameters([
        rclpy.parameter.Parameter('modes.fruiting.band_low', value=0.89),
        rclpy.parameter.Parameter('modes.fruiting.band_high', value=0.99),
        rclpy.parameter.Parameter('modes.fruiting.force_duty', value=0.3)])
    published.clear()
    _tick(node, t_ns)

    assert ('probe', 0.0) in published
    duties = [m for (topic, m) in published if topic == 'duty']
    assert duties == [pytest.approx(0.3)]

    # ...and it stays force-driven; the probe does not resume.
    published.clear()
    _tick(node, t_ns + int(1e9))
    assert ('duty', 1.0) not in published
    node.destroy_node()


def test_probe_aborted_by_staleness_mid_probe(ros_context):
    node = FruitingChamberController()
    published = []
    t_ns = _start_probe(node, published)

    # Stop refreshing the humidity stamp: the next tick, far in the future,
    # trips the staleness guard.
    published.clear()
    node.get_clock = lambda: _mock_clock_at(t_ns + int(3600e9))
    node.control_loop()

    assert ('probe', 0.0) in published
    duties = [m for (topic, m) in published if topic == 'duty']
    assert duties == [pytest.approx(0.0)]
    node.destroy_node()
