#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Temperature, RelativeHumidity
import time
from datetime import datetime

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
            ]
        )
        
        # Initialize hardware or simulation
        if not self.get_parameter('actuator_simulation_mode').value:
            import RPi.GPIO as GPIO
            import rpi_hardware_pwm as hw_pwm
            
            # GPIO Setup
            GPIO.setmode(GPIO.BCM)
            
            # Fan control (PWM)
            self.fan_pwm = hw_pwm.HardwarePWM(
                pwm_channel=self.get_parameter('fan_pwm_channel').value,
                hz=self.get_parameter('fan_pwm_freq').value
            )
            self.fan_pwm.start(0)
            
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
        
        # Control timer
        self.timer = self.create_timer(
            self.get_parameter('control_interval').value,
            self.control_loop
        )
        
        self.get_logger().info('Fruiting Chamber Controller Node Started')

    def temperature_callback(self, msg):
        self.current_temp = msg.temperature

    def humidity_callback(self, msg):
        self.current_humidity = msg.relative_humidity

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
            self.fan_pwm.change_duty_cycle(speed)
        else:
            self.fan_speed = speed

    def set_humidifier(self, state):
        if not self.get_parameter('actuator_simulation_mode').value:
            self.GPIO.output(self.humidifier_pin, self.GPIO.HIGH if state else self.GPIO.LOW)
        else:
            self.humidifier_state = state

    def set_light(self, state):
        if not self.get_parameter('actuator_simulation_mode').value:
            self.GPIO.output(self.light_pin, self.GPIO.HIGH if state else self.GPIO.LOW)
        else:
            self.light_state = state

    def get_fan_speed(self):
        if not self.get_parameter('actuator_simulation_mode').value:
            return self.fan_pwm.get_duty_cycle()
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
            return
            
        # Temperature control (fan speed)
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
            
        # Humidity control (humidifier)
        if self.current_humidity < (self.get_parameter('target_humidity').value - self.get_parameter('humidity_tolerance').value):
            self.set_humidifier(True)
        elif self.current_humidity > (self.get_parameter('target_humidity').value + self.get_parameter('humidity_tolerance').value):
            self.set_humidifier(False)
            
        # Light control
        self.set_light(self.should_light_be_on())
            
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
        if not node.get_parameter('simulation_mode').value:
            # Cleanup hardware
            node.fan_pwm.stop()
            node.GPIO.cleanup()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main() 