"""Chamber model must reproduce the rates measured on fc1 2026-08-08.

Ground truth (26 h trace, fruiting, band [0.885, 0.915]):
  RH decay at duty 0            -2.24 pts/h
  RH rise at delivered ~0.40    +6.76 pts/h
  implied gross fill at 1.0     ~22.5 pts/h
  implied equilibrium duty      ~0.10
"""
import pytest

from fc_core.sim.chamber_model import ChamberModel, ChamberParams

P = ChamberParams()


def _run(model, duty, seconds, dt=1.0):
    for _ in range(int(seconds / dt)):
        model.step(delivered_duty=duty, dt_s=dt)
    return model.rh


def test_decays_at_measured_leak_rate_when_off():
    m = ChamberModel(P, rh0=90.0)
    assert _run(m, 0.0, 3600) == pytest.approx(90.0 - 2.24, abs=0.05)


def test_rises_at_measured_rate_once_settled():
    """+6.76 pts/h net at delivered 0.40, measured while the cap was binding.

    Measured after the dead time and several mixing constants have elapsed, so
    this is the steady-state slope, not the transient.
    """
    m = ChamberModel(P, rh0=90.0)
    _run(m, 0.40, P.dead_time_s + 4 * P.tau_s)     # let transients die
    before = m.rh
    _run(m, 0.40, 3600)
    assert (m.rh - before) == pytest.approx(6.76, abs=0.15)


def test_equilibrium_duty_holds_rh_steady():
    m = ChamberModel(P, rh0=90.0)
    _run(m, P.equilibrium_duty, P.dead_time_s + 4 * P.tau_s)
    settled = m.rh
    _run(m, P.equilibrium_duty, 6 * 3600)
    assert m.rh == pytest.approx(settled, abs=0.05)


def test_equilibrium_duty_is_about_ten_percent():
    assert P.equilibrium_duty == pytest.approx(0.0996, abs=0.005)


def test_dead_time_delays_the_response():
    """Before the dead time elapses, RH must still be falling."""
    m = ChamberModel(P, rh0=90.0)
    _run(m, 1.0, P.dead_time_s - 30)
    assert m.rh < 90.0


def test_response_has_begun_after_dead_time():
    m = ChamberModel(P, rh0=90.0)
    _run(m, 1.0, P.dead_time_s + 2 * P.tau_s)
    assert m.rh > 90.0


def test_step_is_dt_invariant():
    """1 s and 10 s ticks must agree, or replay resolution changes results."""
    a = ChamberModel(P, rh0=90.0)
    b = ChamberModel(P, rh0=90.0)
    _run(a, 0.3, 5400, dt=1.0)
    _run(b, 0.3, 5400, dt=10.0)
    assert a.rh == pytest.approx(b.rh, abs=0.05)


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
