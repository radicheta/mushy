#!/usr/bin/env python3
import math
from collections import deque

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool, Float32


class SlowPwmDriver(Node):
    """
    Time-proportional slow-PWM actuator driver for the humidifier relay.

    Subscribes to ``fc1/actuators/humidifier_duty`` (Float32, 0.0-1.0) and
    translates the duty cycle into relay ON/OFF edges within a fixed
    ``pwm_window_seconds`` window.  Publishes relay state changes to
    ``fc1/actuators/humidifier`` (Bool) on edges only.

    Protective rules applied at window-lock time:

    - Min-pulse round-down (D-11): on_sec < min_pulse_seconds -> 0s
    - Rolling 5-min duty cap (D-12): duty averaged over 5-min history <= max_duty_5min_avg
    - Defensive OFF (D-13): if duty topic is silent > duty_topic_timeout_seconds -> force OFF
    """

    def __init__(self):
        super().__init__('fc_pwm_driver')

        # Declare parameters; actuator_simulation_mode defaults True (sim-safe for dev/tests;
        # overridden to False by fc_config.yaml on the Pi)
        self.declare_parameters(
            namespace='',
            parameters=[
                ('humidifier_pin', 27),
                ('pwm_window_seconds', 120.0),
                ('min_pulse_seconds', 10.0),
                ('max_duty_5min_avg', 0.40),
                ('actuator_simulation_mode', True),
                ('duty_topic_timeout_seconds', 5.0),
            ]
        )

        # Sim-mode / hardware branch (mirrors fc_controller.py GPIO ownership block)
        if not self.get_parameter('actuator_simulation_mode').value:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            self.humidifier_pin = self.get_parameter('humidifier_pin').value
            GPIO.setup(self.humidifier_pin, GPIO.OUT)
            GPIO.output(self.humidifier_pin, GPIO.LOW)
            self.GPIO = GPIO
        else:
            self.humidifier_state = False  # sim attribute test_pwm_driver.py reads
            self.get_logger().info('Actuators in simulation mode')

        # TRANSIENT_LOCAL QoS — matches Phase 04 ACTR-03 contract
        actuator_qos = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
        )

        # Subscribe to duty setpoint (TRANSIENT_LOCAL — Pitfall 5: must match publisher)
        self._duty_sub = self.create_subscription(
            Float32,
            'fc1/actuators/humidifier_duty',
            self._duty_callback,
            actuator_qos,
        )

        # Publish relay state (TRANSIENT_LOCAL — preserves Phase 04 ACTR-03 contract)
        self._state_pub = self.create_publisher(
            Bool,
            'fc1/actuators/humidifier',
            actuator_qos,
        )

        # Internal state
        self._latest_duty = 0.0
        self._last_duty_msg_ts = None
        self._window_start_ts = self.get_clock().now()
        self._window_on_seconds = 0.0        # locked at window-start
        # 999.31 fix: deque appends once per window rollover (not per 1Hz tick),
        # so maxlen must scale to pwm_window_seconds to actually cover ≥5 min.
        # Previous `maxlen=300` was a 10-hour window, not 5 min.
        # ceil so coverage is always ≥ 300s (e.g. window=120s → 3 entries = 360s).
        _window_sec = self.get_parameter('pwm_window_seconds').value
        self._duty_history = deque(maxlen=max(1, math.ceil(300.0 / _window_sec)))
        self._current_state = False

        # 1Hz tick
        self._tick_timer = self.create_timer(1.0, self._tick)

    def _duty_callback(self, msg):
        """Receive duty setpoint; clamp to [0, 1] and record timestamp."""
        self._latest_duty = max(0.0, min(1.0, msg.data))
        self._last_duty_msg_ts = self.get_clock().now()

    def _tick(self):
        """1Hz tick: manage window rollover and relay state."""
        now = self.get_clock().now()
        elapsed = (now - self._window_start_ts).nanoseconds / 1e9
        window = self.get_parameter('pwm_window_seconds').value

        # Defensive OFF (D-13): duty topic silent → force relay OFF
        if self._last_duty_msg_ts is None:
            self._set_relay(False)
            return
        silence = (now - self._last_duty_msg_ts).nanoseconds / 1e9
        if silence > self.get_parameter('duty_topic_timeout_seconds').value:
            self._set_relay(False)
            return

        if elapsed >= window:
            # New window: lock in duty with protective rules
            duty = self._latest_duty

            # Rolling 5-min cap (D-12)
            cap = self.get_parameter('max_duty_5min_avg').value
            if self._duty_history:
                n = len(self._duty_history)
                current_sum = sum(self._duty_history)
                # Forecast: would adding this duty window push the running average over cap?
                if (current_sum + duty) / (n + 1) > cap:
                    # Back-solve: max duty so that (current_sum + duty) / (n+1) == cap
                    duty = max(0.0, cap * (n + 1) - current_sum)

            # Clamp duty to [0, 1] after cap adjustment
            duty = max(0.0, min(1.0, duty))

            on_sec = duty * window

            # Min-pulse round-down (D-11): sub-threshold pulses → 0
            min_pulse = self.get_parameter('min_pulse_seconds').value
            if 0.0 < on_sec < min_pulse:
                on_sec = 0.0

            self._window_on_seconds = on_sec
            self._window_start_ts = now
            self._duty_history.append(on_sec / window)
            elapsed = 0.0

        # Within window: relay HIGH for first on_sec, LOW thereafter
        target_state = elapsed < self._window_on_seconds
        self._set_relay(target_state)

    def _set_relay(self, state):
        """Toggle relay and publish on edge only (publish-on-change)."""
        if state == self._current_state:
            return
        if not self.get_parameter('actuator_simulation_mode').value:
            self.GPIO.output(
                self.humidifier_pin,
                self.GPIO.HIGH if state else self.GPIO.LOW
            )
        else:
            self.humidifier_state = state
        self._current_state = state
        msg = Bool()
        msg.data = state
        self._state_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = SlowPwmDriver()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if not node.get_parameter('actuator_simulation_mode').value:
            node.GPIO.cleanup()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
