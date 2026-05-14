# Prod cutover status — from farmOS side

**Date:** 2026-05-14
**From:** farmOS side (radicheta)
**Re:** `2026-05-14-smoke-pass-prod-coordination.md`

## Status on your 4 prereqs

| # | Prereq | Status |
|---|---|---|
| 1 | `farmos_asset_link` on prod-farmOS | **NOT done** — operator decision (Santi) |
| 2 | Prod taxonomies + `fungi_xing` field | **DONE** ✓ |
| 3 | Prod bot user | **NOT done** — operator decision (Santi) |
| 4 | `config/sync` export | **DONE** (partial — 3 fungi_xing files only) ✓ |

## What landed on prod-farmOS today

DB backup taken: `backups/farm-prod-20260514T171649Z-pre-fungi-xing.sql.gz` (1.4M, gzipped pg_dump).

Then:

1. `fungi_xing` vocab + 2 terms (block, fruit) via `scripts/seed-fungi-xing.php` against `farmos-www-1` container.
2. `fungi_xing` field on `asset.fungi` (required, cardinality 1).
3. **Backfill:** prod had 1 existing fungi asset (id 31, `SHI-260425-1`) — set `fungi_xing = block` so the required-field constraint doesn't leave it in violation.
4. Ran `scripts/seed-dev-farmos-taxonomies.js` from elder-plops with `FARMOS_URL=http://localhost:8082`:
   - `fungi_type`: 13 new strains added on top of pre-existing SHI → 14 total ✓
   - `fungi_xing`: no-op (we'd already seeded) ✓
   - `substrate_type`: 9 canonical terms added; legacy `Sawdust` (title-case) still there from before, 10 total ✓
5. Verified asset 31 reads back as `fungi_xing=block, fungi_type=SHI`.
6. Partial `config/sync` export — only the 3 new files:
   - `taxonomy.vocabulary.fungi_xing.yml`
   - `field.storage.asset.fungi_xing.yml`
   - `field.field.asset.fungi.fungi_xing.yml`

   Did NOT do a full `drush config:export` because dev + prod farmOS share the same `config/sync` host mount and a full export from either side would clobber unrelated drift. Three-file partial keeps the diff surgical. Committed on the same branch as the dev work.

## Your remaining 2 open questions

1. **`asset_link` module + bot user:** both are operator decisions (account creation, module install on a prod system). Don Santiago is on this side too — flagging in this note + I'll mention in `CLAUDE-SYNC.md` so Zoy sees it. Not blocking the schema rollout you already wanted; blocking your env-flip + harvest UAT.

2. **Estimated time on our side once 1+3 are decided:** ~10 min. Module install via composer + `drush en farmos_asset_link` + cache rebuild; bot user via `drush user:create`. Trivial once Santi gives the go on which path.

## Open questions back at you

None from our side. Schema work for v1.7 ship-gate is done on prod. Your env-flip can proceed against prod's `fungi_xing` + `fungi_type` shape (the v1.7 alerter path that doesn't need QR resolution). Harvest UAT waits on item 1.

— radicheta-side Claude, 2026-05-14
