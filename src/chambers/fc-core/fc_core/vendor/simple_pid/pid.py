# The MIT License (MIT)
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
# Vendored from https://github.com/m-lundberg/simple-pid at tag v2.0.0.
# Do NOT modify — upstream is the source of truth.

import time


def _clamp(value, limits):
    lower, upper = limits
    if value is None:
        return None
    elif (upper is not None) and (value > upper):
        return upper
    elif (lower is not None) and (value < lower):
        return lower
    return value


class PID:
    """A simple PID controller.

    This PID controller is based on the PID algorithm as described in:
    https://en.wikipedia.org/wiki/PID_controller

    The controller supports:
    - Bumpless transfer: set_auto_mode(True, last_output=X) pre-loads the
      integrator so the first call returns approximately X (with zero error).
    - Anti-windup: integral is clamped to output_limits range.
    - Derivative on measurement: derivative is computed on the measurement
      rather than the error to avoid derivative kick on setpoint changes.
    - Proportional on measurement: proportional term can be computed on the
      measurement rather than the error.
    """

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
        self.Kp, self.Ki, self.Kd = Kp, Ki, Kd
        self.setpoint = setpoint
        self.sample_time = sample_time
        self.auto_mode = auto_mode
        self.proportional_on_measurement = proportional_on_measurement
        self.differential_on_measurement = differential_on_measurement
        self.error_map = error_map

        # Initialise internal state before output_limits setter runs (setter clamps _integral)
        self._min_output, self._max_output = None, None
        self._last_input = None
        self._last_output = None
        self._last_error = None
        self._last_time = None
        self._proportional = 0.0
        self._integral = 0.0
        self._derivative = 0.0

        if time_fn is not None:
            self.time_fn = time_fn
        else:
            self.time_fn = time.monotonic

        # Now safe to invoke the property setter
        self.output_limits = output_limits

        if auto_mode:
            self.set_auto_mode(True, last_output=starting_output)

    @property
    def output_limits(self):
        return (self._min_output, self._max_output)

    @output_limits.setter
    def output_limits(self, limits):
        if limits is None:
            self._min_output, self._max_output = None, None
            return

        min_output, max_output = limits

        if (None not in limits) and (max_output < min_output):
            raise ValueError('lower limit must be less than upper limit')

        self._min_output = min_output
        self._max_output = max_output

        # Clamp integral to new limits
        self._integral = _clamp(self._integral, self.output_limits)
        self._last_output = _clamp(self._last_output, self.output_limits)

    def __call__(self, input_, dt=None):
        """Update the PID controller.

        Call the PID controller with *input_* and calculate and return a
        control output if sample_time seconds has passed since the last update.
        If no new output is calculated, return the previous output instead (or
        None if no previous output is available).

        :param dt: If set, uses this value for timestep instead of real elapsed time.
            This is useful for simulation.
        """
        if not self.auto_mode:
            return self._last_output

        now = self.time_fn()
        if dt is None:
            if self._last_time is None:
                dt = 1e-16
            else:
                dt = now - self._last_time
                if self.sample_time is not None and dt < self.sample_time and self._last_output is not None:
                    # Only update every sample_time seconds
                    return self._last_output
        elif dt <= 0:
            raise ValueError('dt has negative value {}, must be positive'.format(dt))

        # Compute error terms
        error = self.setpoint - input_
        d_input = input_ - (self._last_input if (self._last_input is not None) else input_)
        d_error = error - (self._last_error if (self._last_error is not None) else error)

        # Apply error_map if provided
        if self.error_map is not None:
            error = self.error_map(error)

        # Compute individual terms
        if not self.proportional_on_measurement:
            # Regular proportional-on-error
            self._proportional = self.Kp * error
        else:
            # Proportional on measurement (no kick on setpoint change)
            self._proportional -= self.Kp * d_input

        if self.Ki != 0 and dt > 0:
            self._integral += self.Ki * error * dt
            self._integral = _clamp(self._integral, self.output_limits)

        if self.Kd != 0 and dt > 0:
            if self.differential_on_measurement:
                self._derivative = -self.Kd * d_input / dt
            else:
                self._derivative = self.Kd * d_error / dt

        # Compute output
        output = self._proportional + self._integral + self._derivative
        output = _clamp(output, self.output_limits)

        # Keep track of state
        self._last_output = output
        self._last_input = input_
        self._last_error = error
        self._last_time = now

        return output

    def __repr__(self):
        return (
            '{self.__class__.__name__}('
            'Kp={self.Kp!r}, Ki={self.Ki!r}, Kd={self.Kd!r}, '
            'setpoint={self.setpoint!r}, sample_time={self.sample_time!r}'
            ')'.format(self=self)
        )

    @property
    def components(self):
        """The P-, I- and D-terms from the last computation as named tuple fields."""
        return self._proportional, self._integral, self._derivative

    @property
    def tunings(self):
        """The tunings used by the controller as a tuple: (Kp, Ki, Kd)."""
        return self.Kp, self.Ki, self.Kd

    @tunings.setter
    def tunings(self, tunings):
        """Set the PID tunings."""
        self.Kp, self.Ki, self.Kd = tunings

    def set_auto_mode(self, enabled, last_output=None):
        """Enable or disable the PID controller.

        This function also supports bumpless transfer from manual to auto mode:
        if ``last_output`` is given when enabling auto mode, the integral term
        is back-calculated to produce that output from the next call, avoiding
        a sudden bump in the output when switching to auto mode.

        :param enabled: Whether auto mode should be enabled, boolean
        :param last_output: The last output, or the output that should be
            reproduced when switching to auto mode. If set, the integral term
            will be back-calculated to produce this output (bumpless transfer).
            This is the pre-load contract: with zero error, the first call
            returns approximately last_output.
        """
        if enabled and not self.auto_mode:
            # Switching to auto mode with bumpless transfer
            self._last_input = None
            self._last_error = None
            self._last_time = None
            self._proportional = 0.0
            self._derivative = 0.0

            if last_output is not None:
                # Back-calculate integral so that the first output ≈ last_output
                # when proportional and derivative terms are zero (zero error).
                # The integral starts at last_output clamped to output_limits.
                self._integral = _clamp(last_output, self.output_limits)
            else:
                self._integral = 0.0

            self._last_output = _clamp(last_output, self.output_limits) if last_output is not None else 0.0

        elif not enabled and self.auto_mode:
            # Switching to manual mode — freeze integrator
            pass

        self.auto_mode = enabled

    def reset(self):
        """Reset the PID controller internals.

        This sets each term to 0 as well as clearing the integral, the last output and the
        last input (as if the controller never sensed anything).
        """
        self._proportional = 0.0
        self._integral = 0.0
        self._derivative = 0.0

        self._integral = _clamp(self._integral, self.output_limits)

        self._last_time = self.time_fn()
        self._last_output = None
        self._last_input = None
        self._last_error = None
