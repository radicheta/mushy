"""MUSHY-154: irma is alice + a zero-init residual. The whole claim that it
"cannot lose by construction" rests on step 0 being alice EXACTLY, so that is
pinned here rather than assumed. A last layer merely scaled down (as eve and
gary do) would pass a loose tolerance and quietly start somewhere else.

    PYTHONPATH=scripts/bakeoff .venv/bin/python -m pytest -q scripts/bakeoff/test_irma.py
"""
import sys, torch
sys.path.insert(0, 'scripts/bakeoff')
from run import CANDIDATES, V, ah_sat


def _batch(n=4):
    g = torch.Generator().manual_seed(0)
    r = lambda *s: torch.rand(*s, generator=g, dtype=torch.float64)
    return dict(ah=8.0 + r(n), aux=(), u=r(n), T=10.0 + 4 * r(n),
                dT_dt=r(n) - 0.5, amb=6.0 + r(n),
                ctx=dict(t_ew30=10.0 + 4 * r(n), u_ew5=r(n), u_ew30=r(n)))


def test_step0_is_alice_bit_for_bit():
    """Zero-init means IDENTICAL, not merely close -- assert exact equality."""
    torch.manual_seed(0)
    irma = CANDIDATES['irma']()
    alice = CANDIDATES['alice']()
    b = _batch()
    d_i, _ = irma.deriv(b['ah'], (), b['u'], b['T'], b['dT_dt'], b['amb'], b['ctx'])
    d_a, _ = alice.deriv(b['ah'], (), b['u'], b['T'], b['dT_dt'], b['amb'], b['ctx'])
    assert torch.equal(d_i, d_a), (d_i - d_a).abs().max()


def test_correction_is_live_once_the_net_moves():
    """The mirror of the above: zero at init must be the INIT, not a dead path.
    A residual wired up wrong would pass test one forever."""
    irma = CANDIDATES['irma']()
    with torch.no_grad():
        irma.net[-1].bias.fill_(1.0)
    b = _batch()
    d_i, _ = irma.deriv(b['ah'], (), b['u'], b['T'], b['dT_dt'], b['amb'], b['ctx'])
    d_a, _ = CANDIDATES['alice']().deriv(
        b['ah'], (), b['u'], b['T'], b['dT_dt'], b['amb'], b['ctx'])
    assert torch.allclose(d_i - d_a, torch.full_like(d_i, 1.0 / V))


def test_net_params_are_found_by_the_optimiser_split():
    """fit() splits the param groups on model.net.parameters(); if the module
    were named anything else the net would silently train at lr 0.05 -- the
    exact rig this candidate exists to avoid."""
    irma = CANDIDATES['irma']()
    assert irma.NET_LR == 1e-3 and irma.NET_WD > 0
    assert {id(p) for p in irma.net.parameters()} <= {id(p) for p in irma.parameters()}
    assert any(p.requires_grad for p in irma.net.parameters())
