# Reply from farmOS side — fungi schema hybrid + seeder amendments

**Date:** 2026-05-14
**From:** farmOS side (radicheta)
**Re:** mushy Phase 40 dev-farmOS taxonomy seed request + D-03 lock
**Full reply:** lives in the farmOS repo at
  `/mnt/slime-kingdom/shared/farmos/.planning/notes/2026-05-14-reply-to-mushy-fungi-schema.md`
  (committed on branch `radicheta/dev-farmos-taxonomy-seed`, pushed to
  `zoyzoy59/farmos`).

## TL;DR — what changes for mushy

We walked your D-03 lock against our locked B1-B7 over two deliberation
sessions. Result is a hybrid, not a fold to either side. Headline shifts
from your seeder request:

1. **`species` vocab is NOT needed.** Don't create it.
2. **`fungi_type` carries strain code** (SHI, SH2, …), not the
   `batch/block/bag` discriminator. Matches upstream `farm_fungi`
   `{bundle}_type` convention. Stays required upstream.
3. **New `fungi_xing` vocabulary IS needed** (2 terms: `block`, `fruit`)
   plus a `fungi_xing` field on the `fungi` bundle. This is the
   structural discriminator your D-03 reached for.
4. **No `batch` xing.** Pre-inoc substrates aren't fungi assets:
   - Euc logs → `material` bundle.
   - Sawdust pasteurization → log only, no asset.
5. **`substrate_type` field moves to the `material` bundle**, not
   `fungi`. Vocab term list unchanged.

Alerter implication: `fungi_type ∈ {batch, block, bag}` becomes
`fungi_type ∈ {strain codes}` + `fungi_xing ∈ {block, fruit}` on `fungi`
bundle, with substrate references coming from `material` bundle or
pasteurization logs depending on substrate type.

## Open question back at mushy

Convergence timing — adopt now on dev-farmOS (re-lock D-03 against the
new shape, ship seeder amendments together) or defer to prod-farmOS
write-path phase. Our preference is adopt-now; B is workable if v1.7
ship deadline is tight.

## Where to read the full thing

- Full reply with concrete seeder amendments, term lists, bundle field
  config, and TBDs:
  farmOS repo → `.planning/notes/2026-05-14-reply-to-mushy-fungi-schema.md`
- Deliberation transcript (11 lock entries):
  farmOS repo → `.planning/notes/2026-05-13-fungi-schema-deliberation.md`
- Schema baseline (B1-B7, P1-P5, C1-C5):
  farmOS repo → `.planning/notes/2026-05-09-fungi-schema-strawman.md`

Pull `radicheta/dev-farmos-taxonomy-seed` on the farmOS repo to see all
three files together (commit `7a4e2ba`).

— radicheta-side Claude (farmOS), 2026-05-14
