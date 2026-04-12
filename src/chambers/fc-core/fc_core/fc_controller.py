#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import Temperature, RelativeHumidity
from std_msgs.msg import Bool
import time
from collections import deque
from datetime import datetime
from statistics import median

class FruitingChamberController(Node):
    def __init__(self):
        super().__init__('fc_controller')
        
        # Declare parameters
        self.declare_parameters(
            namespace='',
            parameters=[
                ('actuator_simulation_mode', True),
                ('dht_pin', 4),
                ('humidifier_pin', 17),
                ('light_pin', 18),
                ('target_temp', 23.0),
                ('target_humidity', 0.85),
                ('target_light_hours', 12),
                ('light_start_hour', 6),
                ('temp_tolerance', 1.0),
                ('humidity_tolerance', 0.05),
                ('min_fan_speed', 50),
                ('fan_temp_scale', 20),
                ('fan_pwm_channel', 0),
                ('fan_pwm_freq', 25000),
                ('control_interval', 1.0),
                ('min_dwell_time', 300.0),
                ('sensor_stale_timeout', 10.0),
            ]
        )
        
        # Initialize hardware or simulation
        if not self.get_parameter('actuator_simulation_mode').value:
            import RPi.GPIO as GPIO

            # GPIO Setup
            GPIO.setmode(GPIO.BCM)

            # Fan control (PWM) — optional, skip if no hardware PWM library
            self.fan_pwm = None
            try:
                import rpi_hardware_pwm as hw_pwm
                self.fan_pwm = hw_pwm.HardwarePWM(
                    pwm_channel=self.get_parameter('fan_pwm_channel').value,
                    hz=self.get_parameter('fan_pwm_freq').value
                )
                self.fan_pwm.start(0)
                self.get_logger().info('Hardware PWM fan initialized')
            except Exception as e:
                self.get_logger().warn(f'Hardware PWM not available, fan disabled: {e}')

            # Humidifier control (GPIO)
            self.humidifier_pin = self.get_parameter('humidifier_pin').value
            GPIO.setup(self.humidifier_pin, GPIO.OUT)
            GPIO.output(self.humidifier_pin, GPIO.LOW)

            # Light control (GPIO)
            self.light_pin = self.get_parameter('light_pin').value
            GPIO.setup(self.light_pin, GPIO.OUT)
            GPIO.output(self.light_pin, GPIO.LOW)

            self.GPIO = GPIO
        else:
            # Simulation mode
            self.fan_speed = 0
            self.humidifier_state = False
            self.light_state = False
            self.get_logger().info('Actuators in simulation mode')
        
        # Create subscribers
        self.temp_sub = self.create_subscription(
            Temperature,
            'fc1/temperature',
            self.temperature_callback,
            10)
        self.humidity_sub = self.create_subscription(
            RelativeHumidity,
            'fc1/humidity',
            self.humidity_callback,
            10)

        # Actuator state publisher — TRANSIENT_LOCAL so late-joiners get last value (D-01, ACTR-03)
        actuator_qos = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
        )
        self.humidifier_state_pub = self.create_publisher(
            Bool, 'fc1/actuators/humidifier', actuator_qos
        )

        # Current values
        self.current_temp = None
        self.current_humidity = None
        self._humidity_buffer = deque(maxlen=5)
        self._last_humidity_timestamp = None   # rclpy.time.Time, set in humidity_callback
        self._last_humidifier_toggle = None    # rclpy.time.Time, set on state change
        self._safe_state_active = False        # log deduplication flag
        self._dwell_blocked_desired = None     # dedupe DWELL-BLOCK logs per blocked window
        
        # Control timer
        self.timer = self.create_timer(
            self.get_parameter('control_interval').value,
            self.control_loop
        )
        
        self.get_logger().info('Fruiting Chamber Controller Node Started')

    def temperature_callback(self, msg):
        self.current_temp = msg.temperature

    def humidity_callback(self, msg):
        self._humidity_buffer.append(msg.relative_humidity)
        self.current_humidity = median(self._humidity_buffer)
        self._last_humidity_timestamp = self.get_clock().now()

    def should_light_be_on(self):
        current_hour = datetime.now().hour
        start_hour = self.get_parameter('light_start_hour').value
        light_hours = self.get_parameter('target_light_hours').value
        
        # Calculate end hour
        end_hour = (start_hour + light_hours) % 24
        
        if start_hour <= end_hour:
            return start_hour <= current_hour < end_hour
        else:
            # Handle case where light period crosses midnight
            return current_hour >= start_hour or current_hour < end_hour

    def set_fan_speed(self, speed):
        if not self.get_parameter('actuator_simulation_mode').value:
            if self.fan_pwm is not None:
                self.fan_pwm.change_duty_cycle(speed)
        else:
            self.fan_speed = speed

    def set_humidifier(self, state):
        if not self.get_parameter('actuator_simulation_mode').value:
            self.GPIO.output(self.humidifier_pin, self.GPIO.HIGH if state else self.GPIO.LOW)
        else:
            self.humidifier_state = state

    def _set_humidifier_with_dwell(self, state):
        """Set humidifier state, gated by minimum dwell time (D-05, D-06).

        Only used by bang-bang control. Safe-state calls bypass this
        and call set_humidifier() directly.
        """
        current_state = self.get_humidifier_state()
        if state == current_state:
            self._dwell_blocked_desired = None
            return  # no transition needed
        if self._last_humidifier_toggle is not None:
            min_dwell = self.get_parameter('min_dwell_time').value
            elapsed_sec = (
                self.get_clock().now() - self._last_humidifier_toggle
            ).nanoseconds / 1e9
            if elapsed_sec < min_dwell:
                if self._dwell_blocked_desired != state:
                    remaining = min_dwell - elapsed_sec
                    self.get_logger().info(
                        f'DWELL-BLOCK: humidifier {"ON" if current_state else "OFF"}->'
                        f'{"ON" if state else "OFF"} delayed by dwell '
                        f'(elapsed {elapsed_sec:.1f}s < {min_dwell:.0f}s, '
                        f'{remaining:.1f}s remaining) | RH={self.current_humidity * 100:.2f}%'
                    )
                    self._dwell_blocked_desired = state
                return
        self.set_humidifier(state)
        self._last_humidifier_toggle = self.get_clock().now()
        self._dwell_blocked_desired = None

    def set_light(self, state):
        if not self.get_parameter('actuator_simulation_mode').value:
            self.GPIO.output(self.light_pin, self.GPIO.HIGH if state else self.GPIO.LOW)
        else:
            self.light_state = state

    def get_fan_speed(self):
        if not self.get_parameter('actuator_simulation_mode').value:
            if self.fan_pwm is not None:
                return self.fan_pwm.get_duty_cycle()
            return 0
        return self.fan_speed

    def get_humidifier_state(self):
        if not self.get_parameter('actuator_simulation_mode').value:
            return self.GPIO.input(self.humidifier_pin) == self.GPIO.HIGH
        return self.humidifier_state

    def get_light_state(self):
        if not self.get_parameter('actuator_simulation_mode').value:
            return self.GPIO.input(self.light_pin) == self.GPIO.HIGH
        return self.light_state

    def control_loop(self):
        if self.current_temp is None or self.current_humidity is None:
            self.set_humidifier(False)
            return

        # Staleness guard (D-09): check if humidity data is too old
        stale = False
        if self._last_humidity_timestamp is not None:
            elapsed_sec = (
                self.get_clock().now() - self._last_humidity_timestamp
            ).nanoseconds / 1e9
            stale = elapsed_sec > self.get_parameter('sensor_stale_timeout').value

        # Temperature control (fan speed) — runs regardless of staleness (D-13)
        temp_diff = self.current_temp - self.get_parameter('target_temp').value
        if abs(temp_diff) > self.get_parameter('temp_tolerance').value:
            # Adjust fan speed based on temperature difference
            fan_speed = min(100, max(
                self.get_parameter('min_fan_speed').value,
                self.get_parameter('min_fan_speed').value + (temp_diff * self.get_parameter('fan_temp_scale').value)
            ))
            self.set_fan_speed(fan_speed)
        else:
            self.set_fan_speed(self.get_parameter('min_fan_speed').value)

        if stale:
            # Safe state: drive humidifier OFF, log on transition only (D-10, D-11)
            if not self._safe_state_active:
                self._safe_state_active = True
                self.get_logger().warn(
                    'Sensor data stale — humidifier OFF for safety'
                )
            self.set_humidifier(False)
            self._last_humidifier_toggle = self.get_clock().now()
        else:
            # Recovery: log on transition back to fresh data (D-11)
            if self._safe_state_active:
                self._safe_state_active = False
                self.get_logger().info('Fresh sensor data received — resuming control')

            # Humidity control (humidifier) — routed through dwell guard
            if self.current_humidity < (self.get_parameter('target_humidity').value - self.get_parameter('humidity_tolerance').value):
                self._set_humidifier_with_dwell(True)
            elif self.current_humidity > (self.get_parameter('target_humidity').value + self.get_parameter('humidity_tolerance').value):
                self._set_humidifier_with_dwell(False)

        # Light control — runs regardless of staleness (D-13)
        self.set_light(self.should_light_be_on())

        # Publish actuator state every tick (ACTR-03)
        state_msg = Bool()
        state_msg.data = self.get_humidifier_state()
        self.humidifier_state_pub.publish(state_msg)

        self.get_logger().debug(
            f'Temp: {self.current_temp:.1f}°C, '
            f'Humidity: {self.current_humidity*100:.1f}%, '
            f'Fan: {self.get_fan_speed():.1f}%, '
            f'Humidifier: {"ON" if self.get_humidifier_state() else "OFF"}, '
            f'Light: {"ON" if self.get_light_state() else "OFF"}'
        )

def main(args=None):
    rclpy.init(args=args)
    node = FruitingChamberController()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if not node.get_parameter('actuator_simulation_mode').value:
            if node.fan_pwm is not None:
                node.fan_pwm.stop()
            node.GPIO.cleanup()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main() 