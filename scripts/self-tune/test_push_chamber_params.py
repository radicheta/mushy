"""Run: PYTHONPATH=src/chambers/fc-core .venv/bin/python -m pytest -q scripts/self-tune/test_push_chamber_params.py"""
import importlib.util
import shutil
import subprocess
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


def _repo(tmp_path):
    """A throwaway git repo standing in for the checkout, on main, with the
    two files the push script writes."""
    r = tmp_path / 'repo'
    (r / 'reports' / 'self-tune').mkdir(parents=True)
    (r / 'config').mkdir()
    yaml, accepted = r / 'config' / 'fc_config.yaml', r / 'reports' / 'self-tune' / 'accepted.json'
    yaml.write_text('    pid_kp: 0.36\n')
    accepted.write_text('{}\n')
    for cmd in (['init', '-q', '-b', 'main'], ['add', '-A'],
                ['-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'init']):
        subprocess.run(['git', '-C', str(r), *cmd], check=True)
    return r, yaml, accepted


def test_precondition_refuses_a_pre_existing_config_edit(tmp_path, monkeypatch):
    """MUSHY-142: a hand edit sitting in the tree must stop the push, not get
    silently folded into the automated commit."""
    r, yaml, accepted = _repo(tmp_path)
    monkeypatch.setattr(pcp, 'REPO_ROOT', r)
    monkeypatch.setattr(pcp, 'YAML', yaml)
    monkeypatch.setattr(pcp, 'ACCEPTED', accepted)

    assert pcp.precondition_refusal() is None

    yaml.write_text('    pid_kp: 0.99  # hand tune, not yet committed\n')
    refusal = pcp.precondition_refusal()
    assert refusal is not None and 'fc_config.yaml' in refusal


def test_precondition_refuses_off_main(tmp_path, monkeypatch):
    r, yaml, accepted = _repo(tmp_path)
    monkeypatch.setattr(pcp, 'REPO_ROOT', r)
    monkeypatch.setattr(pcp, 'YAML', yaml)
    monkeypatch.setattr(pcp, 'ACCEPTED', accepted)
    subprocess.run(['git', '-C', str(r), 'checkout', '-q', '-b', 'side'], check=True)
    assert 'not main' in pcp.precondition_refusal()


def test_precondition_ignores_unrelated_dirt(tmp_path, monkeypatch):
    """Unrelated dirty files are the post-write check's job; they must not
    block a push, or a stray scratch file would stop every nightly run."""
    r, yaml, accepted = _repo(tmp_path)
    monkeypatch.setattr(pcp, 'REPO_ROOT', r)
    monkeypatch.setattr(pcp, 'YAML', yaml)
    monkeypatch.setattr(pcp, 'ACCEPTED', accepted)
    (r / 'scratch.txt').write_text('x')
    assert pcp.precondition_refusal() is None


def test_dirty_paths_keeps_the_first_paths_full_name(tmp_path, monkeypatch):
    """git()'s strip() ate the leading space of porcelain's status column on
    the first line, truncating that path by one character (MUSHY-142 r2)."""
    r, yaml, accepted = _repo(tmp_path)
    monkeypatch.setattr(pcp, 'REPO_ROOT', r)
    monkeypatch.setattr(pcp, 'YAML', yaml)
    monkeypatch.setattr(pcp, 'ACCEPTED', accepted)
    yaml.write_text('x\n')
    accepted.write_text('{"a": 1}\n')
    assert pcp.dirty_paths() == pcp.ours()
