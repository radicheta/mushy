"""MUSHY-154: score the bake-off on ONE month, because the plant changed.

Santi, 2026-09-03: undocumented changes were made to the setup since April.
The corpus runs 2026-04-12 to 2026-08-30, so every candidate has been fitted
across an unknown number of plant changes -- and chrono is hit hardest by
construction, since it trains on 04-06 and tests on 07-08, i.e. it is asked to
extrapolate across exactly the period the changes fall in. A structural
conclusion drawn from that split could be reading hardware edits as physics.

Subsets an existing corpus.npz by month rather than re-querying Timescale:
the daily rows are independent, and run.py's load() recomputes the EWMAs and
the warm-up mask from the subset's own dates, so slicing days is safe.

    .venv/bin/python scripts/bakeoff/subset_corpus.py 8      # August only
    .venv/bin/python scripts/bakeoff/subset_corpus.py 6      # size-matched control
    BAKEOFF_CORPUS=scripts/bakeoff/corpus-m08.npz .venv/bin/python scripts/bakeoff/run.py ...

THE SPLITS ARE NOT THE FULL-CORPUS SPLITS, and the chrono one especially is
not comparable:

  inter  -- IDENTICAL rule to prep.py (week != (month-4)%4), so this really is
            the same interleaved question asked on fewer days.
  chrono -- prep.py's rule is `month <= 6`, which is degenerate inside a single
            month. Here it is the first 21 days against the last 8. That tests
            extrapolation over ONE WEEK, not two months, so it is a far weaker
            distribution shift and a good chrono score here does NOT mean what
            a good chrono score means on the full corpus. Read inter first.

SAMPLE SIZE IS THE CONFOUND: 29 days against 133 is a 4.5x cut, and the
high-capacity candidates (frank, irma) lose more from less data than the
4-parameter physics ones do. So a ranking change on August alone cannot be
attributed to the cleaner regime. That is what the size-matched control month
is for -- run another ~30-day month and compare the RANKING, not the score.
"""
import sys, os, numpy as np

SRC = os.environ.get('BAKEOFF_CORPUS', 'scripts/bakeoff/corpus.npz')
CHRONO_TRAIN_DOM = 21          # first 21 days fit, last 8 score


def main(months):
    z = np.load(SRC)
    dates = z['dates']
    n = len(dates)
    mon = np.array([int(str(d)[5:7]) for d in dates])
    dom = np.array([int(str(d)[8:10]) for d in dates])
    sel = np.isin(mon, months)
    if sel.sum() < 14:
        raise SystemExit(f'only {sel.sum()} days for months {months}; too few to split')

    week = np.minimum((dom[sel] - 1) // 7, 3)          # prep.py's rule, verbatim
    test_week = (mon[sel] - 4) % 4
    out = {}
    for k in z.files:
        v = z[k]
        # dt is a scalar; month/dates and every daily array share dim 0 == n.
        out[k] = v[sel] if (v.ndim >= 1 and v.shape[0] == n) else v
    out['month'] = mon[sel]
    out['inter_train'] = week != test_week
    out['chrono_train'] = dom[sel] <= CHRONO_TRAIN_DOM

    tag = 'm' + '-'.join(f'{m:02d}' for m in months)
    dst = f'scripts/bakeoff/corpus-{tag}.npz'
    np.savez_compressed(dst, **out)
    print(f'wrote {dst}: {sel.sum()} days  {str(dates[sel][0])} -> {str(dates[sel][-1])}')
    print(f'  interleaved    train {out["inter_train"].sum():3d}  '
          f'test {(~out["inter_train"]).sum():3d}')
    print(f'  chronological  train {out["chrono_train"].sum():3d}  '
          f'test {(~out["chrono_train"]).sum():3d}   (dom <= {CHRONO_TRAIN_DOM}, ONE WEEK of shift)')
    if (~out['inter_train']).sum() < 4 or (~out['chrono_train']).sum() < 4:
        print('  WARNING: a test side under 4 days -- the score is noise')


if __name__ == '__main__':
    main([int(a) for a in (sys.argv[1:] or ['8'])])
