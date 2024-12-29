#!/usr/bin/env python3
from typing import Dict, List, Optional

import rclpy
from rclpy.parameter import Parameter
from ls_core.core.life_support import LifeSupport
from ls_interfaces.msg import EnvironmentData, ActuatorCommands, SystemState

class Incubator(LifeSupport):
    def __init__(self, system_id: str):
        super().__init__(system_id)
        
        # Update parameters for incubator-specific values
        self.set_parameters([
            Parameter('temp_setpoint', value=25.0),     # Higher default temp for incubation
            Parameter('temp_tolerance', value=1.0)      # Tighter temperature control
        ])

    # ... rest of the class remains the same ...
    def control_loop(self) -> None:
        """
        Override control loop to focus only on temperature management.
        Humidity and CO2 control are intentionally disabled for incubators.
        """
        if not self.current_env:
            return

        commands = ActuatorCommands()
        commands.header.stamp = self.get_clock().now().to_msg()
        
        # Temperature control with tighter bounds
        temp_setpoint = self.get_parameter('temp_setpoint').value
        temp_tolerance = self.get_parameter('temp_tolerance').value
        
        if self.current_env.temperature > temp_setpoint + temp_tolerance:
            commands.cooler_active = True
            commands.heater_active = False
        elif self.current_env.temperature < temp_setpoint - temp_tolerance:
            commands.heater_active = True
            commands.cooler_active = False
        else:
            commands.heater_active = False
            commands.cooler_active = False

        # Explicitly disable other controls
        commands.humidifier_active = False
        commands.vent_active = False

        self.actuator_pub.publish(commands)
        self.publish_state()

    def check_warnings(self) -> None:
        """Override warning checks to focus on temperature-related issues"""
        self.active_warnings.clear()
        
        if not self.current_env:
            self.active_warnings.append("No environmental data")
            return

        temp_setpoint = self.get_parameter('temp_setpoint').value
        
        # More specific temperature warnings for incubation
        if abs(self.current_env.temperature - temp_setpoint) > 3.0:
            self.active_warnings.append(
                f"Temperature significantly out of range: {self.current_env.temperature:.1f}°C"
            )

def main(args=None):
    rclpy.init(args=args)
    node = Incubator('ic1')  # You might want to make this configurable
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()