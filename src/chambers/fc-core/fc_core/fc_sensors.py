#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Temperature, RelativeHumidity
import time
import random

class FruitingChamberSensors(Node):
    def __init__(self):
        super().__init__('fc_sensors')
        
        # Declare parameters
        self.declare_parameters(
            namespace='',
            parameters=[
                ('sensor_simulation_mode', True),
                ('dht_pin', 4),
                ('sensor_read_interval', 2.0),
            ]
        )

        # Initialize hardware or simulation
        if not self.get_parameter('sensor_simulation_mode').value:
            import adafruit_dht
            import board
            pin_num = self.get_parameter('dht_pin').value
            dht_pin = getattr(board, f'D{pin_num}')
            self.dht = adafruit_dht.DHT22(dht_pin, use_pulseio=False)
        else:
            self.get_logger().info('Running in simulation mode')
            # Simulated values
            self.sim_temp = 23.0
            self.sim_humidity = 0.85
        
        # Create publishers
        self.temp_pub = self.create_publisher(Temperature, 'fc/temperature', 10)
        self.humidity_pub = self.create_publisher(RelativeHumidity, 'fc/humidity', 10)
        
        # Create timer for sensor readings
        self.timer = self.create_timer(
            self.get_parameter('sensor_read_interval').value,
            self.read_sensors
        )
        
        self.get_logger().info('Fruiting Chamber Sensors Node Started')

    def read_sensors(self):
        try:
            if not self.get_parameter('sensor_simulation_mode').value:
                # Read from actual hardware
                temperature = self.dht.temperature
                humidity = self.dht.humidity
            else:
                # Simulate sensor readings with some noise
                self.sim_temp += random.uniform(-0.1, 0.1)
                self.sim_humidity += random.uniform(-0.01, 0.01)
                # Keep values within reasonable ranges
                self.sim_temp = max(15.0, min(30.0, self.sim_temp))
                self.sim_humidity = max(0.5, min(1.0, self.sim_humidity))
                temperature = self.sim_temp
                humidity = self.sim_humidity
            
            # Publish temperature
            temp_msg = Temperature()
            temp_msg.header.stamp = self.get_clock().now().to_msg()
            temp_msg.temperature = float(temperature)
            self.temp_pub.publish(temp_msg)
            
            # Publish humidity
            humidity_msg = RelativeHumidity()
            humidity_msg.header.stamp = self.get_clock().now().to_msg()
            # DHT22 returns 0-100; RelativeHumidity msg expects 0.0-1.0
            if not self.get_parameter('sensor_simulation_mode').value:
                humidity_msg.relative_humidity = float(humidity) / 100.0
            else:
                humidity_msg.relative_humidity = float(humidity)  # sim already 0.0-1.0
            self.humidity_pub.publish(humidity_msg)

            display_humidity = humidity if self.get_parameter('sensor_simulation_mode').value else humidity / 100.0
            self.get_logger().debug(f'Temperature: {temperature}°C, Humidity: {display_humidity*100:.1f}%')
            
        except RuntimeError as e:
            self.get_logger().error(f'Failed to read sensor: {e}')
            time.sleep(2.0)  # Wait before retrying

def main(args=None):
    rclpy.init(args=args)
    node = FruitingChamberSensors()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main() 