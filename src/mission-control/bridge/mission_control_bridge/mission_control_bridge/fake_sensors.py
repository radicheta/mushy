#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Temperature, RelativeHumidity
import random
import time

class FakeSensors(Node):
    def __init__(self):
        super().__init__('fake_sensors')
        
        # Create publishers
        self.temp_pub = self.create_publisher(Temperature, 'fc/temperature', 10)
        self.humidity_pub = self.create_publisher(RelativeHumidity, 'fc/humidity', 10)
        
        # Create timer for publishing
        self.timer = self.create_timer(1.0, self.publish_data)
        
        # Initial values
        self.temperature = 23.0  # °C
        self.humidity = 0.85     # 85%
        
        self.get_logger().info('Fake sensors node started')
    
    def publish_data(self):
        # Add some random variation
        self.temperature += random.uniform(-0.5, 0.5)
        self.humidity += random.uniform(-0.02, 0.02)
        
        # Keep values within reasonable ranges
        self.temperature = max(18.0, min(28.0, self.temperature))
        self.humidity = max(0.7, min(0.95, self.humidity))
        
        # Create and publish temperature message
        temp_msg = Temperature()
        temp_msg.temperature = self.temperature
        temp_msg.header.stamp = self.get_clock().now().to_msg()
        self.temp_pub.publish(temp_msg)
        
        # Create and publish humidity message
        humidity_msg = RelativeHumidity()
        humidity_msg.relative_humidity = self.humidity
        humidity_msg.header.stamp = self.get_clock().now().to_msg()
        self.humidity_pub.publish(humidity_msg)
        
        self.get_logger().debug(
            f'Published: Temp={self.temperature:.1f}°C, '
            f'Humidity={self.humidity*100:.1f}%'
        )

def main():
    rclpy.init()
    node = FakeSensors()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main() 