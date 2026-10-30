import dataclasses
import os

import pytest
import yaml

from fc2_core.params import (
    RULE_PARAM_NAMES, STARTUP_ONLY, params_from_mapping, usable_overlay,
    validate, write_overlay)
from fc2_core.rule import RuleParams


def test_defaults_valid():
    assert validate(RuleParams()) is None


def test_names_and_startup_only():
    assert 'pulse_sec' in RULE_PARAM_NAMES
    assert 'valve_gpio_pin' not in RULE_PARAM_NAMES
    assert set(STARTUP_ONLY) == {
        'valve_gpio_pin', 'valve_active_low', 'actuator_simulation_mode'}


@pytest.mark.parametrize('change', [
    {'cool_temp_c': 28.0}, {'pulse_sec': 121.0}, {'pulse_sec': 0.0},
    {'max_open_sec': 601.0, 'pulse_sec': 60.0},
    {'hot_bursts_per_hour': 31.0},
    {'cool_bursts_per_hour': -1.0}, {'weather_stale_sec': 0.0},
    {'night_start': '25:00'}, {'night_end': '06:60'}, {'night_end': 'abc'},
    {'max_open_sec': 60.0}, {'max_open_sec': 61.9},  # pulse 60: guard must clear a 1 s tick
    {'fallback_bursts_per_hour': 0.0},  # a dead feed must still water
])
def test_rejects(change):
    assert validate(dataclasses.replace(RuleParams(), **change)) is not None


@pytest.mark.parametrize('change', [
    {'max_open_sec': 62.0}, {'fallback_bursts_per_hour': 0.1},
    {'cool_bursts_per_hour': 0.0},
])
def test_accepts_edges(change):
    assert validate(dataclasses.replace(RuleParams(), **change)) is None


def test_overlay_roundtrip(tmp_path):
    p = tmp_path / 'o.yaml'
    write_overlay(str(p), {'pulse_sec': 45.0})
    assert yaml.safe_load(p.read_text()) == {
        '/**': {'ros__parameters': {'pulse_sec': 45.0}}}
    assert usable_overlay(str(p))
    assert not list(tmp_path.glob('*.tmp*'))


def test_failed_write_keeps_old_file(tmp_path, monkeypatch):
    p = tmp_path / 'o.yaml'
    write_overlay(str(p), {'pulse_sec': 45.0})
    monkeypatch.setattr(
        os, 'replace', lambda *a: (_ for _ in ()).throw(OSError('power cut')))
    with pytest.raises(OSError):
        write_overlay(str(p), {'pulse_sec': 50.0})
    assert yaml.safe_load(p.read_text())['/**']['ros__parameters'][
        'pulse_sec'] == 45.0


@pytest.mark.parametrize('text', ['', '/**: [', 'just a string', '/**: {}'])
def test_unusable_overlay(tmp_path, text):
    p = tmp_path / 'o.yaml'
    p.write_text(text)
    assert not usable_overlay(str(p))
    assert not usable_overlay(str(tmp_path / 'missing.yaml'))


def test_params_from_mapping_ignores_unknown():
    assert params_from_mapping(
        {'pulse_sec': 30.0, 'valve_gpio_pin': 17}).pulse_sec == 30.0
