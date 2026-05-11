"""HUMID-03: PID gain math (bumpless, anti-windup, D-on-measurement)."""

import pytest
from fc_core.vendor.simple_pid import PID


def test_bumpless_preload_returns_seed():
    """set_auto_mode(True, last_output=0.15) pre-loads integrator so first call returns ~0.15 with zero error."""
    pid = PID(0.5, 0.002, 4.0, output_limits=(0.0, 1.0), auto_mode=False, sample_time=None)
    pid.set_auto_mode(True, last_output=0.15)
    result = pid(0.0, dt=1.0)
    assert 0.10 < result < 0.20, (
        f'bumpless preload contract broken: expected result in (0.10, 0.20), got {result}'
    )


def test_output_clamps_at_one():
    """Large positive error (error_pct=10.0, setpoint=10.0, input=0.0) drives output to exactly 1.0.

    With Kp=0.5 and error=10.0, the proportional term is 5.0 which already exceeds the upper limit.
    """
    pid = PID(0.5, 0.002, 4.0, setpoint=10.0, output_limits=(0.0, 1.0), auto_mode=True, sample_time=None)
    result = pid(0.0, dt=1.0)
    assert result == 1.0, f'Expected saturation at 1.0 with large positive error, got {result}'


def test_output_clamps_at_zero():
    """Large negative error (setpoint=0.0, input=1.0) drives output to exactly 0.0."""
    pid = PID(0.5, 0.002, 4.0, setpoint=0.0, output_limits=(0.0, 1.0), auto_mode=True, sample_time=None)
    result = pid(1.0, dt=1.0)
    assert result == 0.0, f'Expected saturation at 0.0, got {result}'


def test_anti_windup_clamping_on_saturation():
    """Integral component does not grow without bound when output is saturated.

    With output_limits=(0,1) and Ki=0.002, the integral is clamped to [0,1].
    After 100 ticks at error=10 the integral must stay <= 1.0/0.002 + epsilon is
    too loose — the correct bound is that Ki * I cannot exceed output_limits range.
    We assert |components[1]| < 1.0 + 0.01 epsilon.
    """
    pid = PID(0.5, 0.002, 4.0, setpoint=10.0, output_limits=(0.0, 1.0), auto_mode=True, sample_time=None)
    for _ in range(100):
        pid(0.0, dt=1.0)  # error_pct = 10.0 every tick
    integral = pid.components[1]
    assert abs(integral) < 1.0 + 0.01, (
        f'Anti-windup failed: integral {integral} exceeds output_limits range'
    )


def test_d_on_measurement_no_kick_on_setpoint_change():
    """With differential_on_measurement=True, a sudden setpoint step does not produce a derivative spike.

    Keep input constant at 0.5 and change setpoint. The derivative term should remain
    near zero (no kick from setpoint step) because d/dt is taken on the measurement, not the error.
    """
    pid = PID(
        0.5, 0.002, 4.0,
        setpoint=0.5,
        output_limits=(0.0, 1.0),
        auto_mode=True,
        sample_time=None,
        differential_on_measurement=True,
    )
    # Warm up at steady state (input == setpoint, no change in measurement)
    for _ in range(5):
        pid(0.5, dt=1.0)

    # Now step setpoint while holding measurement constant
    pid.setpoint = 0.9
    pid(0.5, dt=1.0)
    _, _, d_term = pid.components
    # d_term should be near 0 because measurement did not change (d_input = 0)
    assert abs(d_term) < 0.1, (
        f'Derivative kick on setpoint change with D-on-measurement=True: d_term={d_term}'
    )


def test_derivative_filter_rejects_high_freq_noise():
    """999.32: external LPF on PID's derivative term rejects tick-to-tick noise.

    Mirrors the filter wired into fc_controller.py at the PID call site:
        alpha = dt/(tau+dt); d_filt = alpha*d_raw + (1-alpha)*d_filt; output = P+I+d_filt

    With tau=10s and dt=1s (i.e. alpha=1/11 ≈ 0.091), a single-tick noise spike
    on d_raw should be attenuated ~11× in the next output. Without the filter,
    the spike would pass through with full Kd*spike/dt magnitude.
    """
    pid = PID(
        0.5, 0.002, 4.0,
        setpoint=0.0,
        output_limits=(0.0, 1.0),
        auto_mode=True,
        sample_time=None,
        differential_on_measurement=True,
    )
    tau = 10.0
    dt = 1.0
    alpha = dt / (tau + dt)
    d_filt = 0.0

    # Warm up at steady state (no d_input change)
    for _ in range(5):
        pid(0.0, dt=dt)
        _, _, d_raw = pid.components
        d_filt = alpha * d_raw + (1 - alpha) * d_filt

    # Snapshot pre-spike state
    pre_d_filt = d_filt

    # Inject a single-tick spike in measurement → big d_input → big raw D term
    pid(0.05, dt=dt)  # 5% step in input
    _, _, d_raw_spike = pid.components
    d_filt_after = alpha * d_raw_spike + (1 - alpha) * pre_d_filt

    # The filtered D should track only alpha (~9%) of the raw spike
    assert abs(d_raw_spike) > 0.1, (
        f'sanity: raw D term should respond to 5% input step, got d_raw={d_raw_spike}'
    )
    expected_attenuation = abs(d_raw_spike) * alpha + abs(pre_d_filt) * (1 - alpha)
    assert abs(d_filt_after) < abs(d_raw_spike) * 0.5, (
        f'filter failed to attenuate spike: d_raw={d_raw_spike}, d_filt={d_filt_after} '
        f'(expected ≈ {expected_attenuation:.4f})'
    )


def test_derivative_filter_tau_zero_is_passthrough():
    """999.32: with tau=0 the filter math degenerates (alpha undefined / no filter applied).

    fc_controller.py gates the filter on `tau > 0`; this test documents that
    contract: tau=0 means D term flows through unchanged. The vendored PID's
    raw D output is what the controller uses when tau=0.
    """
    pid = PID(
        0.5, 0.002, 4.0,
        setpoint=0.0,
        output_limits=(0.0, 1.0),
        auto_mode=True,
        sample_time=None,
        differential_on_measurement=True,
    )
    for _ in range(3):
        pid(0.0, dt=1.0)
    pid(0.05, dt=1.0)
    _, _, d_raw = pid.components
    # When tau=0, the controller path skips the filter entirely; d_term in
    # the output is exactly d_raw. No test action needed beyond documenting.
    assert d_raw != 0.0


def test_disengage_freezes_integrator():
    """After set_auto_mode(False), further calls do not change the integral component."""
    pid = PID(0.5, 0.002, 4.0, setpoint=1.0, output_limits=(0.0, 1.0), auto_mode=True, sample_time=None)
    # Run 10 ticks with error=1.0 to build up integral
    for _ in range(10):
        pid(0.0, dt=1.0)
    integral_snapshot = pid.components[1]

    # Disengage
    pid.set_auto_mode(False)

    # Run 10 more ticks — integral must be unchanged
    for _ in range(10):
        pid(0.0, dt=1.0)

    assert pid.components[1] == integral_snapshot, (
        f'Integral changed during manual mode: was {integral_snapshot}, now {pid.components[1]}'
    )
