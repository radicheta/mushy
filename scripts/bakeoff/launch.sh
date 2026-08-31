#!/usr/bin/env bash
# MUSHY-150: run the bake-off. Each job is one candidate x one split x one
# seed, independent, so they fan across cores. OMP_NUM_THREADS=1 per job --
# the rollout is kernel-launch/loop bound, so per-job threading buys nothing
# and only steals cores from the other jobs.
set -u
cd "$(dirname "$0")/../.."
STEPS=${STEPS:-1000}
OUT=scripts/bakeoff/results
mkdir -p "$OUT/logs"

jobs=()
for split in inter chrono; do
  for c in alice bob charlie dave; do
    jobs+=("$c $split 0")
  done
  for c in eve frank; do
    for s in 0 1 2; do jobs+=("$c $split $s"); done
  done
done

printf '%s\n' "${jobs[@]}" | xargs -P "${PAR:-8}" -I{} bash -c '
  set -- {}
  c=$1; split=$2; seed=$3
  tag="$split-$c-s$seed"
  OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python scripts/bakeoff/run.py \
    --split "$split" --candidates "$c" --seed "$seed" --steps '"$STEPS"' \
    --out scripts/bakeoff/results/$tag.json \
    > scripts/bakeoff/results/logs/$tag.log 2>&1
  echo "done $tag rc=$?"
'
echo "ALL JOBS FINISHED"
