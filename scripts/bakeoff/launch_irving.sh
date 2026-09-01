#!/usr/bin/env bash
# MUSHY-150: irving only, both splits. Writes into the MAIN results dir with
# the same tag scheme, because irving belongs in the main leaderboard -- it is
# the same duty path and the same loss as every other candidate. launch.sh and
# progress.py both list it now, so a later full rerun picks it up too.
#
# PAR=3 on purpose: the bake-off, the unbounded-tau refit and the queued
# recovery test are all sharing this machine.
set -u
cd "$(dirname "$0")/../.."
STEPS=${STEPS:-1500}
OUT=scripts/bakeoff/results
mkdir -p "$OUT/logs"

for split in inter chrono; do
  for s in $(seq 0 "${SEEDS:-4}"); do echo "$split $s"; done
done | xargs -P "${PAR:-3}" -I{} bash -c '
  set -- {}
  split=$1; seed=$2
  tag="$split-irving-s$seed"
  if [ -s scripts/bakeoff/results/$tag.json ]; then echo "skip $tag"; exit 0; fi
  OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python scripts/bakeoff/run.py \
    --split "$split" --candidates irving --seed "$seed" --steps '"$STEPS"' \
    --out scripts/bakeoff/results/$tag.json \
    > scripts/bakeoff/results/logs/$tag.log 2>&1
  echo "done $tag rc=$?"
'
echo "IRVING JOBS FINISHED"
