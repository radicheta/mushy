#!/usr/bin/env bash
# MUSHY-150: eve refit with tau unbounded (exp parameterisation + smooth ZOH
# alpha). Separate results dir on purpose -- the duty path DIFFERS from the
# main bake-off, so these numbers must never be pasted into that leaderboard.
# Score them against a bounded eve rerun under this same launcher instead.
set -u
cd "$(dirname "$0")/../.."
STEPS=${STEPS:-1500}
OUT=scripts/bakeoff/results/tau-unbounded
mkdir -p "$OUT/logs"

for s in $(seq 0 "${SEEDS:-4}"); do echo "$s"; done | xargs -P "${PAR:-5}" -I{} bash -c '
  seed={}
  tag="inter-eve-s$seed"
  if [ -s '"$OUT"'/$tag.json ]; then echo "skip $tag"; exit 0; fi
  OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python scripts/bakeoff/run.py \
    --split inter --candidates eve --seed "$seed" --steps '"$STEPS"' \
    --tau-unbounded --out '"$OUT"'/$tag.json \
    > '"$OUT"'/logs/$tag.log 2>&1
  echo "done $tag rc=$?"
'
echo "TAU-UNBOUNDED JOBS FINISHED"
