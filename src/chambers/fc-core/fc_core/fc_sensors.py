#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Temperature, RelativeHumidity
import random

class FruitingChamberSensors(Node):
    def __init__(self):
        super().__init__('fc_sensors')

        # Declare parameters
        self.declare_parameters(
            namespace='',
            parameters=[
                ('sensor_simulation_mode', True),
                ('sht30_i2c_address', 0x44),
                ('sensor_read_interval', 2.0),
            ]
        )

        # Initialize hardware or simulation
        if not self.get_parameter('sensor_simulation_mode').value:
            import board
            import adafruit_sht31d
            i2c_addr = self.get_parameter('sht30_i2c_address').value
            self.sht = adafruit_sht31d.SHT31D(board.I2C(), address=i2c_addr)
            self.get_logger().info(f'SHT30 initialized at I2C address 0x{i2c_addr:02x}')
        else:
            self.get_logger().info('Running in simulation mode')
            self.sim_temp = 23.0
            self.sim_humidity = 0.85

        # Create publishers
        self.temp_pub = self.create_publisher(Temperature, 'fc/temperature', 10)
        self.humidity_pub = self.create_publisher(RelativeHumidity, 'fc/humidity', 10)

        self.timer = self.create_timer(
            self.get_parameter('sensor_read_interval').value,
            self.read_sensors
        )

        self.get_logger().info('Fruiting Chamber Sensors Node Started')

    def read_sensors(self):
        try:
            if not self.get_parameter('sensor_simulation_mode').value:
                # SHT30 returns temperature in °C and humidity in % (0-100)
                temperature = self.sht.temperature
                humidity = self.sht.relative_humidity
            else:
                self.sim_temp += random.uniform(-0.1, 0.1)
                self.sim_humidity += random.uniform(-0.01, 0.01)
                self.sim_temp = max(15.0, min(30.0, self.sim_temp))
                self.sim_humidity = max(0.5, min(1.0, self.sim_humidity))
                temperature = self.sim_temp
                humidity = self.sim_humidity * 100.0  # normalize to 0-100 for consistent handling

            # Publish temperature
            temp_msg = Temperature()
            temp_msg.header.stamp = self.get_clock().now().to_msg()
            temp_msg.temperature = float(temperature)
            self.temp_pub.publish(temp_msg)

            # Publish humidity — RelativeHumidity msg expects 0.0-1.0
            humidity_msg = RelativeHumidity()
            humidity_msg.header.stamp = self.get_clock().now().to_msg()
            humidity_msg.relative_humidity = float(humidity) / 100.0
            self.humidity_pub.publish(humidity_msg)

            self.get_logger().info(f'Temperature: {temperature:.1f}°C, Humidity: {humidity:.1f}%')

        except Exception as e:
            self.get_logger().error(f'Failed to read sensor: {e}')

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
