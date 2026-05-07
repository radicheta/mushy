#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import Temperature, RelativeHumidity
from std_msgs.msg import Float32
from collections import deque
from dataclasses import dataclass
from diagnostic_msgs.msg import DiagnosticStatus, KeyValue
from datetime import datetime
from math import isnan, nan
from statistics import median
from fc_core.vendor.simple_pid import PID


@dataclass
class ModeView:
    """Phase 28 D-08: snapshot of the active mode resolved once per control tick.

    `t_target` is NaN when unset (D-02 — reserved for VPD-anchoring in Phase 31+).
    """
    name: str
    target: float
    band_low: float
    band_high: float
    defend_side: str   # 'low' | 'high' | 'both'
    t_target: float    # NaN when unset


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
                ('target_humidity', 0.94),
                ('target_light_hours', 12),
                ('light_start_hour', 6),
                ('temp_tolerance', 1.0),
                ('humidity_tolerance', 0.05),
                ('min_fan_speed', 50),
                ('fan_temp_scale', 20),
                ('fan_pwm_channel', 0),
                ('fan_pwm_freq', 25000),
                ('control_interval', 1.0),
                ('sensor_stale_timeout', 10.0),
                ('startup_grace_period', 20.0),
                ('pid_kp', 0.5),
                ('pid_ki', 0.002),
                ('pid_kd', 4.0),
                ('pid_derivative_filter_tau', 10.0),
                ('pid_setpoint_ramp_seconds', 30.0),
                ('bypass_threshold', 0.025),
            ]
        )

        # Phase 28 D-03 + D-04: declare mode params. Defaults are placeholders —
        # real values come from fc_config.yaml's fc_controller scope. NaN sentinels
        # on band_low/band_high trigger the D-04 back-compat path in
        # _resolve_active_mode (synthesize fruiting from target_humidity +
        # humidity_tolerance) when the modes block is absent. Strict declaration
        # is preserved (Pitfall 7) — adding new named modes (incubation etc.) is
        # a deploy per D-03; both fruiting and pinning are declared here.
        self.declare_parameters(
            namespace='',
            parameters=[
                ('active_mode', 'fruiting'),
                ('modes.fruiting.target_humidity', 0.94),
                ('modes.fruiting.band_low', float('nan')),
                ('modes.fruiting.band_high', float('nan')),
                ('modes.fruiting.defend_side', 'both'),
                ('modes.fruiting.t_target', float('nan')),
                ('modes.pinning.target_humidity', 0.85),
                ('modes.pinning.band_low', float('nan')),
                ('modes.pinning.band_high', float('nan')),
                ('modes.pinning.defend_side', 'low'),
                ('modes.pinning.t_target', float('nan')),
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

            # Light control (GPIO)
            self.light_pin = self.get_parameter('light_pin').value
            GPIO.setup(self.light_pin, GPIO.OUT)
            GPIO.output(self.light_pin, GPIO.LOW)

            self.GPIO = GPIO
        else:
            # Simulation mode
            self.fan_speed = 0
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
        # Phase 26 D-02: slot-2 subscribers — SCD41-only, used only for
        # per-physical-sensor freshness in sensor_health (not control).
        self.temp2_sub = self.create_subscription(
            Temperature,
            'fc1/temperature_2',
            self.temperature_2_callback,
            10)
        self.humidity2_sub = self.create_subscription(
            RelativeHumidity,
            'fc1/humidity_2',
            self.humidity_2_callback,
            10)

        # Actuator QoS — TRANSIENT_LOCAL so late-joiners get last value (D-01, ACTR-03)
        actuator_qos = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
        )

        # Phase 27: duty-cycle publisher — fc_pwm_driver subscribes to this (HUMID-01)
        self._duty_pub = self.create_publisher(
            Float32, 'fc1/actuators/humidifier_duty', actuator_qos
        )

        # Phase 27 telemetry: current effective setpoint (post-ramp) and raw PID output
        self._humidity_target_pub = self.create_publisher(
            Float32, 'fc1/control/humidity_target', actuator_qos
        )
        self._pid_output_pub = self.create_publisher(
            Float32, 'fc1/control/pid_output', actuator_qos
        )

        # Sensor health publisher — TRANSIENT_LOCAL so late-joiners get last state
        # (SENS-01, WARMUP-02)
        self.sensor_health_pub = self.create_publisher(
            DiagnosticStatus, 'fc1/sensor_health', actuator_qos
        )

        # Current values
        self.current_temp = None
        self.current_humidity = None
        self._humidity_buffer = deque(maxlen=5)
        self._last_humidity_timestamp = None   # rclpy.time.Time, set in humidity_callback
        self._safe_state_active = False        # log deduplication flag

        # Phase 26: per-physical-sensor freshness tracking
        self._last_sht30_timestamp = None       # set when slot-1 carries frame_id=='sht30'
        self._last_temp2_timestamp = None       # set by temperature_2_callback (always SCD41)
        self._last_humidity2_timestamp = None   # set by humidity_2_callback (always SCD41)
        self._last_sht30_fresh = None           # tri-state; None means "not yet evaluated"
        self._last_scd41_fresh = None

        # Startup grace state (SENS-01, WARMUP-01/02/03)
        self._boot_time = self.get_clock().now()
        self._warming_up = True
        self._warmup_signal_published = False

        # Phase 27: PID state init (HUMID-01, HUMID-03)
        self._pid = PID(
            Kp=self.get_parameter('pid_kp').value,
            Ki=self.get_parameter('pid_ki').value,
            Kd=self.get_parameter('pid_kd').value,
            setpoint=0.0,                       # error-form: setpoint=0, input=error
            sample_time=None,                   # driven manually via dt (Pitfall 6)
            output_limits=(0.0, 1.0),
            auto_mode=False,                    # start disengaged; engage after grace
            proportional_on_measurement=False,
            differential_on_measurement=True,   # avoid derivative kick on setpoint change
        )
        self._pid_engaged = False
        self._effective_setpoint = self.get_parameter('target_humidity').value
        self._last_tick_ts = None

        # Control timer
        self.timer = self.create_timer(
            self.get_parameter('control_interval').value,
            self.control_loop
        )

        self.get_logger().info('Fruiting Chamber Controller Node Started')

    def temperature_callback(self, msg):
        self.current_temp = msg.temperature
        # Phase 26: SHT30 freshness via frame_id provenance set by fc_sensors.
        if msg.header.frame_id == 'sht30':
            self._last_sht30_timestamp = self.get_clock().now()

    def humidity_callback(self, msg):
        self._humidity_buffer.append(msg.relative_humidity)
        self.current_humidity = median(self._humidity_buffer)
        self._last_humidity_timestamp = self.get_clock().now()
        # Phase 26: SHT30 freshness via frame_id provenance set by fc_sensors.
        if msg.header.frame_id == 'sht30':
            self._last_sht30_timestamp = self.get_clock().now()

    def temperature_2_callback(self, msg):
        # Slot-2 is SCD41-only by Plan 26-01 contract; arrival proves SCD41 alive.
        self._last_temp2_timestamp = self.get_clock().now()

    def humidity_2_callback(self, msg):
        # Slot-2 is SCD41-only by Plan 26-01 contract; arrival proves SCD41 alive.
        self._last_humidity2_timestamp = self.get_clock().now()

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

    def get_light_state(self):
        if not self.get_parameter('actuator_simulation_mode').value:
            return self.GPIO.input(self.light_pin) == self.GPIO.HIGH
        return self.light_state

    def _grace_active(self) -> bool:
        """True while startup grace is in effect.

        Grace holds until BOTH:
          (a) _humidity_buffer is full (maxlen samples received), AND
          (b) startup_grace_period seconds elapsed since __init__.
        Either unmet -> grace active -> no actuation.
        """
        if len(self._humidity_buffer) < self._humidity_buffer.maxlen:
            return True
        elapsed = (
            self.get_clock().now() - self._boot_time
        ).nanoseconds / 1e9
        if elapsed < self.get_parameter('startup_grace_period').value:
            return True
        return False

    def _declared_mode_names(self) -> set:
        """Phase 28 D-08 helper: introspect declared params for 'modes.<name>.*'.

        Uses the public `get_parameters_by_prefix('modes.')` API rather than
        underscore-prefixed `_parameters`. Returns the set of <name> tokens
        that have at least one declared field under their namespace.
        """
        names = set()
        for full in self.get_parameters_by_prefix('modes.').keys():
            # 'modes.fruiting.band_low'.split('.') -> ['modes','fruiting','band_low']
            # but get_parameters_by_prefix strips the prefix, so we receive
            # 'fruiting.band_low' here. Account for both shapes defensively.
            parts = full.split('.')
            if len(parts) >= 2:
                # If first token is 'modes' (full path returned), name is parts[1].
                # If first token is the mode name (prefix stripped), name is parts[0].
                names.add(parts[1] if parts[0] == 'modes' else parts[0])
        return names

    def _resolve_active_mode(self) -> ModeView:
        """Phase 28 D-08: resolve the active mode to a ModeView once per tick.

        D-04 back-compat: if `modes.{name}.band_low` or `band_high` is NaN
        (sentinel = "modes block absent in YAML"), synthesize a fruiting-shape
        ModeView from legacy `target_humidity` + `humidity_tolerance`.
        """
        name = self.get_parameter('active_mode').value
        bl = self.get_parameter(f'modes.{name}.band_low').value
        bh = self.get_parameter(f'modes.{name}.band_high').value
        if isnan(bl) or isnan(bh):
            tgt = self.get_parameter('target_humidity').value
            tol = self.get_parameter('humidity_tolerance').value
            return ModeView(
                name=name,
                target=tgt,
                band_low=tgt - tol,
                band_high=tgt + tol,
                defend_side='both',
                t_target=nan,
            )
        return ModeView(
            name=name,
            target=self.get_parameter(f'modes.{name}.target_humidity').value,
            band_low=bl,
            band_high=bh,
            defend_side=self.get_parameter(f'modes.{name}.defend_side').value,
            t_target=self.get_parameter(f'modes.{name}.t_target').value,
        )

    def _engage_pid_bumplessly(self):
        self._pid.set_auto_mode(True, last_output=0.15)
        self._pid_engaged = True
        self.get_logger().info('PID engaged with bumpless preload: duty=0.15')

    def _disengage_pid(self):
        if self._pid_engaged:
            self._pid.set_auto_mode(False)
            self._pid_engaged = False

    def _publish_duty(self, duty):
        duty = max(0.0, min(1.0, float(duty)))
        msg = Float32()
        msg.data = duty
        self._duty_pub.publish(msg)

    def _ramp_setpoint(self, dt):
        """Legacy ramp toward `target_humidity` — preserved for callers/tests
        that haven't migrated to mode-aware ramping (Phase 27 contract)."""
        target = self.get_parameter('target_humidity').value
        ramp_seconds = self.get_parameter('pid_setpoint_ramp_seconds').value
        if ramp_seconds <= 0:
            self._effective_setpoint = target
            return
        delta = target - self._effective_setpoint
        if abs(delta) < 1e-6:
            self._effective_setpoint = target
            return
        max_step = abs(delta) * (dt / ramp_seconds)
        step = max(-max_step, min(max_step, delta))
        self._effective_setpoint += step

    def _ramp_setpoint_to_band(self, dt, mode: ModeView):
        """Phase 28 D-10: ramp toward the DEFENDED band edge, not midpoint.

        Midpoint is fiction when bands are wide (pinning has 0.85 cosmetic
        target inside a [0.90, 0.99] band — that's geometrically inverted).
        """
        ramp_seconds = self.get_parameter('pid_setpoint_ramp_seconds').value
        rh = self.current_humidity
        if rh < mode.band_low:
            edge_target = mode.band_low
        elif rh > mode.band_high and mode.defend_side in ('high', 'both'):
            edge_target = mode.band_high
        else:
            # In-band, or above-band-with-low-defense: park ramp at the nearest
            # defended edge. defend_side=low → band_low (drift back into band on
            # a fall); defend_side=high → band_high; defend_side=both → band_low
            # by default (the floor is always defended; symmetric to pre-Phase-28
            # behavior).
            edge_target = mode.band_high if mode.defend_side == 'high' else mode.band_low
        if ramp_seconds <= 0:
            self._effective_setpoint = edge_target
            return
        delta = edge_target - self._effective_setpoint
        if abs(delta) < 1e-6:
            self._effective_setpoint = edge_target
            return
        max_step = abs(delta) * (dt / ramp_seconds)
        step = max(-max_step, min(max_step, delta))
        self._effective_setpoint += step

    def _publish_sensor_health(self, warming_up: bool):
        """Publish a DiagnosticStatus snapshot on fc1/sensor_health.

        Called on state CHANGE only (grace enter and grace exit) to keep
        the topic quiet. TRANSIENT_LOCAL QoS means late-joiners still
        see last state on subscribe.
        """
        grace_period = self.get_parameter('startup_grace_period').value
        elapsed = (
            self.get_clock().now() - self._boot_time
        ).nanoseconds / 1e9
        buffer_full = (
            len(self._humidity_buffer) >= self._humidity_buffer.maxlen
        )
        msg = DiagnosticStatus()
        msg.level = (
            DiagnosticStatus.WARN if warming_up else DiagnosticStatus.OK
        )
        msg.name = 'fc1/controller'
        msg.message = 'warming up' if warming_up else 'ok'
        msg.hardware_id = 'fc1'
        sht30_fresh = self._compute_sht30_fresh()
        scd41_fresh = self._compute_scd41_fresh()
        msg.values = [
            KeyValue(key='warming_up', value=str(warming_up).lower()),
            KeyValue(key='grace_elapsed_sec', value=f'{elapsed:.1f}'),
            KeyValue(key='grace_total_sec', value=f'{grace_period:.1f}'),
            KeyValue(key='buffer_full', value=str(buffer_full).lower()),
            # Phase 26 D-03: per-physical-sensor freshness — append-only (Pitfall 4)
            KeyValue(key='sht30_fresh', value=str(sht30_fresh).lower()),
            KeyValue(key='scd41_fresh', value=str(scd41_fresh).lower()),
        ]
        self.sensor_health_pub.publish(msg)
        self._last_sht30_fresh = sht30_fresh
        self._last_scd41_fresh = scd41_fresh

    def _compute_sht30_fresh(self) -> bool:
        """Phase 26: SHT30 fresh ⇔ slot-1 has carried frame_id=='sht30' within timeout."""
        if self._last_sht30_timestamp is None:
            return False
        elapsed = (
            self.get_clock().now() - self._last_sht30_timestamp
        ).nanoseconds / 1e9
        return elapsed <= self.get_parameter('sensor_stale_timeout').value

    def _compute_scd41_fresh(self) -> bool:
        """Phase 26: SCD41 fresh ⇔ slot-2 temp OR humidity arrived within timeout.

        (gap-acceptable per D-03; either channel proves SCD41 alive.)
        """
        candidates = [
            t for t in (self._last_temp2_timestamp, self._last_humidity2_timestamp)
            if t is not None
        ]
        if not candidates:
            return False
        ts = max(candidates)
        elapsed = (self.get_clock().now() - ts).nanoseconds / 1e9
        return elapsed <= self.get_parameter('sensor_stale_timeout').value

    def control_loop(self):
        # WARMUP-01: startup grace — no actuation until sensors settle
        if self._grace_active():
            self._publish_duty(0.0)
            self._disengage_pid()
            if not self._warmup_signal_published:
                self._publish_sensor_health(warming_up=True)
                self._warmup_signal_published = True
            return

        if self._warming_up:
            self._warming_up = False
            self._publish_sensor_health(warming_up=False)
            self.get_logger().info('WARMUP-CLEARED: control loop engaging')

        # Phase 26 D-03: republish sensor_health when sht30_fresh or scd41_fresh
        # flips, preserving Phase 16's quiet-topic property (state-change only).
        sht30_fresh = self._compute_sht30_fresh()
        scd41_fresh = self._compute_scd41_fresh()
        if (sht30_fresh != self._last_sht30_fresh
                or scd41_fresh != self._last_scd41_fresh):
            self._publish_sensor_health(warming_up=False)

        if self.current_temp is None or self.current_humidity is None:
            self._publish_duty(0.0)
            self._disengage_pid()
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
                self.get_parameter('min_fan_speed').value + (
                    temp_diff * self.get_parameter('fan_temp_scale').value)
            ))
            self.set_fan_speed(fan_speed)
        else:
            self.set_fan_speed(self.get_parameter('min_fan_speed').value)

        if stale:
            # Safe state: drive duty to 0.0, log on transition only (D-13)
            if not self._safe_state_active:
                self._safe_state_active = True
                self.get_logger().warn(
                    'Sensor data stale — humidifier OFF for safety'
                )
            self._publish_duty(0.0)
            self._disengage_pid()
        else:
            # Recovery: log on transition back to fresh data
            if self._safe_state_active:
                self._safe_state_active = False
                self.get_logger().info('Fresh sensor data received — resuming control')

            # PID compute (Phase 27 — replaces bang-bang per HUMID-01..03)
            now = self.get_clock().now()
            dt = (
                (now - self._last_tick_ts).nanoseconds / 1e9
                if self._last_tick_ts is not None
                else 1.0
            )
            self._last_tick_ts = now

            # Phase 28 D-08: resolve active mode once per tick.
            mode = self._resolve_active_mode()

            if not self._pid_engaged:
                self._engage_pid_bumplessly()

            # Live-reload PID gains from ROS params each tick (HUMID-03)
            self._pid.Kp = self.get_parameter('pid_kp').value
            self._pid.Ki = self.get_parameter('pid_ki').value
            self._pid.Kd = self.get_parameter('pid_kd').value

            # Phase 28 D-10: ramp toward defended band edge (not target midpoint).
            self._ramp_setpoint_to_band(dt, mode)
            rh = self.current_humidity

            # Phase 28 D-09: band-aware error projection.
            # error_pct < 0 when below the defended floor → drives duty up via PID.
            if rh < mode.band_low:
                error_pct = (rh - mode.band_low) * 100.0
            elif rh > mode.band_high:
                if mode.defend_side in ('high', 'both'):
                    error_pct = (rh - mode.band_high) * 100.0
                else:
                    # defend_side=low: don't fight upward. Clamp duty + freeze
                    # integrator. Bumpless re-engage on return into band uses
                    # the same primitive as Mode C exit (next tick re-enters
                    # the in-band branch which calls set_auto_mode(True, ...)).
                    if self._pid.auto_mode:
                        self._pid.set_auto_mode(False)
                    self._publish_duty(0.0)
                    ht_msg = Float32()
                    ht_msg.data = float(self._effective_setpoint)
                    self._humidity_target_pub.publish(ht_msg)
                    po_msg = Float32()
                    po_msg.data = 0.0
                    self._pid_output_pub.publish(po_msg)
                    return
            else:
                error_pct = 0.0

            # Phase 28 D-11: Mode C bypass keys off NEAREST DEFENDED edge,
            # not target_humidity. Otherwise pinning's cosmetic target=0.85
            # below band_low=0.90 makes the bypass distance metric meaningless.
            if mode.defend_side == 'low':
                nearest_defended = mode.band_low
            elif mode.defend_side == 'high':
                nearest_defended = mode.band_high
            else:  # 'both' (or any unrecognized value falls through here safely)
                nearest_defended = mode.band_low if rh <= mode.target else mode.band_high
            edge_distance = abs(rh - nearest_defended)
            bypass_pct = self.get_parameter('bypass_threshold').value * 100.0
            edge_distance_pct = edge_distance * 100.0

            if edge_distance_pct > bypass_pct and rh < nearest_defended:
                # Mode C: full ON open-loop, freeze integrator. Only fires when
                # RH is below a defended floor by more than bypass_threshold —
                # the crash-recovery case. High-side excursions on defend_side=low
                # already returned above; high-side excursions on {high, both}
                # produce positive error_pct and stay in the linear PID branch
                # (PID output_limits=(0,1) clamp handles the rest).
                if self._pid.auto_mode:
                    self._pid.set_auto_mode(False)
                raw_pid_output = 1.0
                duty = 1.0
            else:
                if not self._pid.auto_mode:
                    # Re-engage bumplessly from Mode C / clamp.
                    self._pid.set_auto_mode(True, last_output=1.0)
                raw_pid_output = self._pid(error_pct, dt=dt)
                duty = raw_pid_output

            self._publish_duty(duty)

            # Phase 27 telemetry: effective setpoint and raw PID output for Mission Control
            ht_msg = Float32()
            ht_msg.data = float(self._effective_setpoint)
            self._humidity_target_pub.publish(ht_msg)

            po_msg = Float32()
            po_msg.data = max(0.0, min(1.0, float(raw_pid_output)))
            self._pid_output_pub.publish(po_msg)

        # Light control — runs regardless of staleness (D-13)
        self.set_light(self.should_light_be_on())

        self.get_logger().debug(
            f'Temp: {self.current_temp:.1f}°C, '
            f'Humidity: {self.current_humidity * 100:.1f}%, '
            f'Fan: {self.get_fan_speed():.1f}%, '
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
