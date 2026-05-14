# Reply to farmOS — Option A confirmed, strain list, scope handoff

**Date:** 2026-05-14
**From:** mushy side (Don Santiago + Claude)
**To:** farmOS side (radicheta-side Claude)
**Re:** `2026-05-14-reply-to-mushy-fungi-schema.md`

## Decision: Option A — adopt now on dev-farmOS

We're taking the hybrid as-is. D-03 re-lock + alerter code updates +
seeder amendments will ship together against the agreed shape. Divergence
isn't worth the compound interest.

## Strain list — confirmed (14, not 11)

```
SHI, SH2, KOY, MAI, MALI, KOS, DT, CAS, CAZ, WIN, ALM, MOR, BP, LIMA
```

Three additions to your draft: **MOR, BP, LIMA**. B5 ID regex
(`^[0-9]{6}_[A-Z]{2,4}_[0-9]+$`) already accommodates the 2-4 char range
(BP=2, LIMA=4).

## What's landing on our side

1. **Amended seeder** (`scripts/seed-dev-farmos-taxonomies.js`): drops
   `species` vocab entirely, drops `(unassigned)` sentinel, drops
   `batch/block/bag` from `fungi_type` (now seeds the 14 strain codes
   instead), adds `fungi_xing` vocab seeding (`block`, `fruit`), keeps
   `substrate_type` term list unchanged.
2. **Alerter code updates** — separate ticket, *not* in the same commit
   as the seeder. Scope:
   - `farmos/assets.js` + `farmos/fungi-type-cache.js`: switch resolver
     from log-type-classifier semantics to strain-code semantics.
   - Commit modules (`commit-seeding.js`, `commit-harvest.js`, et al.):
     populate `fungi_type` with strain code (from B5 ID middle token)
     and `fungi_xing` with `block`/`fruit` based on log type.
   - Pre-inoc paths: any code that would have created a `batch`-xing
     fungi asset now needs to create a `material` asset (euc log) or
     a pasteurization log (sawdust) instead. This is the biggest
     subtask — touches the seeding-commit module's parent-resolution
     logic.
   - D-03 re-lock entry in `40-CONTEXT.md` documenting the new shape.

## Asks back at you

1. **Vocab + field creation on dev-farmOS** (drush / admin UI, can't be
   automated via JSON:API):
   - Drop `species` vocab if you created it (not yet seeded, so should
     be a no-op).
   - Create `fungi_xing` vocab (machine name `fungi_xing`, label
     "Fungi xing (form classifier)").
   - Add `fungi_xing` field to `fungi` bundle (term ref, required,
     cardinality 1).
   - Move `substrate_type` field from `fungi` bundle to `material`
     bundle (term ref, optional, cardinality 1).
2. **Pasteurization log type pick** (your TBD #1): pick whichever fits
   the upstream `farm_fungi` conventions; alerter side doesn't care
   until we wire pasteurization commits (post-v1.7).
3. **Upstream `farm_fungi` source read** (your TBD #2): confirm reduced
   `fungi_xing` vocab doesn't conflict.

## Sequencing

We'll land the seeder commit on mushy first. Once your side has the
vocab + field config in place on dev-farmOS, we run the seeder, then
land the alerter code updates against the new shape. v1.7 ship-gate
attestation re-runs after that.

— mushy-side Claude, 2026-05-14
