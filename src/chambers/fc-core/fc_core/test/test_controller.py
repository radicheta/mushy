#!/usr/bin/env python3
import pytest
import rclpy
from sensor_msgs.msg import Temperature, RelativeHumidity
from fc_core.fc_controller import FruitingChamberController
import time
from unittest.mock import patch

@pytest.fixture
def ros_context():
    rclpy.init()
    yield
    rclpy.shutdown()

def test_controller_initialization(ros_context):
    node = FruitingChamberController()
    assert node is not None
    node.destroy_node()

def test_temperature_control(ros_context):
    node = FruitingChamberController()
    
    # Test temperature below target
    temp_msg = Temperature()
    temp_msg.temperature = node.get_parameter('target_temp').value - 2.0
    node.temperature_callback(temp_msg)
    
    # Test humidity at target
    humidity_msg = RelativeHumidity()
    humidity_msg.relative_humidity = node.get_parameter('target_humidity').value
    node.humidity_callback(humidity_msg)
    
    # Run control loop
    node.control_loop()
    
    # Fan should be at minimum speed
    assert node.fan_pwm.get_duty_cycle() == node.get_parameter('min_fan_speed').value
    
    # Test temperature above target
    temp_msg.temperature = node.get_parameter('target_temp').value + 2.0
    node.temperature_callback(temp_msg)
    node.control_loop()
    
    # Fan should be at higher speed
    assert node.fan_pwm.get_duty_cycle() > node.get_parameter('min_fan_speed').value
    
    node.destroy_node()

def test_humidity_control(ros_context):
    node = FruitingChamberController()
    
    # Test humidity below target
    humidity_msg = RelativeHumidity()
    humidity_msg.relative_humidity = node.get_parameter('target_humidity').value - 0.1
    node.humidity_callback(humidity_msg)
    
    # Test temperature at target
    temp_msg = Temperature()
    temp_msg.temperature = node.get_parameter('target_temp').value
    node.temperature_callback(temp_msg)
    
    # Run control loop
    node.control_loop()
    
    # Humidifier should be ON
    assert node.humidifier_state == True
    
    # Test humidity above target
    humidity_msg.relative_humidity = node.get_parameter('target_humidity').value + 0.1
    node.humidity_callback(humidity_msg)
    node.control_loop()
    
    # Humidifier should be OFF
    assert node.humidifier_state == False
    
    node.destroy_node()

def test_light_control(ros_context):
    node = FruitingChamberController()

    # Test during light hours
    node.set_parameter('light_start_hour', 6)
    node.set_parameter('target_light_hours', 12)

    # Mock current hour to 10 AM
    with patch('datetime.datetime') as mock_datetime:
        mock_datetime.now.return_value.hour = 10
        assert node.should_light_be_on() == True

    # Test outside light hours
    with patch('datetime.datetime') as mock_datetime:
        mock_datetime.now.return_value.hour = 2
        assert node.should_light_be_on() == False

    node.destroy_node()


def _send_humidity(node, value):
    msg = RelativeHumidity()
    msg.relative_humidity = value
    node.humidity_callback(msg)


def test_humidity_spike_rejection(ros_context):
    """After 5 readings [0.80, 0.82, 0.81, 0.99, 0.83], median (0.82) replaces spike (0.99)."""
    node = FruitingChamberController()

    for v in [0.80, 0.82, 0.81, 0.99, 0.83]:
        _send_humidity(node, v)

    # sorted: [0.80, 0.81, 0.82, 0.83, 0.99] -> median = 0.82
    assert node.current_humidity == pytest.approx(0.82)

    node.destroy_node()


def test_humidity_median_partial_buffer(ros_context):
    """With only 3 readings [0.80, 0.82, 0.81], median of available samples is used."""
    node = FruitingChamberController()

    for v in [0.80, 0.82, 0.81]:
        _send_humidity(node, v)

    # sorted: [0.80, 0.81, 0.82] -> median = 0.81
    assert node.current_humidity == pytest.approx(0.81)

    node.destroy_node()


def test_humidity_buffer_fifo(ros_context):
    """After 7 readings, buffer retains only the last 5 (FIFO deque maxlen=5)."""
    node = FruitingChamberController()

    for v in [0.80, 0.82, 0.81, 0.99, 0.83, 0.84, 0.85]:
        _send_humidity(node, v)

    # deque(maxlen=5) after all 7 pushes: [0.81, 0.99, 0.83, 0.84, 0.85]
    # sorted: [0.81, 0.83, 0.84, 0.85, 0.99] -> median = 0.84
    assert node.current_humidity == pytest.approx(0.84)

    node.destroy_node()


def test_new_params_declared(ros_context):
    """min_dwell_time (300.0) and sensor_stale_timeout (10.0) are declared parameters."""
    node = FruitingChamberController()
    assert node.get_parameter('min_dwell_time').value == 300.0
    assert node.get_parameter('sensor_stale_timeout').value == 10.0
    node.destroy_node()


def test_none_humidity_safe_state(ros_context):
    """When current_humidity is None and temp is set, control_loop drives humidifier OFF."""
    node = FruitingChamberController()
    node.humidifier_state = True   # simulate humidifier was ON
    node.current_temp = 23.0       # temp is present
    # current_humidity is None (default)
    node.control_loop()
    assert node.humidifier_state == False  # driven OFF, not frozen
    node.destroy_node()


def test_none_temp_safe_state(ros_context):
    """When current_temp is None and humidity is set, control_loop drives humidifier OFF."""
    node = FruitingChamberController()
    node.humidifier_state = True
    _send_humidity(node, 0.80)   # humidity present
    node.current_temp = None     # temp missing
    node.control_loop()
    assert node.humidifier_state == False
    node.destroy_node()