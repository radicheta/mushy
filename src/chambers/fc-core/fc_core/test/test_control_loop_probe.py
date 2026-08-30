from fc_core.control_kernel import BandSpec, ProbeConfig, ProbeScheduler
from fc_core.sim.control_loop import ControlLoop
from fc_core.sim.pwm_sigma_delta import SigmaDeltaConfig, SigmaDeltaSimulator
from fc_core.sim.replay import run_closed_loop

BAND = BandSpec(0.885, 0.915, 'both')


def test_probe_commands_full_duty_and_restores_integrator():
    # idle_s=0: this test is about the probe pulse and integrator
    # preservation, not the idle-wait rule (covered by
    # test_probe_scheduler.py) -- with idle_s>0 the probe could only ever
    # fire while the PID's own D-filter transient still has duty pinned to
    # its 0 floor, and re-engaging bumpless from a CLIPPED pre-probe duty
    # would not reproduce the true integral.
    N1, N2, K = 5, 550, 139
    probe = ProbeScheduler(ProbeConfig(probe_seconds=60, interval_s=N1 + N2 + K, idle_s=0))
    loop = ControlLoop(BAND, probe=probe)
    for _ in range(N1):
        loop.step(0.895, 1.0)               # below midpoint: PID accumulates
    for _ in range(N2):
        loop.step(0.905, 1.0)               # in band; lets the D-filter settle so
                                             # commanded duty ~= the true integral

    # Run one tick at a time, capturing the integral from just BEFORE the
    # tick on which the probe fires (in-band ticks decay it every step, so
    # reading it any earlier would not be "pre-probe"). interval_s is tuned
    # (N1+N2+K) so the probe fires at tick K and its 60-tick pulse ends on
    # the very last tick of this 200-tick window, leaving no ticks for the
    # post-probe 999.49 decay to run before we check the restored integral.
    duties = []
    pre = None
    prev_integral = loop.pid._integral
    for _ in range(200):
        was_active = probe.active
        d, _ = loop.step(0.905, 1.0)
        if probe.active and not was_active and pre is None:
            pre = prev_integral
        duties.append(d)
        prev_integral = loop.pid._integral
    assert duties.count(1.0) == 60
    assert loop.pid.auto_mode                                  # re-engaged after the probe
    assert abs(loop.pid._integral - pre) < 1e-6                # integrator restored, not Mode C's 1.0


def test_run_closed_loop_records_probe_and_relay_series():
    # A chamber started above the band (rh0=90.5 vs a 90.0 target) idles at
    # duty 0 for its first several minutes before steady-state ambient loss
    # gives the PID anything to do; interval_s/idle_s are sized to that
    # first idle window (measured ~944 ticks at this seed) so the probe
    # fires there rather than needing an idle window to recur later, which
    # standing ambient demand never again produces in a 6h run.
    probe = ProbeScheduler(ProbeConfig(probe_seconds=150, interval_s=900, idle_s=500))
    m = run_closed_loop(hours=6.0, rh0=90.5, probe=probe,
                        pwm=SigmaDeltaSimulator(SigmaDeltaConfig()),
                        rh_noise_pct=0.1, seed=1)
    assert len(m.probe_series) == len(m.rh_series) == len(m.relay_series) == len(m.temp_series)
    assert probe.count >= 1
    assert 0 < sum(m.probe_series) <= 150 * probe.count        # aborts allowed, dt=1.0 here
    assert any(m.relay_series)
    # quantised sensed RH
    assert all(abs(x * 100 - round(x * 100)) < 1e-6 for x in m.rh_series[:100])
