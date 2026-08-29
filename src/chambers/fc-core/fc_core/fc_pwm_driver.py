#!/usr/bin/env python3
import math
from collections import deque

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool, Float32


class SlowPwmDriver(Node):
    """
    Sigma-delta (pulse-frequency) actuator driver for the humidifier relay.

    Subscribes to ``fc1/actuators/humidifier_duty`` (Float32, 0.0-1.0) and
    integrates it every tick into a bank of demand-seconds. Publishes relay
    state changes to ``fc1/actuators/humidifier`` (Bool) on edges only.

        bank += duty * dt                                every tick
        OFF -> ON  when bank >= min_pulse_seconds        one legal pulse accrued
        ON:  bank -= dt;  OFF when bank <= min_pulse - H(duty)
        H(d) = max(min_pulse_seconds, pwm_window_seconds * d * (1 - d))

    The bank swings across a band of width H, so in steady state this IS the
    old ``pwm_window_seconds`` time-proportional window (same pulse length,
    period, edges/day and ripple) and, below the floor, the MUSHY-116 bank.
    The difference is phase: the window sampled duty once per window and
    ignored it for the rest (up to 8 min of deafness at 480s -- MUSHY-129),
    whereas here a pulse fires as soon as ``min_pulse`` of demand exists and
    the rest of the pulse is spent as debt the OFF leg repays. The OFF
    threshold tracks CURRENT demand, so a demand collapse ends a pulse at
    the floor instead of running out a stale commitment.

    Protective rules:

    - Min pulse (D-11): no pulse shorter than min_pulse_seconds, ever.
    - Duty cap (D-12): ON-seconds in the trailing cap_horizon_seconds
      <= max_duty_5min_avg * cap_horizon_seconds, checked at fire and mid-pulse.
    - Defensive OFF (D-13): duty topic silent > duty_topic_timeout_seconds -> OFF.
    """

    def __init__(self):
        super().__init__('fc_pwm_driver')

        # Declare parameters; actuator_simulation_mode defaults True (sim-safe for dev/tests;
        # overridden to False by fc_config.yaml on the Pi)
        self.declare_parameters(
            namespace='',
            parameters=[
                ('humidifier_pin', 27),
                ('pwm_window_seconds', 120.0),     # steady-state period T
                ('min_pulse_seconds', 10.0),
                ('max_duty_5min_avg', 0.40),
                ('cap_horizon_seconds', 300.0),
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
        self._last_tick_ts = None
        self._bank_s = 0.0
        # D-12: one entry per tick (seconds ON), running sum kept alongside.
        horizon = self.get_parameter('cap_horizon_seconds').value
        self._on_history = deque(maxlen=max(1, math.ceil(horizon)))
        self._on_sum = 0.0
        self._current_state = False

        # 1Hz tick
        self._tick_timer = self.create_timer(1.0, self._tick)

    def _duty_callback(self, msg):
        """Receive duty setpoint; clamp to [0, 1] and record timestamp."""
        self._latest_duty = max(0.0, min(1.0, msg.data))
        self._last_duty_msg_ts = self.get_clock().now()

    def _hysteresis(self, duty):
        window = self.get_parameter('pwm_window_seconds').value
        return max(self.get_parameter('min_pulse_seconds').value, window * duty * (1.0 - duty))

    def _cap_allows(self, extra_s):
        cap = self.get_parameter('max_duty_5min_avg').value
        horizon = self.get_parameter('cap_horizon_seconds').value
        return self._on_sum + extra_s <= cap * horizon

    def _record_on(self, on_s):
        if len(self._on_history) == self._on_history.maxlen:
            self._on_sum -= self._on_history[0]
        self._on_history.append(on_s)
        self._on_sum += on_s

    def _tick(self):
        """1Hz tick: integrate demand, drive the relay."""
        now = self.get_clock().now()
        dt = 1.0
        if self._last_tick_ts is not None:
            # A stalled timer must not bank minutes of demand in one go.
            dt = max(0.0, min(5.0, (now - self._last_tick_ts).nanoseconds / 1e9))
        self._last_tick_ts = now

        # Defensive OFF (D-13): duty topic silent → force relay OFF
        if self._last_duty_msg_ts is None:
            self._set_relay(False)
            return
        silence = (now - self._last_duty_msg_ts).nanoseconds / 1e9
        if silence > self.get_parameter('duty_topic_timeout_seconds').value:
            self._set_relay(False)
            return

        duty = self._latest_duty
        min_pulse = self.get_parameter('min_pulse_seconds').value
        window = self.get_parameter('pwm_window_seconds').value

        # Anti-windup: a bank held back by the cap must not become minutes of
        # over-delivery once demand drops. Ceiling = largest swing (T/4 at d=0.5).
        self._bank_s = min(self._bank_s + duty * dt, max(min_pulse, window / 4.0))

        if not self._current_state:
            if self._bank_s >= min_pulse and self._cap_allows(min_pulse):
                self._set_relay(True)
        else:
            self._bank_s -= dt
            off_at = min_pulse - self._hysteresis(duty)
            if self._bank_s <= off_at or not self._cap_allows(dt):
                self._bank_s = max(self._bank_s, off_at)
                self._set_relay(False)

        self._record_on(dt if self._current_state else 0.0)

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
