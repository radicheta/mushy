"""FC-2 valve: GPIO layer, independent max-on guard, and the valve-off command.

No ROS imports. RPi.GPIO is imported lazily so this runs on a non-Pi host.
"""
import os
import sys
import threading
import time
from typing import List, Optional, Tuple

import yaml

from fc2_core.params import DEFAULT_OVERLAY_PATH, usable_overlay

HISTORY_SEC = 2 * 3600.0


class SimValve:
    def __init__(self):
        self.is_open = False

    def set_open(self, open_: bool) -> None:
        self.is_open = bool(open_)


class GpioValve:
    """Output pin that is created already at the off level (never on, even briefly)."""

    def __init__(self, pin: int, active_low: bool):
        import RPi.GPIO as GPIO  # lazy: only exists on the Pi
        self._gpio = GPIO
        self._pin = pin
        self._on = GPIO.LOW if active_low else GPIO.HIGH
        self._off = GPIO.HIGH if active_low else GPIO.LOW
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(pin, GPIO.OUT, initial=self._off)

    def set_open(self, open_: bool) -> None:
        self._gpio.output(self._pin, self._on if open_ else self._off)

    def close(self) -> None:
        """Drive off, then release the pin."""
        try:
            self.set_open(False)
        finally:
            self._gpio.cleanup(self._pin)


class GuardedValve:
    """Wraps a valve with a hard max-on timer that runs in its own thread, so a
    hung control loop still closes the valve."""

    def __init__(self, inner, max_open_sec: float, *, clock=time.monotonic,
                 timer_factory=threading.Timer):
        self.inner = inner
        self.max_open_sec = max_open_sec
        self.tripped = False
        self.trip_count = 0
        self.intervals: List[Tuple[float, Optional[float]]] = []
        self._clock = clock
        self._timer_factory = timer_factory
        self._timer = None
        self._lock = threading.Lock()

    def _close_interval(self, now: float) -> None:
        if self.intervals and self.intervals[-1][1] is None:
            self.intervals[-1] = (self.intervals[-1][0], now)

    def _trip(self) -> None:
        with self._lock:
            self._timer = None
            self.tripped = True
            self.trip_count += 1
            try:
                self.inner.set_open(False)
            finally:
                self._close_interval(self._clock())

    def set_open(self, open_: bool) -> None:
        with self._lock:
            now = self._clock()
            if open_:
                if self._timer is not None:  # already open: window is not extended
                    return
                timer = self._timer_factory(self.max_open_sec, self._trip)
                # Non-daemon on purpose: interpreter exit must wait for the
                # guard so a still-open valve is closed within max_open_sec.
                timer.daemon = False
                try:
                    self.inner.set_open(True)
                    timer.start()
                except BaseException:
                    timer.cancel()
                    self.inner.set_open(False)
                    raise
                self._timer = timer
                self.intervals = [i for i in self.intervals
                                  if i[1] is None or i[1] >= now - HISTORY_SEC]
                self.intervals.append((now, None))
            else:
                if self._timer is not None:
                    self._timer.cancel()
                    self._timer = None
                try:
                    self.inner.set_open(False)
                finally:
                    self._close_interval(now)


def _params(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)['/**']['ros__parameters']


def _resolve(base_path: str, overlay_path: str) -> dict:
    p = _params(base_path)
    if usable_overlay(overlay_path):
        p = {**p, **_params(overlay_path)}
    return p


def _valve_settings(p: dict) -> Tuple[int, bool, bool]:
    """(pin, active_low, simulation) with strict types, else ValueError.

    No coercion: bool('false') is True, which would invert the off level.
    """
    pin = p['valve_gpio_pin']
    active_low = p['valve_active_low']
    sim = p.get('actuator_simulation_mode', False)
    if type(pin) is not int:
        raise ValueError(f'valve_gpio_pin must be an int, got {pin!r}')
    for name, v in (('valve_active_low', active_low),
                    ('actuator_simulation_mode', sim)):
        if not isinstance(v, bool):
            raise ValueError(f'{name} must be an unquoted bool, got {v!r}')
    return pin, active_low, sim


def resolve_valve_config(base_path: str, overlay_path: str) -> Tuple[int, bool]:
    pin, active_low, _ = _valve_settings(_resolve(base_path, overlay_path))
    return pin, active_low


def _default_config() -> str:
    try:
        from ament_index_python.packages import get_package_share_directory
        return os.path.join(get_package_share_directory('fc2_core'),
                            'config', 'fc2_config.yaml')
    except Exception:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            '..', 'config', 'fc2_config.yaml')


def valve_off_main() -> None:
    """fc2_valve_off: drive the valve pin to its off level and exit.

    Exit 0 on success or when there is nothing to drive (simulation mode,
    pin -1). Exit 1, with the reason on stderr and GPIO untouched, if the
    config cannot be read or holds a mistyped value; non-zero if GPIO fails.
    The pin is deliberately not cleaned up: it stays driven off.
    """
    try:
        base = os.environ.get('FC2_CONFIG') or _default_config()
        overlay = os.environ.get('FC2_RUNTIME_OVERLAY', DEFAULT_OVERLAY_PATH)
        pin, active_low, sim = _valve_settings(_resolve(base, overlay))
        if sim or pin == -1:
            sys.exit(0)
        GpioValve(pin, active_low).set_open(False)
    except SystemExit:
        raise
    except BaseException as e:  # noqa: B902 - never a traceback
        print(f'fc2_valve_off: {type(e).__name__}: {e}', file=sys.stderr)
        sys.exit(1)
    sys.exit(0)
