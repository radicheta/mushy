"""Phase 31 D-01/D-02 config sanity — pure YAML test, no rclpy.

Locks force-condensation and force-evaporation mode entries against the
four invariants that, if drifted, would silently break Phase 31:
  (1) force_duty values (1.0, 0.0) — flipping these inverts experiment semantics
  (2) wide-open bands [0.0, 1.0] — narrowing re-arms alerter alarms (D-32)
  (3) defend_side='both' — required by alerter alignment
  (4) target/t_target shape parity with fruiting/pinning so 28's resolver works
"""
import os
import yaml
import pytest

CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), '..', '..', 'config', 'fc_config.yaml'
)


@pytest.fixture(scope='module')
def params():
    with open(CONFIG_PATH) as f:
        doc = yaml.safe_load(f)
    return doc['fc_controller']['ros__parameters']


def test_four_declared_modes_present(params):
    expected = {'fruiting', 'pinning', 'force-condensation', 'force-evaporation'}
    seen = set()
    for k in params:
        if k.startswith('modes.') and k.endswith('.target_humidity'):
            seen.add(k.split('.')[1])
    assert expected.issubset(seen), f'missing modes: {expected - seen}'


def test_force_condensation_force_duty_is_one(params):
    assert params['modes.force-condensation.force_duty'] == 1.0


def test_force_evaporation_force_duty_is_zero(params):
    assert params['modes.force-evaporation.force_duty'] == 0.0


@pytest.mark.parametrize('mode', ['force-condensation', 'force-evaporation'])
def test_force_modes_have_wide_open_bands(params, mode):
    # D-01/D-32: bands MUST be wide-open so alerter defended-edge rule
    # (Phase 28 D-21) cannot fire during an experiment.
    assert params[f'modes.{mode}.band_low'] == 0.0, f'{mode}: band_low must be 0.0'
    assert params[f'modes.{mode}.band_high'] == 1.0, f'{mode}: band_high must be 1.0'


@pytest.mark.parametrize('mode', ['force-condensation', 'force-evaporation'])
def test_force_modes_defend_side_both(params, mode):
    assert params[f'modes.{mode}.defend_side'] == 'both'


@pytest.mark.parametrize('mode', ['force-condensation', 'force-evaporation'])
def test_force_modes_t_target_is_nan(params, mode):
    import math
    v = params[f'modes.{mode}.t_target']
    assert math.isnan(v), f'{mode}.t_target should be NaN, got {v!r}'


def test_baseline_modes_have_no_force_duty(params):
    # fruiting/pinning must NOT carry force_duty — sentinel = absent => NaN
    # via 31-02's declare_parameter default. A spurious force_duty on
    # fruiting would convert it into a forcing mode at next deploy.
    for mode in ('fruiting', 'pinning'):
        assert f'modes.{mode}.force_duty' not in params, (
            f'{mode} must NOT declare force_duty in YAML; remove the key'
        )
