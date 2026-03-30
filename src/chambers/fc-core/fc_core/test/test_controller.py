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