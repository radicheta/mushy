"""Run: PYTHONPATH=src/chambers/fc-core .venv/bin/python -m pytest -q scripts/self-tune/test_fit_probes.py"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location('fit_probes', Path(__file__).with_name('fit-probes.py'))
fp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fp)


def test_resample_holds_last_value_on_uniform_grid():
    rows = [(0.0, 90.0), (7.0, 90.5), (25.0, 91.0)]
    grid = fp.resample(rows, t0=0.0, t1=40.0, dt=10.0)
    assert grid == [90.0, 90.5, 90.5, 91.0]


def test_relay_edges_to_held_state():
    # Sample-and-hold reports the value AT each grid instant (t=0,10,20,30,40):
    # the t=10 sample predates the t=12 edge, so it still reads 0. The task
    # brief's own expected array here ([...,1.0,1.0,1.0,...]) does not match
    # its own resample() -- corrected to what plain hold-last-value produces.
    edges = [(0.0, 0.0), (12.0, 1.0), (33.0, 0.0)]
    assert fp.resample(edges, t0=0.0, t1=50.0, dt=10.0, initial=0.0) == [0.0, 0.0, 1.0, 1.0, 0.0]
