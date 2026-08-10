"""Stateful control law, extracted from ``run_closed_loop`` (MUSHY-59).

This is the SAME arithmetic ``fc_controller._control_loop()`` runs, minus the
ROS plumbing: band/feather projection (shared, ``fc_core.control_kernel``),
Mode C open-loop bypass with integrator freeze, bumpless re-engage, the
999.49 in-band integrator decay, the 999.32 derivative low-pass, and the
MUSHY-57 faded feedforward bias.

Extracted so a validator can drive the real control law directly (feeding it
RECORDED RH and comparing against RECORDED ``fc.pid_output``) without
reimplementing it -- a reimplementation would validate itself, not the
deployed controller. ``run_closed_loop`` now uses this class too, so there is
exactly one implementation of the law.

The slew limiter (``apply_slew``) is deliberately NOT part of this class: it
is a simulator-only shaping step with no counterpart in ``fc_controller.py``
(the real controller calls ``self._publish_duty(duty)`` straight off the law,
no slew stage), so it does not belong in the extracted law.
"""
from dataclasses import dataclass
from math import exp

from fc_core.control_kernel import BandSpec, duty_bias_factor, project_error_pct
from fc_core.vendor.simple_pid import PID


@dataclass
class Gains:
    kp: float = 0.36
    ki: float = 0.001
    kd: float = 4.0
    derivative_filter_tau: float = 60.0
    integrator_decay_tau: float = 1800.0
    bypass_threshold: float = 0.05


DEFAULT_GAINS = Gains()


class ControlLoop:
    """Reconstructed control law with its own PID + derivative-filter state.

    ``step(rh_frac, dt)`` mirrors one tick of ``fc_controller._control_loop``
    and returns ``(duty, raw_pid_output)`` where ``raw_pid_output`` is the
    PRE-bias quantity actually published to ``fc.pid_output`` (see
    ``fc_controller.py`` ~line 1821: ``max(0, min(1, raw_pid_output))``), and
    ``duty`` is the (possibly bias-adjusted) commanded duty.
    """

    def __init__(self,
                 band: BandSpec,
                 gains: Gains = DEFAULT_GAINS,
                 target: float = 0.90,
                 duty_bias: float = 0.0):
        self.band = band
        self.gains = gains
        self.target = target
        self.duty_bias = duty_bias

        self.pid = PID(gains.kp, gains.ki, gains.kd,
                        setpoint=0.0, output_limits=(0.0, 1.0))
        self.d_filtered = 0.0

    def step(self, rh_frac: float, dt: float):
        band = self.band
        gains = self.gains

        projected = project_error_pct(rh_frac, band)
        if projected is None:
            # defend_side='low' freeze: clamp duty 0, disengage the PID.
            if self.pid.auto_mode:
                self.pid.set_auto_mode(False)
            return 0.0, 0.0

        error_pct = projected

        # Mode C bypass: nearest defended edge (fc_controller ~line 1739).
        if band.defend_side == 'low':
            nearest = band.band_low
        elif band.defend_side == 'high':
            nearest = band.band_high
        else:
            nearest = band.band_low if rh_frac <= self.target else band.band_high
        edge_pct = abs(rh_frac - nearest) * 100.0
        bypass_pct = gains.bypass_threshold * 100.0

        if edge_pct > bypass_pct and rh_frac < nearest:
            if self.pid.auto_mode:
                self.pid.set_auto_mode(False)
            return 1.0, 1.0

        if not self.pid.auto_mode:
            self.pid.set_auto_mode(True, last_output=1.0)
            self.d_filtered = 0.0

        # 999.49 in-band integrator decay, applied BEFORE the PID call.
        if gains.integrator_decay_tau > 0 and dt > 0 and error_pct == 0.0:
            self.pid._integral *= exp(-dt / gains.integrator_decay_tau)

        raw_pid_output = self.pid(error_pct, dt=dt)

        # 999.32 external derivative low-pass.
        if gains.derivative_filter_tau > 0 and dt > 0:
            p_term, i_term, d_raw = self.pid.components
            alpha = dt / (gains.derivative_filter_tau + dt)
            self.d_filtered = alpha * d_raw + (1 - alpha) * self.d_filtered
            raw_pid_output = max(0.0, min(1.0, p_term + i_term + self.d_filtered))
        duty = raw_pid_output

        # Feedforward bias -- PID branch only, mirroring fc_controller.
        # MUSHY-57: faded across the upper band so it can never floor output.
        if self.duty_bias > 0.0:
            duty = max(0.0, min(
                1.0, duty + self.duty_bias * duty_bias_factor(rh_frac, band)))

        return duty, raw_pid_output
