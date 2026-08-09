"""Absolute-moisture chamber model (MUSHY-60).

The old model balanced RH points per hour, which is not a conserved quantity --
the same gram of water is a different number of RH points at 3 C than at 20 C.
This one balances grams of water and lets temperature do its real work.
"""
import pytest

from fc_core.sim.chamber_model import ChamberModel, ChamberParams
from fc_core.sim.psychrometrics import CHAMBER_VOLUME_M3, absolute_humidity_g_m3

# Fitted in Task 2 -- see 999.33-06-FIT-RESULTS.md. Replace with the reported values.
FITTED_Q = 0.9634   # m3/h, from the dispatch
FITTED_F = 6.776   # g/h, from the dispatch

TEMP_C = 10.0
RH0 = 90.0
HOUR_S = 3600.0


def params(**kw):
    base = dict(air_exchange_m3_per_h=FITTED_Q, fill_g_per_h=FITTED_F)
    base.update(kw)
    return ChamberParams(**base)


def run(model, duty, ambient_ah, seconds, dt_s=60.0):
    for _ in range(int(seconds / dt_s)):
        model.step(delivered_duty=duty, dt_s=dt_s, ambient_ah_g_m3=ambient_ah)
    return model.rh


def test_fitted_constants_were_substituted():
    """Guards against shipping the placeholder zeros."""
    assert FITTED_Q > 0.0 and FITTED_F > 0.0, 'substitute the Task 2 fit values'


def test_zero_duty_with_drier_ambient_loses_moisture():
    m = ChamberModel(params(), rh0_pct=RH0, temp_c=TEMP_C)
    dry = absolute_humidity_g_m3(TEMP_C, 60.0)
    assert run(m, 0.0, dry, 2 * HOUR_S) < RH0


def test_zero_duty_with_equal_ambient_holds_station():
    """Zero gradient means zero leak. This is the physical condition the
    MUSHY-57 high-ambient test expresses once it is migrated."""
    m = ChamberModel(params(), rh0_pct=RH0, temp_c=TEMP_C)
    same = absolute_humidity_g_m3(TEMP_C, RH0)
    assert run(m, 0.0, same, HOUR_S) == pytest.approx(RH0, abs=1e-9)


def test_full_duty_raises_rh():
    m = ChamberModel(params(), rh0_pct=RH0, temp_c=TEMP_C)
    same = absolute_humidity_g_m3(TEMP_C, RH0)
    assert run(m, 1.0, same, 2 * HOUR_S) > RH0


def test_equilibrium_duty_holds_rh_flat():
    """The settle window here is governed by the MOISTURE time constant
    V/Q (~6 h), NOT by the duty lag dead_time_s + tau_s (~0.43 h). An
    earlier version of this test cleared only the duty lag before checking
    flatness; that checkpoint sits at the bottom of the initial dip (applied
    duty ramps up from 0, so the chamber loses moisture before duty reaches
    u), and the chamber was still recovering toward its fixed point on the
    much slower V/Q timescale -- it failed flatness by ~0.06 pt for a reason
    that had nothing to do with a model bug. Settling for 3*V/Q clears that
    recovery too.
    """
    p = params()
    ah_in = absolute_humidity_g_m3(TEMP_C, RH0)
    ah_out = absolute_humidity_g_m3(TEMP_C, 70.0)
    u = p.equilibrium_duty(ah_in, ah_out)
    m = ChamberModel(p, rh0_pct=RH0, temp_c=TEMP_C)
    settle_s = 3 * (CHAMBER_VOLUME_M3 / p.air_exchange_m3_per_h) * HOUR_S
    run(m, u, ah_out, settle_s)
    settled = m.rh
    assert run(m, u, ah_out, HOUR_S) == pytest.approx(settled, abs=0.05)
    # u is defined as the duty that zeroes dAH/dt at ah_in(RH0), so ah_in is
    # the analytic fixed point: after several V/Q the chamber must return to
    # RH0, not just go flat somewhere else.
    assert settled == pytest.approx(RH0, abs=0.1)


def test_equilibrium_duty_is_higher_when_ambient_is_drier():
    """The seasonal point: a larger gradient demands more standing duty.
    This is what dissolves MUSHY-57's fixed-bias caveat."""
    p = params()
    ah_in = absolute_humidity_g_m3(TEMP_C, RH0)
    drier = p.equilibrium_duty(ah_in, absolute_humidity_g_m3(TEMP_C, 50.0))
    wetter = p.equilibrium_duty(ah_in, absolute_humidity_g_m3(TEMP_C, 85.0))
    assert drier > wetter


def test_equilibrium_duty_is_zero_when_gradient_is_zero():
    p = params()
    ah = absolute_humidity_g_m3(TEMP_C, RH0)
    assert p.equilibrium_duty(ah, ah) == pytest.approx(0.0)


def test_dead_time_delays_the_response():
    p = params()
    m = ChamberModel(p, rh0_pct=RH0, temp_c=TEMP_C)
    same = absolute_humidity_g_m3(TEMP_C, RH0)
    before = m.rh
    # Step duty to full, but stop short of the transport delay.
    assert run(m, 1.0, same, p.dead_time_s - 60.0) == pytest.approx(before, abs=1e-9)


def test_moisture_settling_time_is_v_over_q():
    """Pins the headline dynamical property: with duty held at 0 (so the
    duty lag is out of the picture entirely -- applied duty is 0 from the
    first step) and a fixed ambient, absolute humidity relaxes toward its
    fixed point as a clean exponential with time constant V/Q. Checked in
    AH, not RH, because RH is a nonlinear (though monotonic) function of AH
    at fixed temperature and would not be exactly exponential.

    V/Q ~= 5.98 h against an observed ~2 h limit cycle (MUSHY-56) means the
    controller is acting substantially faster than the plant settles -- a
    future change to Q must not silently change that relationship unnoticed.
    """
    p = params()
    ambient_ah = absolute_humidity_g_m3(TEMP_C, 70.0)
    m = ChamberModel(p, rh0_pct=RH0, temp_c=TEMP_C)
    start_ah = m.ah
    fixed_point_ah = ambient_ah   # zero duty: dAH/dt = 0 only when ah == ambient
    initial_gap = start_ah - fixed_point_ah

    tau_v_over_q_s = (CHAMBER_VOLUME_M3 / p.air_exchange_m3_per_h) * HOUR_S
    for _ in range(int(tau_v_over_q_s / 60.0)):
        m.step(delivered_duty=0.0, dt_s=60.0, ambient_ah_g_m3=ambient_ah)

    remaining_gap = m.ah - fixed_point_ah
    fraction_remaining = remaining_gap / initial_gap
    assert fraction_remaining == pytest.approx(1 / 2.718281828, rel=0.03)


def test_same_rh_at_higher_temperature_is_more_water():
    """The reason RH points cannot be the model's currency."""
    assert absolute_humidity_g_m3(20.0, 90.0) > absolute_humidity_g_m3(5.0, 90.0)
    warm = ChamberModel(params(), rh0_pct=90.0, temp_c=20.0)
    cold = ChamberModel(params(), rh0_pct=90.0, temp_c=5.0)
    assert warm.ah > cold.ah


def test_step_is_dt_invariant():
    """1 s and 10 s ticks must agree, or replay resolution changes results.

    The new model is a forward-Euler integrator, so 1 s and 10 s stepping
    will NOT agree exactly -- local error is O(dt). Measured directly: at
    duty 0.3 (this test's condition) over 1.5 h, 1 s vs 10 s stepping
    differ by ~0.0077 RH pts; the worst case checked (full duty, 1-2 h) was
    ~0.03 pts. abs=0.02 sits comfortably above the measured 0.3-duty
    discrepancy (>2x headroom) while still being tight enough to catch a
    real integration bug (e.g. a dropped dt_s/3600 conversion, which would
    misagree by orders of magnitude, not fractions of a point).
    """
    p = params()
    ambient_ah = absolute_humidity_g_m3(TEMP_C, 70.0)
    a = ChamberModel(p, rh0_pct=RH0, temp_c=TEMP_C)
    b = ChamberModel(p, rh0_pct=RH0, temp_c=TEMP_C)
    run(a, 0.3, ambient_ah, 5400.0, dt_s=1.0)
    run(b, 0.3, ambient_ah, 5400.0, dt_s=10.0)
    assert a.rh == pytest.approx(b.rh, abs=0.02)


def test_no_rclpy_dependency():
    """The whole point of fc_core.sim is that it runs without ROS.

    Checked in a CLEAN subprocess: this test dir's conftest imports rclpy for
    the ROS-dependent modules, so asserting on this process's sys.modules would
    only measure conftest, not the sim package.
    """
    import pathlib
    import subprocess
    import sys

    pkg_root = pathlib.Path(__file__).resolve().parents[2]
    probe = (
        'import sys; '
        'import fc_core.sim.chamber_model, fc_core.sim.pwm_window; '
        "leaked = [m for m in ('rclpy', 'RPi', 'RPi.GPIO') if m in sys.modules]; "
        'print(",".join(leaked))'
    )
    result = subprocess.run(
        [sys.executable, '-c', probe],
        capture_output=True, text=True, cwd=str(pkg_root),
        env={'PYTHONPATH': str(pkg_root), 'PATH': '/usr/bin:/bin'},
    )
    assert result.returncode == 0, f'sim package failed to import alone:\n{result.stderr}'
    assert result.stdout.strip() == '', f'sim package pulled in ROS deps: {result.stdout}'
