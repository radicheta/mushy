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

        # Slot-1 publishers (SHT30 preferred, SCD41 silent fallback — D-01)
        self.temp_pub = self.create_publisher(Temperature, 'fc1/temperature', 10)
        self.humidity_pub = self.create_publisher(RelativeHumidity, 'fc1/humidity', 10)
        self.co2_pub = self.create_publisher(Float32, 'fc1/co2', 10)

        # Phase 26 D-02: slot-2 SCD41-only publishers (always 'scd41' provenance)
        self.temp_2_pub = self.create_publisher(Temperature, 'fc1/temperature_2', 10)
        self.humidity_2_pub = self.create_publisher(RelativeHumidity, 'fc1/humidity_2', 10)

        # Phase 26 D-03: per-physical-sensor last-successful-read timestamps (ROS time, ns)
        self._sht30_last_read_ns = None
        self._scd41_last_read_ns = None

        self.timer = self.create_timer(
            self.get_parameter('sensor_read_interval').value,
            self.read_sensors
        )

        self.get_logger().info('Fruiting Chamber Sensors Node Started')

    def read_sensors(self):
        if not self.get_parameter('sensor_simulation_mode').value:
            sht30_t = sht30_rh = None
            scd41_t = scd41_rh = scd41_co2 = None
            now = self.get_clock().now()

            # SHT30 — own try/except so a failure does not skip SCD41 (Pitfall 1)
            if self.sht is not None:
                try:
                    sht30_t = self.sht.temperature
                    sht30_rh = self.sht.relative_humidity
                    self._sht30_last_read_ns = now.nanoseconds
                except Exception as e:
                    self.get_logger().warn(f'SHT30 read failed: {e}')

            # SCD41 — own try/except + data_ready gate
            if self.scd is not None:
                try:
                    if self.scd.data_ready:
                        scd41_t = self.scd.temperature
                        scd41_rh = self.scd.relative_humidity
                        scd41_co2 = self.scd.CO2
                        self._scd41_last_read_ns = now.nanoseconds
                except Exception as e:
                    self.get_logger().warn(f'SCD41 read failed: {e}')

            # Slot 1 silent fallback (D-01) — per-channel because either reading
            # can be absent independently (e.g. SHT30 raises mid-read on temperature).
            slot1_t = sht30_t if sht30_t is not None else scd41_t
            slot1_t_src = 'sht30' if sht30_t is not None else 'scd41'
            slot1_rh = sht30_rh if sht30_rh is not None else scd41_rh
            slot1_rh_src = 'sht30' if sht30_rh is not None else 'scd41'
            co2 = scd41_co2

            # Slot 2 (D-02 / D-03) — SCD41-only, gap when stale, frame_id always 'scd41'
            slot2_t = scd41_t
            slot2_rh = scd41_rh
        else:
            # Simulation: jitter slot-1 base values; slot 2 ≠ slot 1 to mimic
            # the real-world disagreement we expect (Pitfall 6).
            self.sim_temp += random.uniform(-0.1, 0.1)
            self.sim_humidity += random.uniform(-0.01, 0.01)
            self.sim_co2 += random.uniform(-5.0, 5.0)
            self.sim_temp = max(15.0, min(30.0, self.sim_temp))
            self.sim_humidity = max(0.5, min(1.0, self.sim_humidity))
            self.sim_co2 = max(300.0, min(2000.0, self.sim_co2))
            slot1_t = self.sim_temp
            slot1_t_src = 'sht30'           # sim mode pretends SHT30 is alive
            slot1_rh = self.sim_humidity * 100.0
            slot1_rh_src = 'sht30'
            co2 = self.sim_co2
            # Slot 2 sim values: small constant offset + independent jitter
            slot2_t = self.sim_temp + 0.3 + random.uniform(-0.05, 0.05)
            slot2_rh = (self.sim_humidity * 100.0) + 1.5 + random.uniform(-0.1, 0.1)
            # In sim, both physical sensors are alive each tick:
            now = self.get_clock().now()
            self._sht30_last_read_ns = now.nanoseconds
            self._scd41_last_read_ns = now.nanoseconds

        # Publish helpers — D-03: skip when None. Each helper writes frame_id.
        self._publish_temp(self.temp_pub, slot1_t, slot1_t_src)
        self._publish_humidity(self.humidity_pub, slot1_rh, slot1_rh_src)
        self._publish_temp(self.temp_2_pub, slot2_t, 'scd41')
        self._publish_humidity(self.humidity_2_pub, slot2_rh, 'scd41')
        if co2 is not None:
            co2_msg = Float32()
            co2_msg.data = float(co2)
            self.co2_pub.publish(co2_msg)

        # Operator-visible journal line (preserve existing format)
        parts = []
        if slot1_t is not None:
            parts.append(f'{slot1_t:.1f}°C')
        if slot1_rh is not None:
            parts.append(f'{slot1_rh:.1f}%')
        if co2 is not None:
            parts.append(f'{co2:.0f}ppm')
        if parts:
            self.get_logger().info(' | '.join(parts))

    def _publish_temp(self, pub, value, source):
        if value is None:
            return
        msg = Temperature()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = source        # 'sht30' or 'scd41'
        msg.temperature = float(value)
        pub.publish(msg)

    def _publish_humidity(self, pub, value_pct, source):
        if value_pct is None:
            return
        msg = RelativeHumidity()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = source        # 'sht30' or 'scd41'
        msg.relative_humidity = float(value_pct) / 100.0
        pub.publish(msg)


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
