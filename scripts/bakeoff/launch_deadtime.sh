#!/usr/bin/env bash
# MUSHY-150: the Q-driver comparison with DEAD TIME HELD EQUAL across
# candidates, swept over a range instead of fitted per candidate per seed.
#
# Why: fitted independently, dead time is the least identifiable parameter in
# the harness. Alice alone spanned 45.1-139.9 s across seeds, injecting 0.0174
# of spread into a charlie-vs-alice margin whose entire effect size is 0.0036.
# The structure question cannot be read through 4x its own size in noise.
#
# Why a SWEEP and not one value: if the ranking flips depending on which dead
# time we freeze, that flip IS the answer -- it says the comparison is not
# identified and no amount of seeds will rescue it. One value would have hidden
# exactly that. 360 s is included on purpose: it is the shipped constant, taken
# on faith since 2026-08-08, and this measures what it costs.
#
# Only the driver family + irving. frank and herbert are not part of the
# Q-driver question and frank is the slowest fit in the harness.
set -u
cd "$(dirname "$0")/../.."
STEPS=${STEPS:-3000}
OUT=scripts/bakeoff/results/deadtime-sweep
mkdir -p "$OUT/logs"

# poll, never pkill: matching run.py by pattern kills the invoking shell.
while [ "$(pgrep -fc 'bakeoff/run\.py' || true)" -ge 4 ]; do sleep 60; done
echo "machine drained at $(date -Is), starting sweep"

for d in 60 90 120 150 180 360; do
  for c in alice charlie gary irving; do
    for s in $(seq 0 "${SEEDS:-4}"); do echo "$d $c $s"; done
  done
done | xargs -P "${PAR:-8}" -I{} bash -c '
  set -- {}
  d=$1; c=$2; seed=$3
  tag="d$d-$c-s$seed"
  if [ -s '"$OUT"'/$tag.json ]; then echo "skip $tag"; exit 0; fi
  OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python scripts/bakeoff/run.py \
    --split inter --candidates "$c" --seed "$seed" --steps '"$STEPS"' \
    --dead-time-s "$d" --out '"$OUT"'/$tag.json \
    > '"$OUT"'/logs/$tag.log 2>&1
  echo "done $tag rc=$?"
'
echo "DEADTIME SWEEP FINISHED"
