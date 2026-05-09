---
plan: 21-04
status: complete
started: 2026-04-19
completed: 2026-04-19
---

# Plan 21-04 — Health + Snapshots chip (D-06b)

## What was built

- `/health` extended with `snapshots: {last_24h, oldest_at}` plus flat aliases `snapshots_last_24h` and `oldest_snapshot_at`. Both sub-queries wrapped in a single try/catch — on DB failure fields are `null`, status stays 200 (gap over noise).
- Mission Control "Snapshots" chip added to the Phase 16 system-health strip (7th chip, right of "Grace"). Thresholds: green ≥200/24h, red ==0, grey for null (DB down) or 1..199 (degraded). Grey fallback `"bridge unreachable"` on fetch failure.

## Commits

- `5d0a3fd` feat(21-04): extend /health with snapshots stats (D-06b)
- `6ef161c` feat(21-04): add Snapshots chip to system-health strip (D-06b)

## Verification

Automated: `node --check` on both files, grep acceptance criteria, full jest suite 33/33 green (no regressions after the 21-03 fix).

Live (orchestrator ran):
- `docker compose up -d --build bridge openmct` from repo root
- `/health` returned correct shape with live data (`snapshots.last_24h: 1`, ISO `oldest_at`)
- `/camera/history` endpoint end-to-end (after fix commit `53a530c` patched ISO parsing + items key)
- Farmer confirmed 2026-04-19: "Snapshots chip is there but greyed out" — matches expected initial state for 1-row DB.

## Deviations

None in this plan. One deviation from sibling plan 21-03 caught during live verification and fixed in `53a530c` — `/camera/history` originally shipped with ms-epoch parsing and `rows` key, contrary to CONTEXT D-06a + RESEARCH Q3. Fix restores ISO-string params and `items` key.

## Key files

- `src/mission-control/bridge/src/index.js` (health handler + history endpoint)
- `src/mission-control/frontend/plugins/fruiting-chamber/plugin.js` (chip integration)
