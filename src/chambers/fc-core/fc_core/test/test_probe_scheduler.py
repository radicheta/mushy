from fc_core.control_kernel import BandSpec, ProbeConfig, ProbeScheduler

BAND = BandSpec(0.885, 0.915, 'both')
CFG = ProbeConfig(probe_seconds=150.0, interval_s=3600.0, idle_s=900.0)


def run(sched, n, rh=0.905, rate=0.0, last_duty=0.0, allowed=True, dt=1.0):
    out = []
    for _ in range(n):
        out.append(sched.step(dt, rh, BAND, rate, last_duty, allowed))
    return out


def test_disabled_never_fires():
    s = ProbeScheduler(ProbeConfig(interval_s=0.0))
    assert not any(run(s, 20000))
    assert s.count == 0


def test_fires_after_interval_and_idle_then_lasts_probe_seconds():
    s = ProbeScheduler(CFG)
    assert not any(run(s, 3599))          # interval not yet elapsed
    out = run(s, 400)
    assert out[0] is True and s.count == 1
    assert sum(out) == 150                # exactly probe_seconds ticks of duty 1
    assert out[150] is False


def test_just_ended_flags_the_first_tick_after():
    s = ProbeScheduler(CFG)
    run(s, 3600 + 149)
    assert s.active
    s.step(1.0, 0.905, BAND, 0.0, 1.0, True)
    assert not s.active and s.just_ended
    s.step(1.0, 0.905, BAND, 0.0, 0.0, True)
    assert not s.just_ended


def test_conditions_block_start():
    for kw in (dict(rh=0.895),               # below midpoint
               dict(rh=0.912),               # above band_high - margin
               dict(rate=0.5),               # ramping
               dict(last_duty=0.2),          # not idle
               dict(allowed=False)):         # stale / mode C / wrong mode
        s = ProbeScheduler(CFG)
        assert not any(run(s, 5000, **kw)), kw


def test_idle_counts_from_last_nonzero_duty():
    s = ProbeScheduler(CFG)
    run(s, 3600, last_duty=0.3)             # interval elapsed but busy
    assert not any(run(s, 899))             # idle 899 s: not yet
    assert run(s, 2)[1] is True


def test_abort_on_band_high_or_disallowed():
    for kw in (dict(rh=0.916), dict(allowed=False)):
        s = ProbeScheduler(CFG)
        run(s, 3600 + 10)
        assert s.active
        assert s.step(1.0, kw.get('rh', 0.905), BAND, 0.0, 1.0, kw.get('allowed', True)) is False
        assert not s.active and s.just_ended


def test_interval_restarts_after_a_probe():
    s = ProbeScheduler(CFG)
    run(s, 3600 + 150 + 1)
    assert not any(run(s, 3598))
    assert s.count == 1


def test_idle_duty_max_gate():
    # 0.01 < idle_duty_max (0.02): counts as idle, so only the interval gates it.
    s = ProbeScheduler(CFG)
    assert not any(run(s, 3599, last_duty=0.01))
    assert run(s, 1, last_duty=0.01)[0] is True
    # 0.05 >= idle_duty_max: never idle, so the probe never fires.
    assert not any(run(ProbeScheduler(CFG), 5000, last_duty=0.05))
