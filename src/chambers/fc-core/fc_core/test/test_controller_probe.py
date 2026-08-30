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

    # RH pinned at the band midpoint: project_error_pct is exactly 0 there, so
    # the PID's in-band integrator decay keeps commanded duty near 0 forever
    # (idle_duty_max=0.5) while still satisfying the probe's own in-band gate.
    node.current_temp = 15.0
    t_ns = 0
    for _ in range(1200):
        node.get_clock = lambda t_ns=t_ns: _mock_clock_at(t_ns)
        node.current_humidity = 0.94
        node._last_humidity_timestamp = node.get_clock().now()
        node.control_loop()
        t_ns += int(1e9)

    assert ('probe', 1.0) in published
    i = published.index(('probe', 1.0))
    assert ('duty', 1.0) in published[i:i + 4]
    node.destroy_node()
