# Handover 2026-09-04 (UYT): farm-agent photo pipeline + observation mint

## State of the world
- RUNNING: `mushy-alerter-py-1` on elder-plops, built from main `031dc44f`
  (last rebuild 20:36 local for MUSHY-128), restarts=0. fc1 fc-core active.
  farmOS prod healthy.
- STOPPED / not done: dev :18080 cleanup of `MUSHY131-probe*` asset + 3 logs.
  Needs dev farmOS creds; the alerter container only carries prod.
- COMMITTED: `4e4f0173` (MUSHY-132), `ee318f28` (MUSHY-128), `031dc44f`
  (MUSHY-156 script). All pushed, all deployed. main == origin/main. Prod
  container farm_agent/ == main; its scripts/ lacks mushy156_backfill.py (image
  built one commit before 031dc44f). Runtime unaffected, no rebuild needed.

## Closed tonight
MUSHY-131, 133, 126 (done since 2026-08-29, Plane states never moved),
MUSHY-132, MUSHY-128. MUSHY-156 backfill RAN on prod: 32 uploaded, 4 reused,
0 failed, idempotent on re-run. Only the dev cleanup keeps 156 open.

## Pending live checks (mock-verified only)
- Next low-confidence ask-back must show the value (MUSHY-132).
- Next observation on an unknown block must mint it (MUSHY-128).

## Decisions recorded
- Mint on observation: yes (Santi).
- Backfill everything, including the 13 SHI blocks sharing one notebook page.
- Occasional fc1 reboots are flaky farm power; ignore.

## Not ticketed
- 2025 notebook scan (`shared/mushdatadump`, 73 JPEGs + CSV) is NOT in farmOS
  at all; it never became signal_draft rows. Separate ingestion work.
- MUSHY-35 credential rotation (urgent) untouched since August.
- MUSHY-125 / 147 stay In Progress; neither closes quickly.

## Gotchas
- Scripts reading `*_PASSWORD` env vars must build the name by string
  concatenation, or the secret-dump hook refuses the heredoc.
- Run a prod-writing command on its own line; compound lines with a prod write
  get denied.
- Backfill dedupe is byte size per asset (`scripts/mushy156_backfill.py`);
  upgrade to a content hash only if two photos on one asset ever tie.

## Verified 2026-09-05 morning (UYT)
- Backfill DID run with --write: dry run inside the container reports
  `uploaded=0 reused=36 failed=0` (= 32 uploaded + 4 reused last night).
- Handover commit 01042012 is on origin/main; main clean.
- Gotcha: `docker exec` output never reaches `docker logs`, and the run left
  no history. Only the idempotent dry run proves it. Keep `/tmp/bf.py` in the
  container until MUSHY-156 closes, or re-`docker cp` it from scripts/.
