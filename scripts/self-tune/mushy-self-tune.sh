#!/usr/bin/env bash
# MUSHY-138 nightly: fit the last 14 days of probes, push if the guard passes.
set -euo pipefail
cd /mnt/slime-kingdom/opt/mushy
export PYTHONPATH=src/chambers/fc-core
REPORT="reports/self-tune/$(date -u +%F).json"
# MUSHY-143: refresh the Timescale weather table so the fit covers last
# night's probes. ONE Open-Meteo call per day (free tier: 10k/day, 5k/h,
# 600/min; CC-BY 4.0). Trailing 10 d so preliminary IFS hours get replaced
# by final ERA5 as it lands (~5 d delay); upsert, so re-runs are harmless.
# --out keeps the committed CSV fixture untouched. Failure is non-fatal:
# the fit runs on whatever the table already holds.
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
.venv/bin/python scripts/fetch-ambient-weather.py --fetch --load-timescale \
  --start "$(date -u -d '10 days ago' +%F)" --end "$(date -u +%F)" \
  --out "$TMP/ambient.csv" || echo "ambient refresh failed, fitting on stored weather"
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
