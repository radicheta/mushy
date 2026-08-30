"""Run: PYTHONPATH=src/chambers/fc-core .venv/bin/python -m pytest -q scripts/self-tune/test_push_chamber_params.py"""
import importlib.util
import shutil
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    'push_chamber_params', Path(__file__).with_name('push-chamber-params.py'))
pcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pcp)


def test_set_yaml_writes_a_float_and_stamps_provenance(tmp_path, monkeypatch):
    """A whole-number gain must serialise as `2.0`: fc_controller declares these
    as doubles and an int literal crashed it once (decay_tau, 2026-06-28)."""
    copy = tmp_path / 'fc_config.yaml'
    shutil.copy(pcp.YAML, copy)
    monkeypatch.setattr(pcp, 'YAML', copy)

    pcp.set_yaml('pid_kd', 2.0, '2026-09-05.json')

    line = [ln for ln in copy.read_text().splitlines() if ln.strip().startswith('pid_kd:')]
    assert line == ['    pid_kd: 2.0  # self-tune 2026-09-05.json']
    assert pcp.yaml_value('pid_kd') == 2.0


def test_num_never_emits_a_bare_int():
    assert pcp.num(4) == '4.0'
    assert pcp.num(0.00033333333) == '0.00033333333'
