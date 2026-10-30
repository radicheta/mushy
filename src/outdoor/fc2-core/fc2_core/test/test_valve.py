import sys
import types

import pytest

from fc2_core.valve import (GpioValve, GuardedValve, SimValve,
                            resolve_valve_config, valve_off_main)


class FakeTimer:
    made = []

    def __init__(self, sec, fn):
        self.sec, self.fn, self.cancelled = sec, fn, False
        FakeTimer.made.append(self)

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True


def install_fake_rpi_gpio(monkeypatch):
    calls = {'setup': [], 'output': [], 'cleanup': []}
    gpio = types.SimpleNamespace(
        BCM='BCM', OUT='OUT', HIGH='HIGH', LOW='LOW',
        setmode=lambda m: calls.setdefault('mode', m),
        setup=lambda pin, d, initial=None: calls['setup'].append((pin, d, initial)),
        output=lambda pin, lvl: calls['output'].append((pin, lvl)),
        cleanup=lambda pin: calls['cleanup'].append(pin),
        setwarnings=lambda f: None)
    pkg = types.ModuleType('RPi')
    pkg.GPIO = gpio
    monkeypatch.setitem(sys.modules, 'RPi', pkg)
    monkeypatch.setitem(sys.modules, 'RPi.GPIO', gpio)
    return calls


def test_guard_trips_after_max_open():
    v = SimValve()
    g = GuardedValve(v, 120.0, timer_factory=FakeTimer, clock=lambda: 0.0)
    g.set_open(True)
    assert v.is_open and FakeTimer.made[-1].sec == 120.0
    FakeTimer.made[-1].fn()
    assert not v.is_open and g.tripped


def test_close_cancels_guard_and_logs_interval():
    t = [0.0]
    v = SimValve()
    g = GuardedValve(v, 120.0, timer_factory=FakeTimer, clock=lambda: t[0])
    g.set_open(True)
    t[0] = 60.0
    g.set_open(False)
    assert FakeTimer.made[-1].cancelled and g.intervals[-1] == (0.0, 60.0)
    assert not v.is_open and not g.tripped


def test_reopen_while_open_does_not_extend_window():
    FakeTimer.made.clear()
    g = GuardedValve(SimValve(), 120.0, timer_factory=FakeTimer, clock=lambda: 0.0)
    g.set_open(True)
    g.set_open(True)
    assert len(FakeTimer.made) == 1 and not FakeTimer.made[0].cancelled


def test_open_after_trip_starts_new_window():
    FakeTimer.made.clear()
    v = SimValve()
    g = GuardedValve(v, 120.0, timer_factory=FakeTimer, clock=lambda: 0.0)
    g.set_open(True)
    FakeTimer.made[-1].fn()
    g.set_open(True)
    assert v.is_open and len(FakeTimer.made) == 2 and g.tripped
    assert g.intervals[0] == (0.0, 0.0) and g.intervals[1] == (0.0, None)


def test_old_intervals_pruned():
    t = [0.0]
    g = GuardedValve(SimValve(), 120.0, timer_factory=FakeTimer, clock=lambda: t[0])
    g.set_open(True)
    t[0] = 10.0
    g.set_open(False)
    t[0] = 7200.0 + 11.0
    g.set_open(True)
    assert g.intervals == [(7211.0, None)]


def test_failed_open_leaves_no_armed_timer():
    class Boom(SimValve):
        def set_open(self, o):
            raise OSError('gpio')
    FakeTimer.made.clear()
    g = GuardedValve(Boom(), 120.0, timer_factory=FakeTimer, clock=lambda: 0.0)
    with pytest.raises(OSError):
        g.set_open(True)
    assert FakeTimer.made[-1].cancelled and g.intervals == []


def _cfg(tmp_path, base_extra='', ov=None):
    base = tmp_path / 'b.yaml'
    base.write_text('/**:\n  ros__parameters:\n    valve_gpio_pin: 17\n'
                    '    valve_active_low: false\n' + base_extra)
    ovp = tmp_path / 'o.yaml'
    if ov is not None:
        ovp.write_text(ov)
    return str(base), str(ovp)


def test_resolve_valve_config_overlay_wins(tmp_path):
    base, ov = _cfg(tmp_path, ov='/**:\n  ros__parameters:\n    valve_active_low: true\n')
    assert resolve_valve_config(base, ov) == (17, True)
    assert resolve_valve_config(base, str(tmp_path / 'none.yaml')) == (17, False)


def test_gpio_valve_starts_off_respecting_polarity(monkeypatch):
    calls = install_fake_rpi_gpio(monkeypatch)
    GpioValve(17, active_low=True)
    assert calls['setup'][-1] == (17, 'OUT', 'HIGH')
    calls = install_fake_rpi_gpio(monkeypatch)
    v = GpioValve(17, active_low=False)
    assert calls['setup'][-1] == (17, 'OUT', 'LOW')
    v.set_open(True)
    assert calls['output'][-1] == (17, 'HIGH')
    v.close()
    assert calls['output'][-1] == (17, 'LOW') and calls['cleanup'] == [17]


def test_valve_off_main_drives_off(monkeypatch, tmp_path):
    calls = install_fake_rpi_gpio(monkeypatch)
    base, ov = _cfg(tmp_path, '    actuator_simulation_mode: false\n')
    monkeypatch.setenv('FC2_CONFIG', base)
    monkeypatch.setenv('FC2_RUNTIME_OVERLAY', ov)  # missing overlay: no traceback
    with pytest.raises(SystemExit) as e:
        valve_off_main()
    assert e.value.code == 0
    assert calls['setup'][-1] == (17, 'OUT', 'LOW') and calls['output'][-1] == (17, 'LOW')
    assert calls['cleanup'] == []  # pin stays driven off


def test_valve_off_main_sim_mode_touches_nothing(monkeypatch, tmp_path):
    calls = install_fake_rpi_gpio(monkeypatch)
    base, ov = _cfg(tmp_path, '    actuator_simulation_mode: true\n')
    monkeypatch.setenv('FC2_CONFIG', base)
    monkeypatch.setenv('FC2_RUNTIME_OVERLAY', ov)
    with pytest.raises(SystemExit) as e:
        valve_off_main()
    assert e.value.code == 0 and calls['setup'] == []


def test_valve_off_main_gpio_failure_nonzero(monkeypatch, tmp_path, capsys):
    calls = install_fake_rpi_gpio(monkeypatch)
    sys.modules['RPi.GPIO'].setup = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('nope'))
    base, ov = _cfg(tmp_path, '    actuator_simulation_mode: false\n')
    monkeypatch.setenv('FC2_CONFIG', base)
    monkeypatch.setenv('FC2_RUNTIME_OVERLAY', ov)
    with pytest.raises(SystemExit) as e:
        valve_off_main()
    assert e.value.code != 0 and 'nope' in capsys.readouterr().err


def test_valve_off_main_unreadable_config_nonzero(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv('FC2_CONFIG', str(tmp_path / 'missing.yaml'))
    monkeypatch.setenv('FC2_RUNTIME_OVERLAY', str(tmp_path / 'none.yaml'))
    with pytest.raises(SystemExit) as e:
        valve_off_main()
    assert e.value.code != 0 and 'missing.yaml' in capsys.readouterr().err
