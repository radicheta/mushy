"""ROS tests for fc2_controller. Run only in docker with --network none."""
import math
import time

import pytest

rclpy = pytest.importorskip('rclpy')
yaml = pytest.importorskip('yaml')

from fc2_core.fc2_node import Fc2Controller  # noqa: E402
from fc2_core.rule import WeatherReading  # noqa: E402
from fc2_core.valve import GuardedValve, SimValve  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402


def fresh_reading(*a, **k):
    return WeatherReading(20.0, 70.0, 5.0, 0.0, 0.1, '2026-10-30T12:00',
                          time.monotonic())


@pytest.fixture(scope='module')
def ros():
    rclpy.init()
    yield
    rclpy.shutdown()


@pytest.fixture
def node_factory(ros):
    made = []

    def make(overlay, fetch_fn=None, valve='guarded', **kw):
        if valve == 'guarded':
            valve = GuardedValve(SimValve(), 120.0)
        n = Fc2Controller(valve=valve, overlay_path=str(overlay),
                          fetch_fn=fetch_fn or fresh_reading,
                          clock_synced_fn=lambda: False, **kw)
        made.append(n)
        return n
    yield make
    for n in made:
        n.destroy_node()


def test_rejects_bad_param_and_leaves_overlay(node_factory, tmp_path):
    n = node_factory(overlay=tmp_path / 'o.yaml')
    r = n.set_parameters([Parameter('pulse_sec', value=500.0)])[0]
    assert not r.successful and not (tmp_path / 'o.yaml').exists()


def test_rejects_pin_change(node_factory, tmp_path):
    n = node_factory(overlay=tmp_path / 'o.yaml')
    assert not n.set_parameters([Parameter('valve_gpio_pin', value=5)])[0].successful


def test_good_param_persists(node_factory, tmp_path):
    n = node_factory(overlay=tmp_path / 'o.yaml')
    assert n.set_parameters([Parameter('pulse_sec', value=45.0)])[0].successful
    assert yaml.safe_load((tmp_path / 'o.yaml').read_text())['/**']['ros__parameters']['pulse_sec'] == 45.0


def test_fetch_failure_goes_fallback_valve_closed_at_destroy(node_factory, tmp_path):
    def fail(*a, **k): raise OSError('wifi down')
    n = node_factory(overlay=tmp_path / 'o.yaml', fetch_fn=fail)
    n.control_tick()
    assert n.last_decision.mode == 'fallback'
    n.valve.set_open(True); n.destroy_node()
    assert not n.valve.inner.is_open


def test_persists_node_params_but_not_startup_only(node_factory, tmp_path):
    n = node_factory(overlay=tmp_path / 'o.yaml')
    assert n.set_parameters([Parameter('weather_poll_sec', value=600.0)])[0].successful
    saved = yaml.safe_load((tmp_path / 'o.yaml').read_text())['/**']['ros__parameters']
    assert saved['weather_poll_sec'] == 600.0
    assert saved['timezone'] == 'America/Montevideo'
    assert 'cool_temp_c' in saved
    for name in ('valve_gpio_pin', 'valve_active_low', 'actuator_simulation_mode'):
        assert name not in saved


@pytest.mark.parametrize('value', [math.nan, math.inf])
def test_rejects_non_finite(node_factory, tmp_path, value):
    n = node_factory(overlay=tmp_path / 'o.yaml')
    assert not n.set_parameters([Parameter('hot_temp_c', value=value)])[0].successful
    assert not (tmp_path / 'o.yaml').exists()


def test_rejects_wrong_type(node_factory, tmp_path):
    n = node_factory(overlay=tmp_path / 'o.yaml')
    assert not n.set_parameters([Parameter('pulse_sec', value='60')])[0].successful


def test_rejects_unknown_timezone(node_factory, tmp_path):
    n = node_factory(overlay=tmp_path / 'o.yaml')
    assert not n.set_parameters([Parameter('timezone', value='Mars/Olympus')])[0].successful


def test_rejects_when_overlay_write_fails(node_factory, tmp_path):
    blocker = tmp_path / 'file'
    blocker.write_text('')
    n = node_factory(overlay=blocker / 'o.yaml')  # parent is a file
    assert not n.set_parameters([Parameter('pulse_sec', value=45.0)])[0].successful
    assert n.get_parameter('pulse_sec').value == 60.0


def test_weather_mode_with_fresh_reading(node_factory, tmp_path):
    n = node_factory(overlay=tmp_path / 'o.yaml')
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        n.control_tick()
        if n.last_decision.mode == 'weather':
            break
        time.sleep(0.05)
    assert n.last_decision.mode == 'weather'


def test_pin_unset_with_simulation_off_refuses_to_start(ros, tmp_path):
    with pytest.raises(ValueError, match='valve_gpio_pin'):
        Fc2Controller(
            overlay_path=str(tmp_path / 'o.yaml'), fetch_fn=fresh_reading,
            clock_synced_fn=lambda: False,
            parameter_overrides=[Parameter('actuator_simulation_mode', value=False)])


def test_builds_sim_valve_by_default(node_factory, tmp_path):
    n = node_factory(overlay=tmp_path / 'o.yaml', valve=None)
    assert isinstance(n.valve, GuardedValve) and isinstance(n.valve.inner, SimValve)
    assert n.valve.max_open_sec == 120.0
    assert n.set_parameters([Parameter('max_open_sec', value=90.0)])[0].successful
    assert n.valve.max_open_sec == 90.0


def test_base_config_declares_every_param_with_its_type():
    import os
    from fc2_core.fc2_node import DEFAULTS
    path = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'fc2_config.yaml')
    with open(path) as f:
        cfg = yaml.safe_load(f)['/**']['ros__parameters']
    assert set(cfg) == set(DEFAULTS)
    for k, v in cfg.items():
        assert type(v) is type(DEFAULTS[k]), k
