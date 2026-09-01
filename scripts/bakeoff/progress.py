"""MUSHY-150: bake-off progress. Step counts come from the checkpoints, which
carry the exact iteration -- the logs only print every steps//8.

    .venv/bin/python scripts/bakeoff/progress.py
"""
import os, re, subprocess, time
import torch

R = 'scripts/bakeoff/results'
# Mirrors launch.sh: every candidate on every seed. Kept in step with it --
# a hardcoded job list here silently reports "all done" on a bigger matrix.
SEEDS = int(os.environ.get('SEEDS', 4)) + 1
JOBS = [(s, c, k) for s in ('inter', 'chrono')
        for c in ('alice', 'charlie', 'gary', 'herbert', 'irving', 'frank')
        for k in range(SEEDS)]


def sniff_steps():
    """launch.sh passes --steps on the command line, so read it from there. A
    hardcoded default lies loudly: 1000 against the running 1500-step batch
    showed live jobs at 112% "done" and put the ETA 3.5 h short."""
    if os.environ.get('STEPS'):
        return int(os.environ['STEPS'])
    ps = subprocess.run(['ps', '-eo', 'args'], capture_output=True, text=True).stdout
    m = re.search(r'run\.py .*--steps (\d+)', ps)
    return int(m.group(1)) if m else 1000


def hms(s):
    s = int(max(s, 0))
    return f'{s//3600}h{s%3600//60:02d}m' if s >= 3600 else f'{s//60}m{s%60:02d}s'


def live():
    """{tag: elapsed_s} for the running jobs. Elapsed/step is a far better rate
    than the log gives -- the log only prints every steps//8, so a job under
    125 steps has no second timestamp to difference."""
    out = {}
    ps = subprocess.run(['ps', '-eo', 'etimes,args'], capture_output=True, text=True).stdout
    for ln in ps.splitlines():
        m = re.search(r'^\s*(\d+).*run\.py --split (\w+) --candidates (\w+) --seed (\d+)', ln)
        if m:
            out[f'{m.group(2)}-{m.group(3)}-s{m.group(4)}'] = int(m.group(1))
    return out


def main():
    global STEPS
    STEPS = sniff_steps()
    elapsed = live()
    seen, todo, run, dead = {}, [], [], []
    for split, c, k in JOBS:
        tag = f'{split}-{c}-s{k}'
        if os.path.exists(f'{R}/{tag}.json'):
            it, state = STEPS, 'done'
        elif os.path.exists(f'{R}/{tag}.json.{c}.ckpt'):
            it = torch.load(f'{R}/{tag}.json.{c}.ckpt', weights_only=False)['it']
            # a live job touches its checkpoint; a stale one was interrupted.
            age = time.time() - os.path.getmtime(f'{R}/{tag}.json.{c}.ckpt')
            state = 'run' if age < 600 else f'STALE {hms(age)}'
        else:
            it, state = 0, 'queue'
        # elapsed/it is exact for a running job; fall back to a sibling seed
        # of the same candidate for the ones still queued.
        r = (elapsed[tag] / it) if (tag in elapsed and it) else seen.get(c)
        if r:
            seen[c] = r
        left = (STEPS - it) * (r or 0)
        print(f'{tag:20s} {it:5d}/{STEPS}  {100*it/STEPS:5.1f}%  '
              f'{(f"{r:5.2f}s/step" if r else "     -    ")}  '
              f'{state:12s} {hms(left) if r and it < STEPS else ""}')
        (todo if state == 'queue' else run if state == 'run' else dead)\
            .append((c, STEPS - it))

    # wall-clock ETA: remaining work spread over the 8 slots, since queued jobs
    # only start as running ones free up.
    par = int(os.environ.get('PAR', 8))
    work = sorted(((n * seen.get(c, 0)) for c, n in run + todo + dead), reverse=True)
    slots = [0.0] * par
    for w in work:                       # greedy: next job takes the free slot
        i = slots.index(min(slots)); slots[i] += w
    done = sum(1 for s, c, k in JOBS if os.path.exists(f'{R}/{s}-{c}-s{k}.json'))
    print(f'\n{done}/{len(JOBS)} jobs finished, {len(run)} running, {len(todo)} queued'
          f'  --  est {hms(max(slots))} remaining at PAR={par}')


if __name__ == '__main__':
    main()
