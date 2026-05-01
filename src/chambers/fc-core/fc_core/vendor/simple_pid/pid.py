# MIT License
#
# Copyright (c) 2018 Martin Lundberg
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# Vendored from simple-pid 2.0.0 (https://github.com/m-lundberg/simple-pid)
# Do not modify this file — update by re-vendoring from upstream.

import time


def _clamp(value, limits):
    lower, upper = limits
    if value is None:
        return None
    if upper is not None and value > upper:
        return upper
    if lower is not None and value < lower:
        return lower
    return value


class PID:
    """A simple PID controller with anti-windup, derivative-on-measurement,
    bumpless transfer via set_auto_mode, and optional output limits."""

    def __init__(
        self,
        Kp=1.0,
        Ki=0.0,
        Kd=0.0,
        setpoint=0.0,
        sample_time=0.01,
        output_limits=(None, None),
        auto_mode=True,
        proportional_on_measurement=False,
        differential_on_measurement=True,
        error_map=None,
        time_fn=None,
        starting_output=0.0,
    ):
        self.Kp = Kp
        self.Ki = Ki
        self.Kd = Kd
        self.setpoint = setpoint
        self.sample_time = sample_time
        self.output_limits = output_limits
        self.auto_mode = auto_mode
        self.proportional_on_measurement = proportional_on_measurement
        self.differential_on_measurement = differential_on_measurement
        self.error_map = error_map
        self.time_fn = time_fn if time_fn is not None else time.monotonic

        self._min_output, self._max_output = output_limits

        self._proportional = 0.0
        self._integral = 0.0
        self._derivative = 0.0

        self._last_time = None
        self._last_output = starting_output
        self._last_error = 0.0
        self._last_input = None

        if auto_mode:
            self._integral = starting_output - _clamp(starting_output, output_limits)
        else:
            self._integral = 0.0

    def __call__(self, input_, dt=None):
        """Compute and return a new output value.

        :param input_: the current value of the process variable
        :param dt: elapsed time in seconds since last call; if None, sample_time is used
        """
        if not self.auto_mode:
            return self._last_output

        now = self.time_fn()
        if dt is None:
            if self._last_time is None:
                dt = 1e-16
            else:
                dt = now - self._last_time
                if self.sample_time is not None and dt < self.sample_time and dt > 0:
                    return self._last_output
        elif dt <= 0:
            raise ValueError('dt has negative value {}, must be positive'.format(dt))

        error = self.setpoint - input_
        if self.error_map is not None:
            error = self.error_map(error)

        d_input = input_ - (self._last_input if self._last_input is not None else input_)
        d_error = error - self._last_error

        # P term
        if self.proportional_on_measurement:
            self._proportional -= self.Kp * d_input
        else:
            self._proportional = self.Kp * error

        # I term with anti-windup (clamping)
        self._integral += self.Ki * error * dt

        # Clamp integral to prevent windup
        self._integral = _clamp(self._integral, self.output_limits)

        # D term
        if self.differential_on_measurement:
            self._derivative = -self.Kd * d_input / dt if dt else 0.0
        else:
            self._derivative = self.Kd * d_error / dt if dt else 0.0

        output = self._proportional + self._integral + self._derivative

        # Clamp output
        output = _clamp(output, self.output_limits)

        self._last_output = output
        self._last_input = input_
        self._last_error = error
        self._last_time = now

        return output

    @property
    def components(self):
        """Return the P, I, D components of the last computation."""
        return self._proportional, self._integral, self._derivative

    @property
    def tunings(self):
        """Return the tunings (Kp, Ki, Kd)."""
        return self.Kp, self.Ki, self.Kd

    @tunings.setter
    def tunings(self, tunings):
        self.Kp, self.Ki, self.Kd = tunings

    @property
    def output_limits(self):
        return self._min_output, self._max_output

    @output_limits.setter
    def output_limits(self, limits):
        if limits is None:
            self._min_output, self._max_output = None, None
            return
        min_output, max_output = limits
        if None not in limits and max_output < min_output:
            raise ValueError('lower limit must be less than upper limit')
        self._min_output = min_output
        self._max_output = max_output
        self._integral = _clamp(self._integral, self.output_limits)
        self._last_output = _clamp(self._last_output, self.output_limits)

    def set_auto_mode(self, enabled, last_output=None):
        """Enable or disable the PID controller.

        When enabling, the integrator is back-computed from last_output so
        the very next __call__ returns approximately last_output (bumpless transfer).
        """
        if enabled and not self.auto_mode:
            # Switching from manual to auto — bumpless transfer
            self.auto_mode = True
            self._last_input = None
            self._last_error = 0.0
            if last_output is not None:
                self._integral = last_output
                self._proportional = 0.0
                self._integral = _clamp(self._integral, self.output_limits)
            else:
                self._integral = 0.0
                self._proportional = 0.0
        elif not enabled:
            self.auto_mode = False
            if last_output is not None:
                self._last_output = last_output

    def reset(self):
        """Reset the PID controller state."""
        self._proportional = 0.0
        self._integral = 0.0
        self._derivative = 0.0
        self._last_time = None
        self._last_output = 0.0
        self._last_error = 0.0
        self._last_input = None
