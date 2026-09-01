#!/usr/bin/env bash
# MUSHY-150: frank recovery test. 2 candidates x 2 excitation regimes.
# alice is the pipeline control (teacher's own structure, MUST reach ~0);
# frank is the question. See recover.py for how to read the 2x2.
#
# WAITS for the machine to drain first -- the bake-off and the unbounded-tau
# refit are already holding 13 of 16 cores, and frank is the slowest fit in
# the harness (~7.4 s/step). Starting now would just slow everything down.
set -u
cd "$(dirname "$0")/../.."
STEPS=${STEPS:-1500}
OUT=scripts/bakeoff/results/recover
mkdir -p "$OUT/logs"

# poll, do not pkill: matching run.py by pattern is how you kill your own
# shell. This only ever COUNTS.
while [ "$(pgrep -fc 'bakeoff/run\.py' || true)" -ge 4 ]; do sleep 120; done
echo "machine drained at $(date -Is), starting"

for duty in real random; do
  for c in alice frank; do echo "$duty $c"; done
done | xargs -P 4 -I{} bash -c '
  set -- {}
  duty=$1; c=$2
  tag="$c-$duty"
  if [ -s '"$OUT"'/$tag.json ]; then echo "skip $tag"; exit 0; fi
  OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=scripts/bakeoff \
    .venv/bin/python scripts/bakeoff/recover.py \
    --candidates "$c" --duty "$duty" --steps '"$STEPS"' \
    --out '"$OUT"'/$tag.json > '"$OUT"'/logs/$tag.log 2>&1
  echo "done $tag rc=$?"
'
echo "RECOVERY JOBS FINISHED"
