"""Is the shared duty path actually carrying Alice's score, or has the fitted
tau turned it into a slow daily ramp? Ablate and see."""
import sys, torch, numpy as np
sys.path.insert(0, 'scripts/bakeoff')
from run import CANDIDATES, rollout, load, score, ah_to_rh

tr, te, dt_s = load('inter')
ck = torch.load('scripts/bakeoff/results/inter-alice-s0.json.alice.ckpt', weights_only=False)
m = CANDIDATES['alice'](); m.load_state_dict(ck['model'])
tau = ck['log_tau'].exp()

def rmse(b, tau_s, duty=None):
    b = dict(b)
    if duty is not None:
        b['duty'] = torch.full_like(b['duty'], duty) if np.isscalar(duty) else duty
    with torch.no_grad():
        return float(score(rollout(m, tau_s, b, dt_s), b)[0].mean())

print(f'fitted tau      = {float(tau):9.0f} s  ({float(tau)/3600:.1f} h)')
print(f'as fitted            test rmse {rmse(te, tau):6.3f}')
print(f'duty ZEROED          test rmse {rmse(te, tau, 0.0):6.3f}')
print(f'duty at constant 0.5 test rmse {rmse(te, tau, 0.5):6.3f}')
print(f'tau forced to 600 s  test rmse {rmse(te, torch.tensor(600.0)):6.3f}')
print(f'tau 600 + duty zero  test rmse {rmse(te, torch.tensor(600.0), 0.0):6.3f}')

# how far does `applied` actually get, given it resets to 0 each day?
alpha = float(dt_s / tau)
n = te['duty'].shape[1]
print(f'\nalpha = {alpha:.2e}/step; after one full day applied reaches '
      f'{100*(1-np.exp(-alpha*n)):.1f}% of mean duty (starts each day at 0)')
print(f'mean duty in test = {float(te["duty"].mean()):.3f}')
