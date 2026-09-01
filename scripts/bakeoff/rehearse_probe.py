"""MUSHY-150: run the duty probe's schedule through the FITTED chamber model on
RECORDED ambient, and see whether it stays inside the working band.

WHY THIS EXISTS. duty-probe.sh has its own dry run, but that one moves RH with
two eyeballed slopes -- no temperature, no ambient, no dead time, no reservoir.
It is there so the guard branches execute, and NOTHING about the chamber may be
concluded from it. This is the honest rehearsal: alice's fitted parameters, the
same rollout equations the bake-off scores, and real recorded temperature and
ambient AH from a past 48 h.

WHAT IT STILL IS NOT. (1) Temperature is EXOGENOUS here, replayed from the
chosen days -- in the chamber the humidifier and the cooling loop move it.
(2) 48 h free-running is ~300x the 10 min horizon the model was fitted on, and
this ticket has already measured that these models degrade into delayed copies
of their input far past their horizon. Read the OUTPUT as "does the schedule
drift out of band and how hard does the guard work", not as a prediction of
what RH will be at 03:00.

    .venv/bin/python scripts/bakeoff/rehearse_probe.py <dry-run.csv>
    .venv/bin/python scripts/bakeoff/rehearse_probe.py --control

--control is the instrument check and MUST be read first: it replays the same
48 h with the duty that was ACTUALLY commanded on those days and compares
against the RH that actually happened. If the model cannot track the real days,
nothing it says about a hypothetical schedule means anything.
"""
import csv, sys, datetime as dt
import numpy as np
import torch

sys.path.insert(0, 'scripts/bakeoff')
from run import CANDIDATES, CORPUS, V, ah_sat

RH_FLOOR, RH_CEIL, RH_RECOVER = 0.80, 0.98, 0.90
CKPT = 'scripts/bakeoff/results/chrono-alice-s0.json.alice.ckpt'


def schedule(path, dt_s, n):
    """Commanded duty per sample, from the dry run's CSV. The guard's own rows
    are DROPPED: this replays the SCHEDULE and lets the model's RH decide when
    the guard fires, which is the whole question."""
    rows = [r for r in csv.DictReader(open(path)) if not r['phase'].endswith('override')]
    t0 = dt.datetime.strptime(rows[0]['iso'], '%Y-%m-%dT%H:%M:%SZ')
    u = np.zeros(n)
    idx = [int((dt.datetime.strptime(r['iso'], '%Y-%m-%dT%H:%M:%SZ') - t0).total_seconds() / dt_s)
           for r in rows]
    for i, r in zip(idx, rows):              # step-and-hold to the next command
        if i < n:
            u[i:] = float(r['duty'])
    return u


def main(csv_path):
    control = csv_path == '--control' 
    z = np.load(CORPUS)
    dt_s = float(z['dt'])
    ok = z['valid'].mean(1) > 0.999
    d = max(i for i in range(1, len(ok)) if ok[i] and ok[i - 1])   # last clean pair
    temp = np.concatenate([z['temp'][d - 1], z['temp'][d]])
    amb = np.concatenate([z['amb_ah'][d - 1], z['amb_ah'][d]])
    rh0 = z['rh'][d - 1][0]
    print(f'ambient replayed from {z["dates"][d-1]} + {z["dates"][d]}  '
          f'T {temp.min():.1f}-{temp.max():.1f} C  amb_ah {amb.min():.1f}-{amb.max():.1f} g/m3')

    ck = torch.load(CKPT, weights_only=False)
    m = CANDIDATES['alice']()
    m.load_state_dict(ck['model'])
    F, Q, C = float(m.logF.exp()), float(m.logQ.exp()), float(m.C)
    dead = float(m.delay_s())
    print(f'alice fitted: F {F:.3f}  Q {Q:.3f}  C {C:.3f}  dead {dead:.0f}s  ({CKPT})')

    n = len(temp)
    truth = np.concatenate([z['rh'][d - 1], z['rh'][d]])
    u_cmd = (np.concatenate([z['duty'][d - 1], z['duty'][d]]) if control
             else schedule(csv_path, dt_s, n))
    lag = int(round(dead / dt_s))
    dT = np.gradient(temp, dt_s)

    ah = rh0 / 100.0 * float(ah_sat(torch.tensor(temp[0])))
    sat = ah_sat(torch.tensor(temp)).numpy()
    rh = np.zeros(n)
    applied, mode = np.zeros(n), np.zeros(n)     # mode: 0 schedule 1 floor 2 ceiling
    state = 0
    for i in range(n):
        r = ah / sat[i]
        # ponytail: the guard rule is written here AND in duty-probe.sh. Two
        # copies, and only the shell one runs on fc1 -- if the thresholds move,
        # move them in both or this rehearsal quietly stops rehearsing.
        if state == 0 and r < RH_FLOOR: state = 1
        elif state == 0 and r > RH_CEIL: state = 2
        elif state == 1 and r >= RH_RECOVER: state = 0
        elif state == 2 and r <= RH_RECOVER: state = 0
        if control:
            state, u = 0, u_cmd[i]          # no guard: replay exactly what ran
        else:
            u = 1.0 if state == 1 else 0.0 if state == 2 else u_cmd[i]
        applied[i], mode[i], rh[i] = u, state, r * 100
        ud = applied[i - lag] if i >= lag else 0.0
        ah += (F * ud - Q * (ah - amb[i]) + C * dT[i]) / V * dt_s / 3600.0

    if control:
        err = rh - truth
        print(f'\nCONTROL -- recorded duty, recorded ambient, 48 h free run')
        print(f'  actual RH  min {truth.min():.1f}  max {truth.max():.1f}  mean {truth.mean():.1f}')
        print(f'  model RH   min {rh.min():.1f}  max {rh.max():.1f}  mean {rh.mean():.1f}')
        print(f'  rmse {np.sqrt((err ** 2).mean()):.1f} RH pts   bias {err.mean():+.1f}   '
              f'drift by hour 48 {err[-1]:+.1f}')
        print('\n  A 48 h free run is ~300x the 10 min horizon this model was fitted on.'
              '\n  If the numbers above are large, that is the instrument, not the schedule.')
        return
    ev = np.diff(np.concatenate([[0], mode]))
    nf = int(((mode == 1) & (ev != 0)).sum()); nc = int(((mode == 2) & (ev != 0)).sum())
    print(f'\nRH over 48 h: min {rh.min():.1f}  max {rh.max():.1f}  mean {rh.mean():.1f}')
    print(f'mean commanded duty {u_cmd.mean():.3f}  |  mean applied {applied.mean():.3f}')
    print(f'guard: {nf} floor episodes, {nc} ceiling episodes, '
          f'{(mode > 0).mean() * 100:.1f}% of the run overridden (closed loop, unusable)')
    print(f'time outside 80-98: {((rh < 80) | (rh > 98)).mean() * 100:.1f}%')
    np.savez('scripts/bakeoff/results/rehearsal.npz', rh=rh, duty=applied,
             cmd=u_cmd, mode=mode, temp=temp, amb=amb, dt=dt_s)
    print('wrote scripts/bakeoff/results/rehearsal.npz')


if __name__ == '__main__':
    main(sys.argv[1])
