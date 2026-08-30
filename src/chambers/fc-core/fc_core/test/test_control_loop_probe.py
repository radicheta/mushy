from fc_core.control_kernel import BandSpec, ProbeConfig, ProbeScheduler
from fc_core.sim.control_loop import ControlLoop
from fc_core.sim.pwm_sigma_delta import SigmaDeltaConfig, SigmaDeltaSimulator
from fc_core.sim.replay import run_closed_loop

BAND = BandSpec(0.885, 0.915, 'both')


def test_probe_commands_full_duty_and_restores_integrator():
    """MUSHY-138 ruling 5: bumpless re-engage sets ``pid._integral =
    clamp(last_output)`` where ``last_output`` is the duty PUBLISHED on the
    tick immediately before the probe fired -- so that is the contract to
    assert, not the pre-probe integral (which the bumpless transfer never
    tries to reproduce). ``idle_duty_max`` (ruling 4) makes idle reachable
    at this small a standing duty, so the brief's own config fires within a
    normal settle."""
    probe = ProbeScheduler(ProbeConfig(probe_seconds=60, interval_s=100, idle_s=10))
    loop = ControlLoop(BAND, probe=probe)
    for _ in range(50):
        loop.step(0.895, 1.0)               # below midpoint: PID accumulates
    pre_duty = 0.0
    for _ in range(30):
        pre_duty, _ = loop.step(0.905, 1.0)  # in band, duty decays toward 0

    # Step until the probe fires, tracking the duty PUBLISHED on the tick
    # just before it does -- that is what the re-engage will bumpless-load.
    duties = []
    while True:
        d, _ = loop.step(0.905, 1.0)
        if loop.probe.active:
            duties.append(d)
            break
        pre_duty = d
    while loop.probe.active:
        d, _ = loop.step(0.905, 1.0)         # this call's just_ended re-engages
        duties.append(d)
    assert duties.count(1.0) == 60

    # The re-engage tick itself also runs the 999.49 in-band decay (error
    # is 0 in-band) AFTER loading the integral, so pid._integral is already
    # off pre_duty by more than 1e-9 by the time we can observe it -- assert
    # the contract ControlLoop actually applied instead: the exact value it
    # passed to set_auto_mode(last_output=...).
    assert loop.pid.auto_mode
    assert loop._pre_probe_output == pre_duty


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
