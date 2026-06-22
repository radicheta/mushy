#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import Temperature, RelativeHumidity
from std_msgs.msg import Float32, String
from collections import deque
from dataclasses import dataclass
from diagnostic_msgs.msg import DiagnosticStatus, KeyValue
from datetime import datetime, timezone, timedelta
from math import exp, isnan, nan
from typing import Optional
from statistics import median
from fc_core import scheduler
from fc_core.vendor.simple_pid import PID
from fc_msgs.msg import Mode
from fc_msgs.srv import SetMode, StartExperiment, CancelExperiment
from rcl_interfaces.msg import SetParametersResult
from rclpy.parameter import Parameter
import json
import time as _time

# 260529-ean: heartbeat interval for periodic sensor_health republish.
# Must be comfortably below the alerter's effective sensor-offline watchdog threshold
# (fc_config sensor_offline_min clamped to [1, 60] minutes by the validator — 60s is
# well under even the minimum 1-minute floor, so healthy sensors stay visible regardless
# of the watchdog tuning).
SENSOR_HEALTH_HEARTBEAT_SEC = 60.0


@dataclass
class ModeView:
    """Phase 28 D-08: snapshot of the active mode resolved once per control tick.

    `t_target` is NaN when unset (D-02 — reserved for VPD-anchoring in Phase 31+).
    `force_duty` is NaN when unset (Phase 31 D-02 sentinel — PID-driven, no
    short-circuit). When finite (0.0..1.0), control_loop bypasses PID + Mode C
    and emits the literal duty value.
    """
    name: str
    target: float
    band_low: float
    band_high: float
    defend_side: str   # 'low' | 'high' | 'both'
    t_target: float    # NaN when unset
    force_duty: float  # Phase 31 D-02: NaN=PID-driven; finite=force short-circuit


@dataclass
class ActiveExperiment:
    """Phase 31 D-05: in-memory state for an in-flight forcing experiment.

    TTL math is anchored on monotonic clock (D-06) — NTP correction has zero
    effect on revert timing. Wall-clock ISO strings are recorded only for
    human-readable timestamps in the experiment_event JSON envelope.
    """
    experiment_mode: str            # 'force-condensation' | 'force-evaporation'
    prior_mode: str                 # mode to revert to on TTL expiry / cancel
    started_at_monotonic: float     # time.monotonic() at start; for TTL math
    reverts_at_monotonic: float     # started_at_monotonic + duration*60
    started_at_wall_iso: str        # ISO 8601 UTC at start (human-readable)
    reverts_at_wall_iso: str        # ISO 8601 UTC at start + duration
    requested_duration_min: int


class FruitingChamberController(Node):
    def __init__(self, **kwargs):
        # Phase 28-04: forward kwargs (e.g. parameter_overrides=, namespace=) to
        # rclpy.node.Node so tests can inject mode params at __init__ time —
        # required for startup-republish of current_mode to observe the
        # test-supplied mode shape rather than the declared NaN-sentinel
        # defaults.
        super().__init__('fc_controller', **kwargs)

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
                ('pid_integrator_decay_tau', 1200.0),
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
                ('modes.fruiting.force_duty', float('nan')),
                ('modes.pinning.target_humidity', 0.85),
                ('modes.pinning.band_low', float('nan')),
                ('modes.pinning.band_high', float('nan')),
                ('modes.pinning.defend_side', 'low'),
                ('modes.pinning.t_target', float('nan')),
                ('modes.pinning.force_duty', float('nan')),
                # Phase 31 D-01: force modes — wide-open bands [0.0, 1.0],
                # force_duty short-circuit (1.0=continuous-on, 0.0=continuous-off).
                # YAML overrides target_humidity/band_*/defend_side/t_target/
                # force_duty per Plan 31-01.
                ('modes.force-condensation.target_humidity', 1.0),
                ('modes.force-condensation.band_low', 0.0),
                ('modes.force-condensation.band_high', 1.0),
                ('modes.force-condensation.defend_side', 'both'),
                ('modes.force-condensation.t_target', float('nan')),
                ('modes.force-condensation.force_duty', 1.0),
                ('modes.force-evaporation.target_humidity', 0.0),
                ('modes.force-evaporation.band_low', 0.0),
                ('modes.force-evaporation.band_high', 1.0),
                ('modes.force-evaporation.defend_side', 'both'),
                ('modes.force-evaporation.t_target', float('nan')),
                ('modes.force-evaporation.force_duty', 0.0),
                # Phase 30 D-01: JSON-encoded list of {start,end,mode}; default
                # '[]' = scheduling disabled (SCHED-03 backward compat). Real
                # value comes from fc_config.yaml / runtime_overrides.yaml.
                ('schedule_windows', '[]'),
            ]
        )

        # Phase 29 Tier B — per-mode alerter overrides (D-05).
        # Defaults are bootstrap-only; tuned values land in plan 29-06 via
        # fc_config.yaml. Validator (Phase 29) enforces ranges atomically.
        for _mode_name in ('fruiting', 'pinning'):
            self.declare_parameter(f'modes.{_mode_name}.alerter.cooldown_min',          30)
            self.declare_parameter(f'modes.{_mode_name}.alerter.critical_cooldown_min', 60)
            self.declare_parameter(f'modes.{_mode_name}.alerter.humidifier_stuck_min',  30)
            self.declare_parameter(f'modes.{_mode_name}.alerter.oob_n',                 5)
            self.declare_parameter(f'modes.{_mode_name}.alerter.oob_window_min',        3)

        # Phase 29 Tier C — global alerter knobs (runtime-tunable via SetParameters; D-05).
        self.declare_parameter('pi_offline_min',     5)
        self.declare_parameter('sensor_offline_min', 5)
        self.declare_parameter('heartbeat_hour',     8)
        self.declare_parameter('max_sends_per_hour', 20)

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

        # Phase 28 D-13/D-14: current_mode topic. TRANSIENT_LOCAL so late
        # subscribers (alerter Phase 29, scheduler Phase 30, bridge dashboard)
        # get the last value on subscribe — same QoS pattern as Phase 27
        # telemetry trio. Pitfall 2: TRANSIENT_LOCAL does NOT survive process
        # restart, so the controller MUST publish once at startup (end of
        # __init__) AFTER active_mode is resolvable.
        self._current_mode_pub = self.create_publisher(
            Mode, 'fc1/control/current_mode', actuator_qos
        )

        # Phase 29-07 deploy fix (2026-05-08): bridge container ships with
        # ros:jazzy-ros-core only — no fc_msgs build, so rclnodejs cannot
        # generate JS bindings for fc_msgs/msg/Mode. RESEARCH §460 assumed
        # "fc_msgs already built on bridge image"; that assumption was false
        # (Phase 28 never added a Mode subscriber on the bridge). Mirror the
        # alerter_globals/alerter_mode_overrides pattern and ship a sibling
        # JSON-in-String topic the bridge can consume without a custom-msg
        # build cycle. The typed Mode publisher stays for any future ROS-
        # native consumer.
        self._current_mode_json_pub = self.create_publisher(
            String, 'fc1/control/current_mode_json', actuator_qos
        )

        # Phase 29 D-06: delivery channel for Tier B (per-mode alerter overrides)
        # and Tier C (global alerter knobs). JSON-in-String avoids a second
        # fc_msgs build cycle (RESEARCH §Anti-Patterns). Same TRANSIENT_LOCAL
        # QoS as current_mode so late-joining bridge replays last value on
        # subscribe (Pitfall 1; startup republish at end of __init__).
        # Topic: fc1/control/alerter_mode_overrides — Tier B per-mode alerter knobs.
        self._alerter_overrides_pub = self.create_publisher(
            String, 'fc1/control/alerter_mode_overrides', actuator_qos
        )
        self._alerter_globals_pub = self.create_publisher(
            String, 'fc1/control/alerter_globals', actuator_qos
        )

        # Phase 31 D-22 / D-31: experiment_event JSON-in-String topic.
        # JSON-in-String over std_msgs/String mirrors the Phase 29-07 precedent
        # — the bridge container ships ros:jazzy-ros-core only (no fc_msgs
        # build), so a typed Mode-style topic would force a second build cycle.
        # Same TRANSIENT_LOCAL/RELIABLE/depth=1 QoS as current_mode (D-15) so
        # late subscribers (UI poll, audit) get the last value on subscribe.
        self._experiment_event_pub = self.create_publisher(
            String, 'fc1/control/experiment_event', actuator_qos
        )

        # Phase 28 D-15 + Pitfall 4: validate SetParameters batches atomically
        # (whole batch passes or fails — no partial application). Defense-in-depth
        # against the bridge allowlist (Phase 28-05): even if a bad value slips
        # past the bridge or the bridge container is compromised, the callback
        # rejects band-invariant violations, enum violations, and PID-range
        # overruns at the rcl boundary.
        self._pending_current_mode_republish = None
        # Phase 29 — pending-republish flags for Tier B + Tier C topics; drained
        # at the top of control_loop on the next tick (Pattern C: in-callback
        # publish would emit pre-applied state because rclpy applies the new
        # param values AFTER _validate_params returns successful=True).
        self._pending_alerter_overrides_republish = None
        self._pending_alerter_globals_republish = None
        # Phase 31 D-03/D-05: gate flag for service-orchestrated set_parameters
        # into a force mode. _validate_params permits 'active_mode'='force-*'
        # ONLY when this flag is True (toggled by _handle_start_experiment /
        # _handle_cancel_experiment / _experiment_tick / _check_force_mode_at_boot).
        # _active_experiment is the in-memory record of the in-flight experiment
        # (None when idle). Phase 31 D-12 — _active_experiment is also the
        # single source of truth for scheduler suppression (D-08).
        self._experiment_set_in_progress = False
        self._active_experiment: Optional[ActiveExperiment] = None
        # Phase 31 D-12 follow-up (2026-05-09 hotfix): snapshot of
        # _last_published_duty taken at experiment entry, restored on revert.
        # Without this, the force_duty short-circuit overwrites
        # _last_published_duty with the artificial value (1.0 or 0.0) and the
        # bumpless re-engage seeds the PID integrator with that value — duty
        # stays pinned at the force value if RH is in-band at revert.
        self._pre_experiment_duty: Optional[float] = None
        self.add_on_set_parameters_callback(self._validate_params)

        # Phase 28 D-16: mode-switch service. Custom srv in fc_msgs. The handler
        # writes active_mode via self.set_parameters(...) so the validator above
        # also fires — single source of truth for "is this name a declared mode?".
        self._set_mode_srv = self.create_service(
            SetMode, 'set_mode', self._handle_set_mode
        )

        # Phase 31 D-10/D-13: forcing-experiment services. start_experiment
        # gates entry into a force-* mode behind validation (name, duration
        # range, no-active-experiment lockout, controller readiness) and
        # registers an in-memory ActiveExperiment with monotonic-clock TTL.
        # cancel_experiment early-reverts via the same in-process set_parameters
        # path. Both helpers toggle _experiment_set_in_progress around the
        # gated set_parameters call so _validate_params permits the force-*
        # transition (D-03).
        self._start_experiment_srv = self.create_service(
            StartExperiment, 'start_experiment', self._handle_start_experiment
        )
        self._cancel_experiment_srv = self.create_service(
            CancelExperiment, 'cancel_experiment', self._handle_cancel_experiment
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
        # 260529-ean: shared timestamp for heartbeat republish — None until the first
        # real publish (warmup WARN or grace-exit OK).  None guard + grace early-return
        # together ensure the heartbeat never fires during the startup grace window.
        self._last_sensor_health_publish = None

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
        # Phase 28 D-12: track last duty so set_mode can pass it as last_output
        # to _engage_pid_bumplessly — carries the integrator across mode swaps
        # without a kick.
        self._last_published_duty = 0.0
        # 999.32: low-pass-filtered derivative term. Vendored simple_pid lacks
        # native derivative filtering; we filter outside the library after each
        # PID call. Reset on every (re-)engage so the filter doesn't carry
        # stale state across mode swaps / experiments / restarts.
        self._d_filtered = 0.0

        # Control timer
        self.timer = self.create_timer(
            self.get_parameter('control_interval').value,
            self.control_loop
        )

        # Phase 31 D-05: 1 Hz TTL check for in-flight experiments. Monotonic
        # clock (not wall clock) per D-06 — NTP correction cannot extend or
        # truncate an experiment unexpectedly.
        self._experiment_timer = self.create_timer(1.0, self._experiment_tick)

        self.get_logger().info('Fruiting Chamber Controller Node Started')

        # Phase 31 D-09: boot-recovery — never come up running a force mode.
        # Must run AFTER declare_parameters + experiment_event_pub creation but
        # BEFORE the initial config_default publish so that publish reflects
        # the recovered (non-force) mode. If the runtime overlay carried
        # active_mode='force-*', this forces it back to a safe baseline and
        # emits a 'truncated' experiment_event so the bridge can close any
        # in-flight DB row left by the pre-restart experiment.
        self._check_force_mode_at_boot()

        # Phase 28 Pitfall 2: TRANSIENT_LOCAL durability does NOT persist across
        # process restart. Publish current_mode once at startup AFTER the param
        # store is initialized so late subscribers (Phase 29 alerter, future
        # scheduler) see the active mode without polling.
        self._publish_current_mode(source='config_default')
        # Phase 29 Pitfall 1: TRANSIENT_LOCAL durability does NOT persist across
        # process restart. Publish once at startup so the bridge (Phase 29-04)
        # and any late-joiners receive the cached payloads on subscribe.
        self._publish_alerter_overrides(source='config_default')
        self._publish_alerter_globals(source='config_default')

        # Phase 30 D-06..D-09 — time-of-day scheduler.
        # Plain attribute clock seam (testable: `node._now_hhmm = lambda: ...`).
        self._now_hhmm = self._default_now_hhmm
        # Gap-debounce state — last-emitted (kind, mode) tuple so a continuous
        # gap logs once per (kind, mode) entry rather than every 30s tick.
        self._last_scheduler_log = None
        # D-09 startup alignment — fire one immediate eval so reboot-mid-window
        # comes up correct. Runs AFTER the config_default current_mode publish
        # so a scheduler-initiated swap publishes a SECOND current_mode with
        # source='scheduler' (audit trail intact).
        self._scheduler_tick()
        # D-07 30s timer cadence — bounded, deterministic, well under PID's
        # thermal-lag timescales.
        self._scheduler_timer = self.create_timer(30.0, self._scheduler_tick)

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
        # rclpy Jazzy: get_parameters_by_prefix('modes.') (trailing dot) returns
        # an empty dict due to internal prefix handling — pass 'modes' instead
        # so the dotted-key namespace is split correctly. Returned keys have the
        # prefix stripped (e.g. 'fruiting.band_low').
        for full in self.get_parameters_by_prefix('modes').keys():
            parts = full.split('.')
            if len(parts) >= 2:
                # Defensive: handle both stripped and full-path shapes.
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
                force_duty=nan,
            )
        # Phase 31 D-02: force_duty is declared on every mode (NaN sentinel for
        # non-force modes); read it via get_parameter to populate ModeView.
        try:
            force_duty = self.get_parameter(f'modes.{name}.force_duty').value
        except Exception:
            # Defensive: very old overlay without force_duty for an obscure mode.
            force_duty = nan
        return ModeView(
            name=name,
            target=self.get_parameter(f'modes.{name}.target_humidity').value,
            band_low=bl,
            band_high=bh,
            defend_side=self.get_parameter(f'modes.{name}.defend_side').value,
            t_target=self.get_parameter(f'modes.{name}.t_target').value,
            force_duty=force_duty,
        )

    def _build_mode_msg(self, mv: ModeView, source: str) -> Mode:
        """Phase 28 D-13: assemble fc_msgs/Mode from a ModeView snapshot.

        `effective_since` is stamped at build time with the controller clock.
        `t_target` is forwarded NaN-or-finite per D-02; rclpy round-trips both
        through float32 without coercion.
        """
        msg = Mode()
        msg.name = mv.name
        msg.target_humidity = float(mv.target)
        msg.band_low = float(mv.band_low)
        msg.band_high = float(mv.band_high)
        msg.defend_side = mv.defend_side
        msg.t_target = float(mv.t_target)
        msg.effective_since = self.get_clock().now().to_msg()
        msg.source = source
        return msg

    def _publish_current_mode(self, source: str = 'config_default'):
        """Resolve the active mode and publish on /fc1/control/current_mode.

        Called from three sites:
          (1) end of __init__ with source='config_default' (Pitfall 2 mitigation),
          (2) on_set_parameters_callback's next-tick drain with source='param_set'
              (D-15 — band-edge tweak republish),
          (3) set_mode service handler synchronously with source='service_call'
              (D-15 — service-driven mode swap).

        Also emits a cosmetic WARN when target lies outside [band_low, band_high]
        (D-06: pinning's target=0.85 lives below band_low=0.90 by design — the
        message is operational signal, not a config rejection per OQ-5).
        """
        mv = self._resolve_active_mode()
        msg = self._build_mode_msg(mv, source)
        self._current_mode_pub.publish(msg)
        # Phase 29-07: also publish JSON sibling for the bridge (which lacks
        # fc_msgs/msg/Mode bindings). NaN-safe t_target serialization mirrors
        # bridge's payload shape.
        self._publish_current_mode_json(mv, source)
        self.get_logger().info(
            f'current_mode → {mv.name} '
            f'[band {mv.band_low:.3f}–{mv.band_high:.3f}, defend={mv.defend_side}, '
            f'source={source}]'
        )
        # OQ-5 / D-06: target outside band is intentional for pinning. Surface as
        # WARN so the operator sees it but don't reject the config.
        if not (mv.band_low <= mv.target <= mv.band_high):
            self.get_logger().warn(
                f'target {mv.target} outside band [{mv.band_low},{mv.band_high}] '
                f'for mode {mv.name} — cosmetic, by D-06'
            )

    def _publish_current_mode_json(self, mv, source: str):
        """Phase 29-07: JSON sibling of current_mode for the bridge container.

        Bridge ships ros:jazzy-ros-core only; rclnodejs lacks fc_msgs/Mode
        bindings. JSON-in-String mirrors the alerter_mode_overrides /
        alerter_globals delivery pattern (RESEARCH §Anti-Patterns recommends
        JSON-in-String to avoid second fc_msgs build cycle).
        """
        import json
        import math
        now = self.get_clock().now().to_msg()
        t_target = mv.t_target if (mv.t_target is not None and not math.isnan(mv.t_target)) else None
        payload = {
            'name':            mv.name,
            'target_humidity': mv.target,
            'band_low':        mv.band_low,
            'band_high':       mv.band_high,
            'defend_side':     mv.defend_side,
            't_target':        t_target,
            'effective_since': {'sec': now.sec, 'nanosec': now.nanosec},
            'source':          source,
        }
        msg = String()
        msg.data = json.dumps(payload, sort_keys=True)
        self._current_mode_json_pub.publish(msg)

    def _publish_alerter_overrides(self, source: str = 'param_set'):
        """Phase 29 D-06: publish per-mode alerter overrides as JSON-in-String.

        Payload shape: { "<mode_name>": { "cooldown_min": int, ... } } for every
        declared mode (fruiting, pinning v0). Subscribed by bridge (Phase 29-04)
        and broadcast to alerter via WS.
        """
        import json
        payload = {}
        for mode_name in ('fruiting', 'pinning'):
            payload[mode_name] = {
                'cooldown_min':          self.get_parameter(f'modes.{mode_name}.alerter.cooldown_min').value,
                'critical_cooldown_min': self.get_parameter(f'modes.{mode_name}.alerter.critical_cooldown_min').value,
                'humidifier_stuck_min':  self.get_parameter(f'modes.{mode_name}.alerter.humidifier_stuck_min').value,
                'oob_n':                 self.get_parameter(f'modes.{mode_name}.alerter.oob_n').value,
                'oob_window_min':        self.get_parameter(f'modes.{mode_name}.alerter.oob_window_min').value,
            }
        msg = String()
        msg.data = json.dumps(payload, sort_keys=True)
        self._alerter_overrides_pub.publish(msg)
        self.get_logger().info(f'[alerter_overrides] republished (source={source})')

    def _publish_alerter_globals(self, source: str = 'param_set'):
        """Phase 29 D-06: publish Tier C global alerter knobs as JSON-in-String."""
        import json
        payload = {
            'pi_offline_min':     self.get_parameter('pi_offline_min').value,
            'sensor_offline_min': self.get_parameter('sensor_offline_min').value,
            'heartbeat_hour':     self.get_parameter('heartbeat_hour').value,
            'max_sends_per_hour': self.get_parameter('max_sends_per_hour').value,
        }
        msg = String()
        msg.data = json.dumps(payload, sort_keys=True)
        self._alerter_globals_pub.publish(msg)
        self.get_logger().info(f'[alerter_globals] republished (source={source})')

    def _validate_params(self, params) -> SetParametersResult:
        """Phase 28 D-15 + Pitfall 4: validate SetParameters batches atomically.

        Whole batch passes or fails — first violating param triggers immediate
        rejection with a reason naming the violation. Cross-param invariants
        (e.g. band_low<band_high) check the WOULD-BE state after the batch is
        applied, not the pre-batch state, so a batched edit that flips
        [band_low, band_high] simultaneously can land even when the per-param
        new value would individually violate against the unmodified peer.

        Defense in depth: range bounds on pid_kp/ki/kd mirror the bridge
        allowlist (Phase 28-05) so a bridge bypass cannot push insane gains.

        On accept of any mode-shape param, queue a republish of current_mode
        for the next control_loop tick (D-15) — not synchronous because rclpy
        applies the new param values AFTER this callback returns successful=True;
        publishing in-callback would emit the OLD ModeView.
        """
        # Build "post-batch view" so cross-param invariants check the would-be
        # state. `post[name] = new_value` for params in the batch; lookups for
        # peers fall back to the current param store.
        post = {p.name: p.value for p in params}

        def get_post(name):
            if name in post:
                return post[name]
            return self.get_parameter(name).value

        republish_current_mode = False
        # Phase 29 — Tier B + Tier C republish flags (Pattern C: deferred drain).
        republish_alerter_overrides = False
        republish_alerter_globals = False
        for p in params:
            n = p.name
            v = p.value
            if n.startswith('modes.') and n.endswith('.band_low'):
                prefix = n.rsplit('.', 1)[0]
                bh = get_post(f'{prefix}.band_high')
                # NaN peer = D-04 sentinel (modes block absent in YAML); skip
                # invariant check, just bound the new value to [0,1].
                if isnan(bh):
                    if not (0.0 <= v <= 1.0):
                        return SetParametersResult(
                            successful=False,
                            reason=f'{n}: must be in [0,1] (got {v})',
                        )
                elif not (0.0 <= v < bh <= 1.0):
                    return SetParametersResult(
                        successful=False,
                        reason=f'{n}: must satisfy 0<=band_low<band_high<=1 '
                               f'(got band_low={v}, band_high={bh})',
                    )
                republish_current_mode = True
            elif n.startswith('modes.') and n.endswith('.band_high'):
                prefix = n.rsplit('.', 1)[0]
                bl = get_post(f'{prefix}.band_low')
                if isnan(bl):
                    if not (0.0 <= v <= 1.0):
                        return SetParametersResult(
                            successful=False,
                            reason=f'{n}: must be in [0,1] (got {v})',
                        )
                elif not (0.0 <= bl < v <= 1.0):
                    return SetParametersResult(
                        successful=False,
                        reason=f'{n}: must satisfy 0<=band_low<band_high<=1 '
                               f'(got band_low={bl}, band_high={v})',
                    )
                republish_current_mode = True
            elif n.startswith('modes.') and n.endswith('.defend_side'):
                if v not in ('low', 'high', 'both'):
                    return SetParametersResult(
                        successful=False,
                        reason=f'{n}: must be one of low|high|both (got {v!r})',
                    )
                republish_current_mode = True
            elif n.startswith('modes.') and n.endswith('.target_humidity'):
                if not (0.0 <= v <= 1.0):
                    return SetParametersResult(
                        successful=False,
                        reason=f'{n}: must be in [0,1] (got {v})',
                    )
                republish_current_mode = True
            # Phase 29 — Tier B per-mode alerter knobs (`modes.<name>.alerter.<key>`).
            elif n.startswith('modes.') and '.alerter.' in n:
                parts = n.split('.')
                if len(parts) != 4 or parts[0] != 'modes' or parts[2] != 'alerter':
                    return SetParametersResult(
                        successful=False,
                        reason=f'{n}: malformed alerter dotted-key',
                    )
                key = parts[3]
                if key in ('cooldown_min', 'critical_cooldown_min', 'humidifier_stuck_min'):
                    if not (isinstance(v, int) and 1 <= v <= 240):
                        return SetParametersResult(
                            successful=False,
                            reason=f'{n}: must be int in [1,240] (got {v})',
                        )
                elif key == 'oob_n':
                    if not (isinstance(v, int) and 1 <= v <= 20):
                        return SetParametersResult(
                            successful=False,
                            reason=f'{n}: must be int in [1,20] (got {v})',
                        )
                elif key == 'oob_window_min':
                    if not (isinstance(v, int) and 1 <= v <= 60):
                        return SetParametersResult(
                            successful=False,
                            reason=f'{n}: must be int in [1,60] (got {v})',
                        )
                else:
                    return SetParametersResult(
                        successful=False,
                        reason=f'{n}: unknown alerter key {key}',
                    )
                republish_alerter_overrides = True
            # Phase 29 — Tier C global alerter knobs.
            elif n in ('pi_offline_min', 'sensor_offline_min'):
                if not (isinstance(v, int) and 1 <= v <= 60):
                    return SetParametersResult(
                        successful=False,
                        reason=f'{n}: must be int in [1,60] (got {v})',
                    )
                republish_alerter_globals = True
            elif n == 'heartbeat_hour':
                if not (isinstance(v, int) and 0 <= v <= 23):
                    return SetParametersResult(
                        successful=False,
                        reason=f'{n}: must be int in [0,23] (got {v})',
                    )
                republish_alerter_globals = True
            elif n == 'max_sends_per_hour':
                if not (isinstance(v, int) and 1 <= v <= 200):
                    return SetParametersResult(
                        successful=False,
                        reason=f'{n}: must be int in [1,200] (got {v})',
                    )
                republish_alerter_globals = True
            elif n == 'active_mode':
                declared = self._declared_mode_names()
                if v not in declared:
                    return SetParametersResult(
                        successful=False,
                        reason=f'active_mode={v!r} not in declared modes '
                               f'{sorted(declared)}',
                    )
                # Phase 31 D-03: force-* modes are service-only. Direct
                # SetParameters('active_mode','force-*') is rejected unless the
                # _experiment_set_in_progress flag is True (toggled inside the
                # start_experiment / cancel_experiment / TTL revert / boot-
                # recovery handlers). Plain /set_mode service rejects them at
                # the handler level (defense in depth).
                if isinstance(v, str) and v.startswith('force-') and not self._experiment_set_in_progress:
                    return SetParametersResult(
                        successful=False,
                        reason=(
                            f'active_mode={v!r} is service_only — call '
                            f'/fc_controller/start_experiment instead of set_mode'
                        ),
                    )
                republish_current_mode = True
            elif n == 'schedule_windows':
                # Phase 30 D-01..D-04 — JSON-encoded list of windows. Reject
                # malformed JSON, missing keys, bad HH:MM, or unknown mode
                # names. Old value retained on reject (rclpy callback pattern).
                # Empty array '[]' is always valid (= scheduling disabled,
                # SCHED-03 backward compat).
                try:
                    windows = scheduler.parse_schedule(v)
                    declared = self._declared_mode_names()
                    for w in windows:
                        scheduler.validate_window(w, declared)
                except ValueError as e:
                    return SetParametersResult(
                        successful=False, reason=str(e)
                    )
                # No republish needed — schedule edits don't change current_mode
                # synchronously; the scheduler timer fires at the next 30s tick.
            elif n == 'pid_kp':
                if not (0.0 <= v <= 5.0):
                    return SetParametersResult(
                        successful=False,
                        reason=f'pid_kp must be in [0,5] (got {v})',
                    )
            elif n == 'pid_ki':
                if not (0.0 <= v <= 1.0):
                    return SetParametersResult(
                        successful=False,
                        reason=f'pid_ki must be in [0,1] (got {v})',
                    )
            elif n == 'pid_kd':
                if not (0.0 <= v <= 20.0):
                    return SetParametersResult(
                        successful=False,
                        reason=f'pid_kd must be in [0,20] (got {v})',
                    )

        if republish_current_mode:
            # Drained at top of control_loop on the next tick. rclpy applies the
            # accepted param values after this returns; in-callback publish would
            # emit the pre-applied ModeView.
            self._pending_current_mode_republish = ('param_set',)
        # Phase 29 — same deferred-drain pattern for the two new topics.
        if republish_alerter_overrides:
            self._pending_alerter_overrides_republish = ('param_set',)
        if republish_alerter_globals:
            self._pending_alerter_globals_republish = ('param_set',)

        return SetParametersResult(successful=True)

    def _handle_set_mode(self, request, response):
        """Phase 28 D-16: /fc_controller/set_mode service handler.

        Routes through self.set_parameters(...) so _validate_params fires —
        single source of truth for "is this name a declared mode?". On accept:
          (1) D-12 bumpless re-engage with current duty so the integrator
              doesn't kick when bands change underfoot,
          (2) D-15 synchronous republish with source='service_call' (rclpy has
              already applied the param value by the time this returns from
              set_parameters, so synchronous publish emits the NEW ModeView),
          (3) suppress the redundant next-tick republish that the validator
              queued — we already published synchronously here.
        """
        declared = self._declared_mode_names()
        # Phase 31 D-03: /set_mode is for non-force modes only; route force-*
        # requests to /start_experiment so a TTL is always associated.
        if request.name.startswith('force-'):
            response.success = False
            response.reason = (
                f'mode {request.name!r} is service_only — '
                f'call /fc_controller/start_experiment'
            )
            response.active_mode = self._build_mode_msg(
                self._resolve_active_mode(), source='service_call_rejected'
            )
            return response
        if request.name not in declared:
            response.success = False
            response.reason = (
                f'unknown mode {request.name!r}; declared: {sorted(declared)}'
            )
            response.active_mode = self._build_mode_msg(
                self._resolve_active_mode(), source='service_call_rejected'
            )
            return response

        results = self.set_parameters([
            Parameter('active_mode', Parameter.Type.STRING, request.name)
        ])
        if not results[0].successful:
            response.success = False
            response.reason = results[0].reason
            response.active_mode = self._build_mode_msg(
                self._resolve_active_mode(), source='service_call_rejected'
            )
            # Validator may have queued a republish on a *different* param in
            # the (single-element here) batch — clear it; the rejection path
            # didn't actually mutate anything.
            self._pending_current_mode_republish = None
            return response

        # D-12: bumpless re-engage carrying current duty.
        self._engage_pid_bumplessly(last_output=self._last_published_duty)

        # D-15: synchronous republish (the param IS applied by now).
        new_mv = self._resolve_active_mode()
        msg = self._build_mode_msg(new_mv, source='service_call')
        self._current_mode_pub.publish(msg)
        # Phase 29-07: JSON sibling for the bridge.
        self._publish_current_mode_json(new_mv, source='service_call')
        self.get_logger().info(
            f'set_mode → {new_mv.name} '
            f'[band {new_mv.band_low:.3f}–{new_mv.band_high:.3f}, '
            f'defend={new_mv.defend_side}, source=service_call]'
        )
        # Suppress the redundant next-tick republish queued by _validate_params.
        self._pending_current_mode_republish = None

        response.success = True
        response.reason = ''
        response.active_mode = msg
        return response

    # ---- Phase 31: experimental forcing modes ----------------------------------
    def _wall_now_iso(self) -> str:
        """ISO 8601 UTC stamp from wall clock. Test seam — overridable via
        attribute reassignment (e.g. node._wall_now_iso = lambda: '2026-...').
        """
        return datetime.now(timezone.utc).isoformat()

    def _monotonic(self) -> float:
        """Monotonic clock (seconds). Phase 31 D-06 — TTL math is anchored
        on monotonic, not wall clock. Test seam — overridable for TTL tests.
        """
        return _time.monotonic()

    def _publish_experiment_event(self, event: str,
                                   experiment: 'Optional[ActiveExperiment]',
                                   actual_minutes: 'Optional[float]'):
        """Phase 31 D-22 / D-31: publish a JSON envelope on
        fc1/control/experiment_event for bridge consumption.

        event ∈ {'started', 'ended', 'cancelled', 'truncated'}.
        Bridge persists this to fc_experiments table (Plan 31-03).
        Truncated-on-boot may have no in-memory experiment record (overlay
        only) — payload uses None for the unknown fields in that case.
        """
        now_iso = self._wall_now_iso()
        if experiment is not None:
            payload = {
                'event': event,
                'experiment': experiment.experiment_mode,
                'prior_mode': experiment.prior_mode,
                'requested_minutes': int(experiment.requested_duration_min),
                'actual_minutes': actual_minutes,
                'started_at_iso': experiment.started_at_wall_iso,
                'ended_at_iso': now_iso if event != 'started' else None,
                'reverts_at_iso': experiment.reverts_at_wall_iso if event == 'started' else None,
                'wall_clock_iso': now_iso,
            }
        else:
            payload = {
                'event': event,
                'experiment': None,
                'prior_mode': None,
                'requested_minutes': None,
                'actual_minutes': None,
                'started_at_iso': None,
                'ended_at_iso': now_iso,
                'reverts_at_iso': None,
                'wall_clock_iso': now_iso,
            }
        msg = String()
        msg.data = json.dumps(payload, separators=(',', ':'), sort_keys=True)
        self._experiment_event_pub.publish(msg)

    def _handle_start_experiment(self, request, response):
        """Phase 31 D-10/D-11: enter a force experiment with TTL.

        Validation order (D-11):
          1. experiment_name in {force-condensation, force-evaporation}
          2. 1 <= duration_minutes <= 120
          3. _active_experiment is None (single-experiment lockout)
          4. controller is ready (active_mode resolves cleanly)
        On accept: allocate ActiveExperiment, do gated in-process set_parameters
        to enter the force mode, bumpless re-engage with current duty
        (carry-over for the eventual revert), publish current_mode with
        source='experiment', publish experiment_event with event='started'.
        """
        name = request.experiment_name
        try:
            dur = int(request.duration_minutes)
        except Exception:
            dur = -1

        # 1. name
        if name not in ('force-condensation', 'force-evaporation'):
            response.ok = False
            response.message = 'unknown_experiment'
            response.started_at_iso = ''
            response.reverts_at_iso = ''
            response.prior_mode = ''
            return response

        # 2. duration
        if not (1 <= dur <= 120):
            response.ok = False
            response.message = 'duration_out_of_range (1..120)'
            response.started_at_iso = ''
            response.reverts_at_iso = ''
            response.prior_mode = ''
            return response

        # 3. lockout
        if self._active_experiment is not None:
            response.ok = False
            response.message = 'experiment_in_progress'
            response.started_at_iso = ''
            response.reverts_at_iso = ''
            response.prior_mode = ''
            return response

        # 4. controller readiness
        try:
            prior_mv = self._resolve_active_mode()
        except Exception as e:
            response.ok = False
            response.message = f'controller_not_ready: {e}'
            response.started_at_iso = ''
            response.reverts_at_iso = ''
            response.prior_mode = ''
            return response
        prior_mode = prior_mv.name

        # Allocate the experiment record.
        started_mono = self._monotonic()
        reverts_mono = started_mono + dur * 60.0
        started_wall = datetime.now(timezone.utc)
        reverts_wall = started_wall + timedelta(minutes=dur)
        started_iso = started_wall.isoformat()
        reverts_iso = reverts_wall.isoformat()

        experiment = ActiveExperiment(
            experiment_mode=name,
            prior_mode=prior_mode,
            started_at_monotonic=started_mono,
            reverts_at_monotonic=reverts_mono,
            started_at_wall_iso=started_iso,
            reverts_at_wall_iso=reverts_iso,
            requested_duration_min=dur,
        )

        # 2026-05-09 hotfix: snapshot pre-experiment duty BEFORE the swap.
        # The force_duty short-circuit will overwrite _last_published_duty
        # with the artificial value (1.0 or 0.0) on the first post-swap tick;
        # we need the real prior steady-state duty for revert's bumpless
        # re-engage.
        self._pre_experiment_duty = self._last_published_duty

        # In-process mode swap, gated by D-03 flag.
        self._experiment_set_in_progress = True
        try:
            results = self.set_parameters([
                Parameter('active_mode', Parameter.Type.STRING, name)
            ])
        finally:
            self._experiment_set_in_progress = False
        if not results[0].successful:
            # Roll back the snapshot — we never actually entered force mode.
            self._pre_experiment_duty = None
            response.ok = False
            response.message = f'set_parameters_failed: {results[0].reason}'
            response.started_at_iso = ''
            response.reverts_at_iso = ''
            response.prior_mode = prior_mode
            return response

        # Commit experiment state.
        self._active_experiment = experiment

        # Bumpless re-engage carrying current duty (D-12 carry-over). The
        # force_duty short-circuit will park PID on the next tick anyway, but
        # this keeps _last_published_duty as the cached carry-over for the
        # eventual revert.
        self._engage_pid_bumplessly(last_output=self._last_published_duty)

        # D-15 + D-31: synchronous current_mode publish with source='experiment'.
        new_mv = self._resolve_active_mode()
        cm_msg = self._build_mode_msg(new_mv, source='experiment')
        self._current_mode_pub.publish(cm_msg)
        self._publish_current_mode_json(new_mv, source='experiment')
        self._pending_current_mode_republish = None

        # D-22: experiment_event 'started'.
        self._publish_experiment_event('started', experiment, actual_minutes=None)

        # D-30: INFO log.
        self.get_logger().info(
            f'[experiment] started: {name} {dur}min, '
            f'prior={prior_mode}, reverts={reverts_iso}'
        )

        response.ok = True
        response.message = ''
        response.started_at_iso = started_iso
        response.reverts_at_iso = reverts_iso
        response.prior_mode = prior_mode
        return response

    def _handle_cancel_experiment(self, request, response):
        """Phase 31 D-13: early-revert an in-flight experiment.

        Reverts via the same gated set_parameters path as the TTL timer,
        publishes current_mode with source='experiment_cancel', publishes
        experiment_event with event='cancelled' carrying actual_minutes.
        """
        if self._active_experiment is None:
            response.ok = False
            response.message = 'no_experiment_active'
            response.ended_at_iso = ''
            return response

        experiment = self._active_experiment
        actual_min = (self._monotonic() - experiment.started_at_monotonic) / 60.0
        ended_iso = self._wall_now_iso()

        # Revert via gated set_parameters.
        self._experiment_set_in_progress = True
        try:
            self.set_parameters([
                Parameter('active_mode', Parameter.Type.STRING, experiment.prior_mode)
            ])
        finally:
            self._experiment_set_in_progress = False

        # Clear FIRST so the scheduler can resume on its next tick.
        self._active_experiment = None

        # 2026-05-09 hotfix: re-engage with the PRE-experiment duty, not
        # _last_published_duty (which holds the force-mode artificial value).
        revert_seed = (
            self._pre_experiment_duty
            if self._pre_experiment_duty is not None
            else self._last_published_duty
        )
        self._pre_experiment_duty = None
        # D-12 bumpless re-engage carrying pre-experiment duty.
        self._engage_pid_bumplessly(last_output=revert_seed)

        # D-15: synchronous current_mode publish with source='experiment_cancel'.
        new_mv = self._resolve_active_mode()
        cm_msg = self._build_mode_msg(new_mv, source='experiment_cancel')
        self._current_mode_pub.publish(cm_msg)
        self._publish_current_mode_json(new_mv, source='experiment_cancel')
        self._pending_current_mode_republish = None

        # D-22: experiment_event 'cancelled'.
        self._publish_experiment_event('cancelled', experiment, actual_minutes=actual_min)

        self.get_logger().info(
            f'[experiment] cancelled: {experiment.experiment_mode} '
            f'after {actual_min:.2f}min, reverted to {experiment.prior_mode}'
        )

        response.ok = True
        response.message = ''
        response.ended_at_iso = ended_iso
        return response

    def _experiment_tick(self):
        """Phase 31 D-05/D-06: 1 Hz TTL check.

        Fires the auto-revert when monotonic clock crosses
        reverts_at_monotonic. Idle-tick (no active experiment) is a no-op.
        Auto-revert mirrors _handle_cancel_experiment but publishes
        source='experiment_revert' / event='ended'.
        """
        if self._active_experiment is None:
            return
        if self._monotonic() < self._active_experiment.reverts_at_monotonic:
            return

        experiment = self._active_experiment
        actual_min = (
            self._monotonic() - experiment.started_at_monotonic
        ) / 60.0

        # Revert via gated set_parameters.
        self._experiment_set_in_progress = True
        try:
            self.set_parameters([
                Parameter('active_mode', Parameter.Type.STRING, experiment.prior_mode)
            ])
        finally:
            self._experiment_set_in_progress = False

        self._active_experiment = None

        # 2026-05-09 hotfix: re-engage with the PRE-experiment duty, not
        # _last_published_duty (which holds the force-mode artificial value
        # 1.0 or 0.0). Without this, RH-in-band at revert pinned the duty at
        # the force value indefinitely.
        revert_seed = (
            self._pre_experiment_duty
            if self._pre_experiment_duty is not None
            else self._last_published_duty
        )
        self._pre_experiment_duty = None
        self._engage_pid_bumplessly(last_output=revert_seed)

        new_mv = self._resolve_active_mode()
        cm_msg = self._build_mode_msg(new_mv, source='experiment_revert')
        self._current_mode_pub.publish(cm_msg)
        self._publish_current_mode_json(new_mv, source='experiment_revert')
        self._pending_current_mode_republish = None

        self._publish_experiment_event('ended', experiment, actual_minutes=actual_min)

        self.get_logger().info(
            f'[experiment] auto-revert: {experiment.experiment_mode} '
            f'completed {actual_min:.2f}min, reverted to {experiment.prior_mode}'
        )

    def _check_force_mode_at_boot(self):
        """Phase 31 D-09: never come up running a force mode.

        If the runtime overlay (or YAML) carried active_mode='force-*', force
        it back to a safe baseline. Recovery target priority:
          (1) 'fruiting' if declared
          (2) first declared non-force mode name (sorted)
        Then publish a 'truncated' experiment_event so the bridge can close
        any in-flight DB row left by the pre-restart experiment.
        """
        current = self.get_parameter('active_mode').value
        if not isinstance(current, str) or not current.startswith('force-'):
            return
        declared = self._declared_mode_names()
        non_force = sorted(m for m in declared if not m.startswith('force-'))
        if 'fruiting' in non_force:
            safe = 'fruiting'
        elif non_force:
            safe = non_force[0]
        else:
            self.get_logger().error(
                f'[experiment] BOOT-RECOVERY: no non-force mode declared; '
                f'leaving active_mode={current!r} (UNSAFE — investigate).'
            )
            return
        self.get_logger().warn(
            f'[experiment] BOOT-RECOVERY: active_mode={current!r} on startup; '
            f'forcing to {safe!r} (D-09: never come up running a force mode). '
            f'Any in-flight experiment will be logged as truncated.'
        )
        self._experiment_set_in_progress = True
        try:
            self.set_parameters([
                Parameter('active_mode', Parameter.Type.STRING, safe)
            ])
        finally:
            self._experiment_set_in_progress = False
        # Publish truncated event so bridge closes any open DB row.
        self._publish_experiment_event('truncated', None, actual_minutes=None)

    def _default_now_hhmm(self) -> str:
        """Phase 30 D-21 — local-clock HH:MM string (fc1 system TZ).

        Plain method so tests can override the seam by reassigning the
        instance attribute `_now_hhmm` (set in `__init__`).
        """
        return datetime.now().strftime('%H:%M')

    def _scheduler_tick(self):
        """Phase 30 D-06..D-11 — evaluate schedule and swap mode if needed.

        Called once at startup (D-09 alignment) and every 30s thereafter (D-07).
        Compares the schedule-desired mode for the current local time against
        the active mode and, on mismatch, performs an in-process mode swap
        that mirrors `_handle_set_mode` minus the service-response path:

          1. set_parameters('active_mode', desired) — fires _validate_params
             which already vets declared mode names (single source of truth).
          2. Bumpless re-engage carrying the live duty (D-12 — no integrator
             kick when bands change underfoot).
          3. Synchronous current_mode publish with source='scheduler'.

        Manual override (D-10/D-11) self-heals at the next boundary because
        scheduler unconditionally fires whenever desired != active.

        Empty schedule = no-op. Gap (no window matches) keeps the current
        mode and emits a single debounced WARNING per (gap, mode) entry.

        Phase 31 D-08: scheduler is suppressed for the duration of an in-flight
        forcing experiment. After auto-revert, the next scheduler tick (within
        30s) re-aligns to the current wall clock window.
        """
        if self._active_experiment is not None:
            return
        raw = self.get_parameter('schedule_windows').value
        try:
            windows = scheduler.parse_schedule(raw)
        except ValueError:
            # Should be impossible — validator rejects malformed values — but
            # tolerate it defensively (e.g. corrupted overlay yaml on disk).
            return
        if not windows:
            return
        current = self.get_parameter('active_mode').value
        now_hhmm = self._now_hhmm()
        desired, matched = scheduler.compute_desired_mode(
            now_hhmm, windows, current
        )
        if matched is None:
            # Gap — debounce one WARN per (gap, current_mode) entry.
            key = ('gap', current)
            if self._last_scheduler_log != key:
                self.get_logger().warn(
                    f'[scheduler] no window matches {now_hhmm}; '
                    f'keeping current mode {current!r}'
                )
                self._last_scheduler_log = key
            return
        if desired == current:
            # Within-window, already correct (incl. manual override that
            # happens to match the desired mode for this window).
            self._last_scheduler_log = ('match', desired)
            return

        # Transition — set_parameters fires _validate_params (active_mode arm
        # checks declared modes); on accept, do bumpless re-engage and
        # synchronous current_mode publish with source='scheduler'.
        prev = current
        results = self.set_parameters([
            Parameter('active_mode', Parameter.Type.STRING, desired)
        ])
        if not results[0].successful:
            self.get_logger().error(
                f'[scheduler] set_parameters rejected mode={desired!r}: '
                f'{results[0].reason}'
            )
            return
        self._engage_pid_bumplessly(last_output=self._last_published_duty)
        new_mv = self._resolve_active_mode()
        msg = self._build_mode_msg(new_mv, source='scheduler')
        self._current_mode_pub.publish(msg)
        # Phase 29-07 — JSON sibling for the bridge.
        self._publish_current_mode_json(new_mv, source='scheduler')
        # Suppress the redundant next-tick republish queued by _validate_params.
        self._pending_current_mode_republish = None
        self.get_logger().info(
            f'[scheduler] transition: {prev} → {desired} '
            f'at {now_hhmm} '
            f"(window={matched['start']}-{matched['end']})"
        )
        self._last_scheduler_log = ('transition', desired)

    def _engage_pid_bumplessly(self, last_output: float):
        """D-12: bumpless engage with explicit carry-over duty.

        DEFER-29-01 fix (2026-05-08): default `0.15` removed — caller MUST
        pass an explicit value (typically `self._last_published_duty`).
        Hardcoded preload combined with zero error (RH in-band at re-engage
        time) caused humidifier_duty to pin at 0.15 indefinitely.
        The set_mode service handler passes `last_output=current_duty` so a
        band-change mid-flight doesn't kick the integrator; the tick loop
        passes `self._last_published_duty` so post-restart re-engage
        continues the prior steady state.
        """
        self._pid.set_auto_mode(True, last_output=last_output)
        self._pid_engaged = True
        # 999.32: reset D filter so the filtered derivative doesn't carry
        # stale state across re-engage. Starts at 0 so the filter ramps in
        # naturally as new d_input samples flow.
        self._d_filtered = 0.0
        self.get_logger().info(f'PID engaged with bumpless preload: duty={last_output:.3f}')

    def _disengage_pid(self):
        if self._pid_engaged:
            self._pid.set_auto_mode(False)
            self._pid_engaged = False

    def _publish_duty(self, duty):
        duty = max(0.0, min(1.0, float(duty)))
        # D-12: stash post-clamp value so set_mode bumpless re-engage carries
        # the actual operating duty (not the pre-clamp PID output).
        self._last_published_duty = duty
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
        # 260529-ean: stamp on EVERY publish path so the heartbeat clock is reset
        # by warmup, grace-exit, flip, and heartbeat publishes alike.
        self._last_sensor_health_publish = self.get_clock().now()

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
        # Phase 28 D-15: drain a pending current_mode republish queued by
        # _validate_params. Done at the top of every tick so the republish lands
        # on the FIRST tick after the SetParameters batch is applied.
        if self._pending_current_mode_republish is not None:
            (source,) = self._pending_current_mode_republish
            self._pending_current_mode_republish = None
            self._publish_current_mode(source=source)
        # Phase 29 — drain Tier B + Tier C deferred republishes (Pattern C).
        if self._pending_alerter_overrides_republish is not None:
            (source,) = self._pending_alerter_overrides_republish
            self._pending_alerter_overrides_republish = None
            self._publish_alerter_overrides(source=source)
        if self._pending_alerter_globals_republish is not None:
            (source,) = self._pending_alerter_globals_republish
            self._pending_alerter_globals_republish = None
            self._publish_alerter_globals(source=source)

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

        # 260529-ean: heartbeat republish — keeps alerter sht30LastSeenMs alive for
        # a healthy, stable sensor that never triggers a freshness flip.
        # Guarded on is-not-None: the warmup WARN publish stamps the timestamp first,
        # so the heartbeat only fires after at least one real publish has occurred.
        # _publish_sensor_health stamps _last_sensor_health_publish, so the interval
        # is measured from the last publish regardless of whether it was a flip or heartbeat.
        if (self._last_sensor_health_publish is not None
                and (self.get_clock().now() - self._last_sensor_health_publish).nanoseconds
                / 1e9 >= SENSOR_HEALTH_HEARTBEAT_SEC):
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

            # Phase 31 D-02: force_duty short-circuit. When the active mode
            # declares a finite force_duty, bypass PID + Mode C entirely and
            # emit the literal duty value. Park the integrator (set_auto_mode
            # False) so it does not accumulate during the experiment; D-12
            # bumpless re-engage on revert via _engage_pid_bumplessly carries
            # last_published_duty into the next closed-loop tick. Telemetry
            # (humidity_target / pid_output) reflects the literal commanded
            # duty so the chart shows the operator-commanded value cleanly,
            # not stale PID state.
            if not isnan(mode.force_duty):
                if self._pid.auto_mode:
                    self._pid.set_auto_mode(False)
                self._pid_engaged = False
                self._publish_duty(mode.force_duty)
                ht_msg = Float32()
                ht_msg.data = float(mode.force_duty)
                self._humidity_target_pub.publish(ht_msg)
                po_msg = Float32()
                po_msg.data = float(mode.force_duty)
                self._pid_output_pub.publish(po_msg)
                # Update _last_tick_ts so the eventual revert sees a sane dt.
                self._last_tick_ts = now
                return

            if not self._pid_engaged:
                # DEFER-29-01 fix: pass current operating duty so post-restart
                # re-engage continues the prior steady state instead of
                # pinning at the old hardcoded 0.15 default.
                self._engage_pid_bumplessly(self._last_published_duty)

            # Live-reload PID gains from ROS params each tick (HUMID-03)
            self._pid.Kp = self.get_parameter('pid_kp').value
            self._pid.Ki = self.get_parameter('pid_ki').value
            self._pid.Kd = self.get_parameter('pid_kd').value

            # Phase 28 D-10: ramp toward defended band edge (not target midpoint).
            self._ramp_setpoint_to_band(dt, mode)
            rh = self.current_humidity

            # Phase 28 D-09 + quadratic low-side feather (calibration 2026-06-21).
            # error_pct < 0 drives duty up via PID. Below target, error ramps
            # quadratically from 0 at target to -b/2 at band_low, then continues
            # linearly below band_low. The piecewise join at d=b is C1 (value AND
            # slope match), so the controller climbs gently from the setpoint
            # instead of stepping at the floor — the step was the source of the
            # derivative kick that slammed duty to 100%. b = band half-width in
            # pct (= humidity_tolerance * 100). With b<=0 the feather degenerates
            # to the plain linear projection.
            if rh < mode.target:
                d = (mode.target - rh) * 100.0          # pct below target (>0)
                b = (mode.target - mode.band_low) * 100.0
                if b > 0 and d <= b:
                    error_pct = -(d * d) / (2.0 * b)     # quadratic feather
                else:
                    error_pct = -(d - b / 2.0)           # linear, C1 with feather
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
                    # 999.32: reset D filter on Mode C exit; the new d_input
                    # baseline starts fresh.
                    self._d_filtered = 0.0
                # 999.49: in-band integrator decay. Phase 28 D-09 feeds
                # error_pct=0 when RH is in-band, which freezes P/I/D at
                # whatever values they reached during the last OOB excursion.
                # Duty then pins at stale I-term forever, causing the chamber
                # to over-humidify (or under-humidify) at residue energy.
                # Exponentially decay I when in-band so the controller trends
                # toward the chamber's passive equilibrium. tau=0 disables.
                # Applied BEFORE the PID call so the PID's own update
                # (which adds Ki*0*dt = 0 in this branch) sees the decayed
                # value as the integrator state, and output = decayed I.
                decay_tau = self.get_parameter('pid_integrator_decay_tau').value
                if decay_tau > 0 and dt > 0 and error_pct == 0.0:
                    self._pid._integral *= exp(-dt / decay_tau)
                raw_pid_output = self._pid(error_pct, dt=dt)
                # 999.32: replace the PID's raw derivative term with a
                # low-pass-filtered version. tau=0 disables filtering.
                # alpha = dt/(tau+dt); d_filt += alpha * (d_raw - d_filt).
                # Vendored simple_pid lacks native derivative filtering, so
                # we filter externally and recompute the clamped output.
                tau = self.get_parameter('pid_derivative_filter_tau').value
                if tau > 0 and dt > 0:
                    p_term, i_term, d_raw = self._pid.components
                    alpha = dt / (tau + dt)
                    self._d_filtered = alpha * d_raw + (1 - alpha) * self._d_filtered
                    raw_pid_output = max(0.0, min(1.0, p_term + i_term + self._d_filtered))
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
