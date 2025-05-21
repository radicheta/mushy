#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Temperature, RelativeHumidity
import time

class FruitingChamberDisplay(Node):
    def __init__(self):
        super().__init__('fc_display')
        
        # Create subscribers
        self.temp_sub = self.create_subscription(
            Temperature,
            'fc/temperature',
            self.temperature_callback,
            10)
        self.humidity_sub = self.create_subscription(
            RelativeHumidity,
            'fc/humidity',
            self.humidity_callback,
            10)
        
        # Current values
        self.current_temp = None
        self.current_humidity = None
        
        # Display update timer
        self.timer = self.create_timer(1.0, self.update_display)
        
        self.get_logger().info('Fruiting Chamber Display Node Started')

    def temperature_callback(self, msg):
        self.current_temp = msg.temperature

    def humidity_callback(self, msg):
        self.current_humidity = msg.relative_humidity

    def update_display(self):
        if self.current_temp is not None and self.current_humidity is not None:
            self.get_logger().info(
                f'Chamber Status:\n'
                f'  Temperature: {self.current_temp:.1f}°C\n'
                f'  Humidity: {self.current_humidity*100:.1f}%'
            )

def main(args=None):
    rclpy.init(args=args)
    node = FruitingChamberDisplay()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main() 