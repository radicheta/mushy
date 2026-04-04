#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Temperature, RelativeHumidity
from std_msgs.msg import Float32
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
                ('scd41_enabled', True),
                ('sensor_read_interval', 2.0),
            ]
        )

        self.sht = None
        self.scd = None

        # Initialize hardware or simulation
        if not self.get_parameter('sensor_simulation_mode').value:
            import board
            i2c = board.I2C()

            # SHT30 (temp + humidity)
            try:
                import adafruit_sht31d
                i2c_addr = self.get_parameter('sht30_i2c_address').value
                self.sht = adafruit_sht31d.SHT31D(i2c, address=i2c_addr)
                self.get_logger().info(f'SHT30 initialized at 0x{i2c_addr:02x}')
            except Exception as e:
                self.get_logger().warn(f'SHT30 not available: {e}')

            # SCD41 (CO2 + temp + humidity)
            if self.get_parameter('scd41_enabled').value:
                try:
                    import adafruit_scd4x
                    self.scd = adafruit_scd4x.SCD4X(i2c)
                    self.scd.start_periodic_measurement()
                    self.get_logger().info('SCD41 initialized at 0x62')
                except Exception as e:
                    self.get_logger().warn(f'SCD41 not available: {e}')
        else:
            self.get_logger().info('Running in simulation mode')
            self.sim_temp = 23.0
            self.sim_humidity = 0.85
            self.sim_co2 = 400.0

        # Create publishers
        self.temp_pub = self.create_publisher(Temperature, 'fc/temperature', 10)
        self.humidity_pub = self.create_publisher(RelativeHumidity, 'fc/humidity', 10)
        self.co2_pub = self.create_publisher(Float32, 'fc/co2', 10)

        self.timer = self.create_timer(
            self.get_parameter('sensor_read_interval').value,
            self.read_sensors
        )

        self.get_logger().info('Fruiting Chamber Sensors Node Started')

    def read_sensors(self):
        try:
            if not self.get_parameter('sensor_simulation_mode').value:
                temperature = None
                humidity = None
                co2 = None

                # Read SHT30 if available
                if self.sht is not None:
                    temperature = self.sht.temperature
                    humidity = self.sht.relative_humidity

                # Read SCD41 if available
                if self.scd is not None and self.scd.data_ready:
                    co2 = self.scd.CO2
                    # Use SCD41 temp/humidity as fallback if no SHT30
                    if temperature is None:
                        temperature = self.scd.temperature
                        humidity = self.scd.relative_humidity
            else:
                self.sim_temp += random.uniform(-0.1, 0.1)
                self.sim_humidity += random.uniform(-0.01, 0.01)
                self.sim_co2 += random.uniform(-5.0, 5.0)
                self.sim_temp = max(15.0, min(30.0, self.sim_temp))
                self.sim_humidity = max(0.5, min(1.0, self.sim_humidity))
                self.sim_co2 = max(300.0, min(2000.0, self.sim_co2))
                temperature = self.sim_temp
                humidity = self.sim_humidity * 100.0
                co2 = self.sim_co2

            # Publish temperature
            if temperature is not None:
                temp_msg = Temperature()
                temp_msg.header.stamp = self.get_clock().now().to_msg()
                temp_msg.temperature = float(temperature)
                self.temp_pub.publish(temp_msg)

            # Publish humidity — RelativeHumidity msg expects 0.0-1.0
            if humidity is not None:
                humidity_msg = RelativeHumidity()
                humidity_msg.header.stamp = self.get_clock().now().to_msg()
                humidity_msg.relative_humidity = float(humidity) / 100.0
                self.humidity_pub.publish(humidity_msg)

            # Publish CO2
            if co2 is not None:
                co2_msg = Float32()
                co2_msg.data = float(co2)
                self.co2_pub.publish(co2_msg)

            parts = []
            if temperature is not None:
                parts.append(f'{temperature:.1f}°C')
            if humidity is not None:
                parts.append(f'{humidity:.1f}%')
            if co2 is not None:
                parts.append(f'{co2:.0f}ppm')
            self.get_logger().info(' | '.join(parts))

        # Non-blocking: log error and skip sample. Next timer tick retries automatically.
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
