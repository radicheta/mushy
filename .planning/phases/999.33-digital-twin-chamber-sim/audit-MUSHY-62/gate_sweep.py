import sys; sys.path.insert(0,'src/chambers/fc-core')
from fc_core.sim.chamber_model import ChamberParams
from fc_core.sim.replay import run_closed_loop, DEFAULT_BAND, DEFAULT_GAINS
FQ=7.0337
print("Q      F      p2p   bursts period  duty_cmd rh_min rh_max")
for q in (0.658,0.9634,1.242,1.5,1.899,2.1,2.5):
    m=run_closed_loop(14.0, params=ChamberParams(moisture_loss_m3_per_h=q, fill_g_per_h=q*FQ), band=DEFAULT_BAND, gains=DEFAULT_GAINS, rh0=90.0)
    per = f"{m.cycle_period_h:.2f}" if m.cycle_period_h else "none"
    print(f"{q:<6.3f} {q*FQ:<6.2f} {m.rh_p2p:5.2f} {m.burst_count:6d} {per:>6s}  {m.duty_mean_commanded:.3f}   {m.rh_min:.2f}  {m.rh_max:.2f}")
