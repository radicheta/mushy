#!/usr/bin/env python3
from typing import Dict, List, Optional

import rclpy
from rclpy.node import Node
from ls_interfaces.msg import EnvironmentData, ActuatorCommands, SystemState

class LifeSupport(Node):
    def __init__(self, system_id: str):
        super().__init__(f'life_support_{system_id}')
        self.system_id = system_id
        
        # Parameters (can be overridden by subclasses)
        self.declare_parameters(
            namespace='',
            parameters=[
                ('temp_setpoint', 20.0),           # Celsius
                ('temp_tolerance', 2.0),           # ±°C from setpoint
                ('humidity_setpoint', 85.0),       # %
                ('humidity_tolerance', 5.0),       # ±% from setpoint
                ('co2_max', 800.0),               # ppm
                ('control_interval', 1.0),         # seconds
            ]
        )

        # Publishers
        self.actuator_pub = self.create_publisher(
            ActuatorCommands, 
            f'{system_id}/actuators/commands', 
            10
        )
        self.state_pub = self.create_publisher(
            SystemState,
            f'{system_id}/state',
            10
        )

        # Subscribers
        self.env_sub = self.create_subscription(
            EnvironmentData,
            f'{system_id}/sensors/environment',
            self.environment_callback,
            10
        )

        # Control loop timer
        self.control_timer = self.create_timer(
            self.get_parameter('control_interval').value,
            self.control_loop
        )

        # State
        self.current_env: Optional[EnvironmentData] = None
        self.active_warnings: List[str] = []
        self.active_errors: List[str] = []

    def environment_callback(self, msg: EnvironmentData) -> None:
        """Handle new environmental sensor data"""
        self.current_env = msg
        self.check_warnings()

    def control_loop(self) -> None:
        """Main control loop - can be overridden by subclasses"""
        if not self.current_env:
            return

        commands = ActuatorCommands()
        commands.header.stamp = self.get_clock().now().to_msg()
        
        # Temperature control
        temp_setpoint = self.get_parameter('temp_setpoint').value
        temp_tolerance = self.get_parameter('temp_tolerance').value
        
        if self.current_env.temperature > temp_setpoint + temp_tolerance:
            commands.cooler_active = True
        elif self.current_env.temperature < temp_setpoint - temp_tolerance:
            commands.heater_active = True

        # Humidity control
        humidity_setpoint = self.get_parameter('humidity_setpoint').value
        humidity_tolerance = self.get_parameter('humidity_tolerance').value
        
        if self.current_env.humidity < humidity_setpoint - humidity_tolerance:
            commands.humidifier_active = True
        
        # CO2 control
        if self.current_env.co2_ppm > self.get_parameter('co2_max').value:
            commands.vent_active = True

        self.actuator_pub.publish(commands)
        self.publish_state()

    def check_warnings(self) -> None:
        """Check for warning conditions"""
        self.active_warnings.clear()
        
        if not self.current_env:
            self.active_warnings.append("No environmental data")
            return

        # Add your warning checks here
        if self.current_env.co2_ppm > self.get_parameter('co2_max').value:
            self.active_warnings.append("CO2 levels above maximum")

    def publish_state(self) -> None:
        """Publish current system state"""
        state = SystemState()
        state.header.stamp = self.get_clock().now().to_msg()
        state.system_id = self.system_id
        state.mode = "NORMAL"  # Can be updated based on conditions
        state.online = True
        state.active_warnings = self.active_warnings
        state.active_errors = self.active_errors
        self.state_pub.publish(state)