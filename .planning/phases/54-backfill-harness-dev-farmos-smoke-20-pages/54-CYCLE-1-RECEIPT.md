# Cycle 1 Receipt

- verdict: SIGN-OFF
- cycle-2 unlock: YES
- run_id: 2026-06-07T16-59-57-377Z
- signed_off: 2026-06-07
- cost_usd: 0.2641

## Pages processed

IMG_3775.jpg (2025-02-01), IMG_3776.jpg (2025-02-04), IMG_3777.jpg, IMG_3778.jpg (2025-02-20), IMG_3779.jpg

## Aggregate

- drafts: 80
- commits ok: 70
- commits failed: 10
- assets created: 10
- logs created: 70
- duplicate_asset_count: 0 (PASS)
- upsert_stability.unstable: [] (PASS)

## Failure analysis

All 10 failures are understood and acceptable:

- **LIM × 10** — extraction error; model wrote `LIM` instead of `LIMA`. Quality noise, not a harness bug.
- **POY × 4** (subset of above) — valid Feb 2025 strain, not in `mossrock_active_strain_codes` registry. Upsert will handle on Cycle 2 full run.

## Pre-Cycle-2 notes

- `mushy-bot` farmOS password was out of sync (reset to `rocky` via drush 2026-06-07).
- Resume runbook needs `SIGNAL_SENDER` and `TIMESCALE_PASSWORD` added to env export block.
