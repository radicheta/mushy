#!/usr/bin/env bash
# Launch one candidate over 5 seeds x both splits. CAND picks it; the default
# is the franktuned GATE this script was written for (MUSHY-154 step 0), and
# `CAND=irma` is the run the gate cleared. Renamed from launch_franktuned.sh
# when irma needed the identical harness -- one script, so the two runs cannot
# drift apart in steps, seeds or output layout.
# franktuned == frank with the net at lr 1e-3 + weight decay 1e-4 instead of
# the shared 0.05 (see FrankTuned in run.py). If it still loses to alice on
# INTER, the corpus has no more signal to give and irma is moot; if it wins on
# inter but not chrono, the problem is extrapolation across the season, not
# missing signal. Those are different answers and only this run tells them
# apart.
#
# Writes into the main results dir under its own candidate name, so the paired
# analysis sees it next to alice and nothing overwrites the untuned frank rows.
set -u
cd "$(dirname "$0")/../.."
CAND=${CAND:-franktuned}
STEPS=${STEPS:-3000}
OUT=scripts/bakeoff/results
mkdir -p "$OUT/logs"

for split in inter chrono; do
  for s in $(seq 0 "${SEEDS:-4}"); do echo "$split $s"; done
done | xargs -P "${PAR:-10}" -I{} bash -c '
  set -- {}
  split=$1; seed=$2
  tag="$split-'"$CAND"'-s$seed"
  if [ -s scripts/bakeoff/results/$tag.json ]; then echo "skip $tag"; exit 0; fi
  OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python scripts/bakeoff/run.py \
    --split "$split" --candidates '"$CAND"' --seed "$seed" --steps '"$STEPS"' \
    --out scripts/bakeoff/results/$tag.json \
    > scripts/bakeoff/results/logs/$tag.log 2>&1
  echo "done $tag rc=$?"
'
echo "$CAND JOBS FINISHED"
