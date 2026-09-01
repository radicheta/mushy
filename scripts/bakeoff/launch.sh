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

# EVERY candidate gets seeds. Seeds were originally only run for the neural
# entries, and that made the leaderboard unreadable: eve's seed spread
# (0.444-0.629 worst-horizon) was 4x the gap between the top three physics
# candidates, so "charlie beats alice" could not be told from init noise.
# CULLED 2026-09-01 from 9 to 6 -- each cut has a reason, not a vibe:
#   bob   dominated. eve already showed a FLEXIBLE Q inside alice's structure
#         still loses to charlie's driver; bob is the weakest form of that
#         (linear in T). Nothing left for it to tell us.
#   dave  uninterpretable by construction: it swaps the wall state IN and the
#         C*dT term OUT, two changes at once. irving is its strict superset
#         (C=0 reproduces dave bit-for-bit) and asks the question properly.
#   eve   its question is answered -- a 6-input neural Q inside alice's
#         structure loses to charlie. gary asks what is left with ONE readable
#         input instead of six.
# The classes stay in run.py so archived results can still be re-scored.
jobs=()
for split in inter chrono; do
  for c in alice charlie gary herbert irving frank; do
    for s in $(seq 0 "${SEEDS:-4}"); do jobs+=("$c $split $s"); done
  done
done

printf '%s\n' "${jobs[@]}" | xargs -P "${PAR:-8}" -I{} bash -c '
  set -- {}
  c=$1; split=$2; seed=$3
  tag="$split-$c-s$seed"
  # resume: a finished job has written its JSON, so skip it. Jobs are
  # independent, so an interrupted batch restarts only what is missing.
  if [ -s scripts/bakeoff/results/$tag.json ]; then echo "skip $tag"; exit 0; fi
  OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python scripts/bakeoff/run.py \
    --split "$split" --candidates "$c" --seed "$seed" --steps '"$STEPS"' \
    --out scripts/bakeoff/results/$tag.json \
    > scripts/bakeoff/results/logs/$tag.log 2>&1
  echo "done $tag rc=$?"
'
echo "ALL JOBS FINISHED"
