#!/usr/bin/env bash
# MUSHY-138 nightly: fit the last 14 days of probes, push if the guard passes.
set -euo pipefail
cd /mnt/slime-kingdom/opt/mushy
export PYTHONPATH=src/chambers/fc-core
REPORT="reports/self-tune/$(date -u +%F).json"
if ! .venv/bin/python scripts/self-tune/fit-probes.py --days 14 --out "$REPORT"; then
  rc=$?
  if [ "$rc" -eq 3 ]; then
    echo "fit invalid, not pushing"
    exit 0
  fi
  echo "fit-probes failed (exit $rc)"
  exit "$rc"
fi
.venv/bin/python scripts/self-tune/push-chamber-params.py "$REPORT" ${SELF_TUNE_DRY_RUN:+--dry-run}
