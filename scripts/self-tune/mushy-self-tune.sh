#!/usr/bin/env bash
# MUSHY-138 nightly: fit the last 14 days of probes, push if the guard passes.
set -euo pipefail
cd /mnt/slime-kingdom/opt/mushy
export PYTHONPATH=src/chambers/fc-core
REPORT="reports/self-tune/$(date -u +%F).json"
set +e
.venv/bin/python scripts/self-tune/fit-probes.py --days 14 --out "$REPORT"
rc=$?
set -e
if [ "$rc" -eq 3 ]; then
  echo "fit invalid, not pushing"
  exit 0
elif [ "$rc" -ne 0 ]; then
  echo "fit-probes failed (exit $rc)"
  exit "$rc"
fi
# Fail-safe by hand: the push is a dry run UNLESS SELF_TUNE_PUSH=1 is set.
.venv/bin/python scripts/self-tune/push-chamber-params.py "$REPORT" \
  $([ "${SELF_TUNE_PUSH:-0}" = 1 ] || echo --dry-run)
