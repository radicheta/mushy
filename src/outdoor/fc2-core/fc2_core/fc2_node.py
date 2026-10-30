"""fc2_controller: pulses the FC-2 sprinkler valve on a weather-driven schedule.

Thin rclpy wiring around the pure modules (rule, scheduler, params, weather,
valve). The valve is closed at start, at shutdown and on any exception path.
"""
import dataclasses
from datetime import datetime
import math
import os
import socket
import threading
import time
from zoneinfo import ZoneInfo

from fc2_core import weather
from fc2_core.params import (DEFAULT_OVERLAY_PATH, params_from_mapping, STARTUP_ONLY,
                             validate, write_overlay)
from fc2_core.rule import decide, MODE_CODES, RuleParams
from fc2_core.scheduler import BurstScheduler, duty_pct
from fc2_core.valve import GpioValve, GuardedValve, SimValve
from rcl_interfaces.msg import SetParametersResult
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool, Float32, Int32

# Typed defaults: ROS infers each parameter's type from these and rejects
# values of another type (floats are written as floats on purpose).
DEFAULTS = {
    **{f.name: f.default for f in dataclasses.fields(RuleParams)},
    'weather_poll_sec': 900.0,
    'latitude': -34.5165641,
    'longitude': -55.0982273,
    'timezone': 'America/Montevideo',
    'valve_gpio_pin': -1,
    'valve_active_low': False,
    'actuator_simulation_mode': True,
}
PERSISTED = tuple(k for k in DEFAULTS if k not in STARTUP_ONLY)
WEATHER_FIELDS = (('temperature', 'temperature_c'), ('humidity', 'humidity_pct'),
                  ('wind', 'wind_kmh'), ('precipitation', 'precipitation_mm'),
                  ('et0', 'et0_mm'))


def clock_synced() -> bool:
    """Return True once systemd-timesyncd has synced the clock (the Pi has no RTC)."""
    return os.path.exists('/run/systemd/timesync/synchronized')


def sd_notify(msg: bytes) -> None:
    """Minimal sd_notify; a no-op when not run under systemd."""
    addr = os.environ.get('NOTIFY_SOCKET')
    if not addr:
        return
    if addr.startswith('@'):
        addr = '\0' + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(addr)
            s.sendall(msg)
    except OSError:
        pass  # a missed ping is what the systemd watchdog is for


def _node_param_error(v: dict):
    for k, x in v.items():
        if isinstance(x, float) and not math.isfinite(x):
            return f'{k} must be finite'
    if v['weather_poll_sec'] <= 0:
        return 'weather_poll_sec must be positive'
    if not -90.0 <= v['latitude'] <= 90.0 or not -180.0 <= v['longitude'] <= 180.0:
        return 'latitude/longitude out of range'
    try:
        ZoneInfo(v['timezone'])
    except Exception:
        return f'unknown timezone {v["timezone"]!r}'
    return validate(params_from_mapping(v))


class Fc2Controller(Node):
    """Weather rule -> burst scheduler -> guarded valve, once a second."""

    def __init__(self, *, fetch_fn=weather.fetch, valve=None, overlay_path=None,
                 clock_synced_fn=None, now_mono=time.monotonic, **node_kwargs):
        """Declare typed params, build the valve (closed) and start timers."""
        super().__init__('fc2_controller', **node_kwargs)
        for name, default in DEFAULTS.items():
            self.declare_parameter(name, default)
        self._values = {k: self.get_parameter(k).value for k in DEFAULTS}
        err = _node_param_error(self._values)
        if err:
            raise ValueError(f'fc2_controller: bad startup settings: {err}')
        self._rule = params_from_mapping(self._values)
        self._overlay_path = overlay_path or os.environ.get(
            'FC2_RUNTIME_OVERLAY', DEFAULT_OVERLAY_PATH)
        self._fetch_fn = fetch_fn
        self._clock_synced = clock_synced_fn or clock_synced
        self._now = now_mono

        if valve is None:
            if self._values['actuator_simulation_mode']:
                valve = GuardedValve(SimValve(), self._rule.max_open_sec)
            elif self._values['valve_gpio_pin'] == -1:
                raise ValueError('fc2_controller: valve_gpio_pin is -1 (unset) and '
                                 'actuator_simulation_mode is false; refusing to start')
            else:
                valve = GuardedValve(GpioValve(self._values['valve_gpio_pin'],
                                               self._values['valve_active_low']),
                                     self._rule.max_open_sec)
        self.valve = valve
        self.valve.set_open(False)
        self._open = False
        self._trip_seen = False
        self.last_decision = None
        self._scheduler = BurstScheduler(self._now())

        self._reading = None
        self._lock = threading.Lock()
        self._stop = threading.Event()

        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                             reliability=ReliabilityPolicy.RELIABLE,
                             history=HistoryPolicy.KEEP_LAST)
        self._valve_pub = self.create_publisher(Bool, 'fc2/valve', latched)
        self._valve_pub.publish(Bool(data=False))
        self._duty_pub = self.create_publisher(Float32, 'fc2/duty_pct_1h', 10)
        self._rate_pub = self.create_publisher(Float32, 'fc2/bursts_per_hour', 10)
        self._mode_pub = self.create_publisher(Int32, 'fc2/mode', 10)
        self._weather_pubs = {
            t: self.create_publisher(Float32, f'fc2/weather/{t}', 10)
            for t, _ in WEATHER_FIELDS + (('age_sec', None),)}

        self.add_on_set_parameters_callback(self._on_set_parameters)
        self.create_timer(1.0, self.control_tick)
        self.create_timer(60.0, self.publish_telemetry)
        threading.Thread(target=self._weather_loop, name='fc2-weather',
                         daemon=True).start()
        self.get_logger().info(
            f'fc2_controller up: valve={type(self.valve.inner).__name__}, '
            f'overlay={self._overlay_path}')

    def control_tick(self) -> None:
        """One control step; closes the valve on any exception, then pings systemd."""
        try:
            now = self._now()
            with self._lock:
                reading = self._reading
            tz = self._values['timezone']
            local = datetime.now(ZoneInfo(tz)).time() if self._clock_synced() else None
            p = self._rule
            d = decide(reading, now, local, p)
            self.last_decision = d
            want = self._scheduler.tick(now, d.bursts_per_hour, p.pulse_sec)
            if want != self._open:
                self.valve.set_open(want)
                self._open = want
                self._valve_pub.publish(Bool(data=want))
            if self.valve.tripped and not self._trip_seen:
                self._trip_seen = True
                self.get_logger().warning(
                    f'max-on guard tripped: valve forced closed after '
                    f'{self.valve.max_open_sec:g}s')
        except BaseException:
            self.valve.set_open(False)
            self._open = False
            raise
        sd_notify(b'WATCHDOG=1')

    def publish_telemetry(self) -> None:
        """Publish duty, rate, mode and (once a reading exists) the weather."""
        now = self._now()
        self._duty_pub.publish(Float32(data=duty_pct(list(self.valve.intervals), now)))
        d = self.last_decision
        if d is not None:
            self._rate_pub.publish(Float32(data=float(d.bursts_per_hour)))
            self._mode_pub.publish(Int32(data=MODE_CODES[d.mode]))
        with self._lock:
            r = self._reading
        if r is not None:
            for topic, attr in WEATHER_FIELDS:
                self._weather_pubs[topic].publish(Float32(data=float(getattr(r, attr))))
            self._weather_pubs['age_sec'].publish(Float32(data=float(now - r.fetched_mono)))

    def _weather_loop(self) -> None:
        failing = False
        while not self._stop.is_set():
            v = self._values
            try:
                reading = self._fetch_fn(v['latitude'], v['longitude'])
                with self._lock:
                    self._reading = reading
                if failing:
                    self.get_logger().info('weather fetch recovered')
                failing = False
            except Exception as e:  # keep the old reading
                if not failing:
                    self.get_logger().warning(f'weather fetch failed: {e!r}')
                failing = True
            self._stop.wait(v['weather_poll_sec'])

    def _on_set_parameters(self, params):
        candidate = dict(self._values)
        for prm in params:
            if prm.name in STARTUP_ONLY:
                return SetParametersResult(
                    successful=False, reason=f'{prm.name} is startup-only')
            if prm.name in candidate:
                candidate[prm.name] = prm.value
        err = _node_param_error(candidate)
        if err:
            return SetParametersResult(successful=False, reason=err)
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self._overlay_path)),
                        exist_ok=True)
            write_overlay(self._overlay_path, {k: candidate[k] for k in PERSISTED})
        except Exception as e:
            return SetParametersResult(successful=False,
                                       reason=f'overlay write failed: {e}')
        self._values = candidate
        self._rule = params_from_mapping(candidate)
        self.valve.max_open_sec = self._rule.max_open_sec
        return SetParametersResult(successful=True)

    def destroy_node(self):
        """Close the valve before tearing down the node."""
        self._stop.set()
        try:
            self.valve.set_open(False)
            self._open = False
        finally:
            super().destroy_node()


def main(args=None):
    """Entry point for fc2_controller."""
    rclpy.init(args=args)
    node = None
    try:
        node = Fc2Controller()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.valve.set_open(False)
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
