# `fungi_type` semantics pushback -- parked options

**Date:** 2026-05-13
**Status:** parked; awaiting farmOS-team reply to seed-request
**Author this side:** mushy
**Owner that side:** radicheta (with Vikki/Zoy in CLAUDE-SYNC loop)
**Trigger:** Phase 40 Backlog B handoff (`mushy:scripts/seed-dev-farmos-taxonomies.js`, request note `farmos:.planning/notes/2026-05-13-dev-farmos-taxonomy-seed-request.md`). farmOS-side has already started a deliberation (`farmos:.planning/notes/2026-05-13-fungi-schema-deliberation.md`) and is paused mid-walk; they will almost certainly push back before running the seeder. This doc enumerates the responses we should have ready.

## 1. Background brief

The 2026-05-09 schema strawman (`farmos:.planning/notes/2026-05-09-fungi-schema-strawman.md`) defined `fungi_type` as the SPECIES field on `asset--fungi` (holds SHI, KOY, MAI, ...), with the lifecycle stage of an asset derived from logs and the "kind of fungi-thing" (batch vs. block vs. bag) inferred from a name prefix. When mushy implemented the Phase 40 farmOS write path, that strawman was treated as advisory; the shipped alerter code (locked Phase 40 D-03) instead uses `fungi_type` as a STRUCTURAL DISCRIMINATOR holding `batch`/`block`/`bag` and adds a SEPARATE `species` taxonomy relationship for the strain code. The seed request (`farmos:...2026-05-13-dev-farmos-taxonomy-seed-request.md`) flagged the divergence explicitly. farmOS-side has since walked rows 1-3 of a side-by-side comparison and tentatively locked a hybrid: `fungi_type` carries species (matching upstream `farm_fungi` intent), and a NEW custom field `fungi_xing` on the `fungi` bundle carries the structural discriminator (`batch`/`block`/`fruit` -- note `fruit`, not `bag`). They have NOT yet sent us this back as a reply; it lives in their deliberation file. This doc anticipates that reply.

## 2. Upstream evidence

Canonical contrib module is `farmOS/farm_fungi` (not symbioquine). Source pulled 2026-05-13 from branch `3.x`:

**`farm_fungi/src/Plugin/Asset/AssetType/Fungi.php`** -- defines two bundle fields on `asset--fungi`:

```php
'fungi_type' => [
  'type' => 'entity_reference',
  'label' => 'Fungi species/variety',
  'description' => "Enter this fungi asset's species/variety.",
  'target_type' => 'taxonomy_term',
  'target_bundle' => 'fungi_type',
  'auto_create' => TRUE,
  'required' => TRUE,
  ...
],
'substrate_type' => [
  'type' => 'entity_reference',
  'label' => 'Substrate type',
  'target_type' => 'taxonomy_term',
  'target_bundle' => 'substrate_type',
  'auto_create' => TRUE,
  // not required
  ...
],
```

**`farm_fungi/config/install/taxonomy.vocabulary.fungi_type.yml`** -- vocabulary description: `"A list of fungi species/varieties."`

Local dev-farmOS config exports agree (`farmos:config/sync/taxonomy.vocabulary.fungi_type.yml` L12 -- same description string).

Pinned facts:

- `fungi_type` is a SINGLE field (cardinality default = 1), entity_reference to taxonomy_term, target_bundle `fungi_type`, `required: TRUE`, `auto_create: TRUE`.
- Upstream intent is unambiguously SPECIES/VARIETY (label, description, vocabulary description all say so; pattern matches `plant_type` / `animal_type` in sibling contribs).
- `required: TRUE` is enforced at the entity-level, which is why mushy currently has to set SOMETHING on every fungi asset write. The current shipped code satisfies that by putting `batch`/`block`/`bag` there -- semantically wrong vs. upstream.
- `auto_create: TRUE` means farmOS will auto-create a missing taxonomy term on write if the API caller submits a name instead of a UUID; mushy doesn't use that path (it resolves UUIDs via `fungi-type-cache.js` first), but the upstream module assumes name-write is fine.
- There is no upstream field for "kind of fungi-asset" (batch vs. block vs. bag). The upstream module assumes the asset bundle itself is the only kind discriminator.

## 3. Candidate reconverge proposals

### (a) Keep alerter code as-is; farmOS-team accepts structural `fungi_type`

**One-line:** farmOS-side rewrites the strawman to match shipped Phase 40 D-03 semantics; `fungi_type` holds structure, `species` holds strain.

- **Code-impact (mushy):** zero. `mushy:src/agents/alerter/src/farmos/assets.js:48-100`, `commits/commit-seeding.js:22,52,56`, `commits/commit-harvest.js:45-46,55-58` already pass `fungiTypeName: 'batch' | 'block' | 'bag'`. `fungi-type-cache.js` and `species-cache.js` both exist and work.
- **Schema-impact (farmOS):** rewrite vocabulary description (`"A list of fungi species/varieties." -> "Structural form: batch | block | bag"`). Diverges from upstream `farm_fungi` intent in a user-visible, label-level way. Door to upstream contribution closes (would need a patch to the contrib module's description and label).
- **Seeder-impact:** none -- current `FUNGI_TYPE_TERMS = ['batch', 'block', 'bag']` and `SPECIES_TERMS = [SHI, ...]` are already correct under this proposal. `species` vocabulary still needs hands-on creation (step 1 of seed request).
- **Tradeoffs:** cheapest to land for v1.7 ship-gate (zero code touch). Most schema-dishonest: farmOS UI will show "Fungi species/variety: batch" on every asset, which is wrong-looking and will confuse any farmOS-native user. radicheta has already rejected this in row 3 of the deliberation ("`fungi_type` carries species ... matching upstream `farm_fungi` intent ... no module patches needed"). LOW likelihood farmOS-team accepts.

### (b) Rename mushy field to `fungi_structure`; `fungi_type` reverts to species; drop separate `species` taxonomy

**One-line:** collapse two fields back to one bundle field per upstream pattern, with a new local custom field for structure.

- **Code-impact (mushy):** moderate. Touch points:
  - `mushy:src/agents/alerter/src/farmos/fungi-type-cache.js` -- repurpose to cache species codes (essentially merge with `species-cache.js`); update probe URL stays the same (`/api/taxonomy_term/fungi_type`).
  - `mushy:src/agents/alerter/src/farmos/species-cache.js` -- delete (functionality folded into `fungi-type-cache.js`).
  - `mushy:src/agents/alerter/src/farmos/assets.js:48-100` -- `createFungiAsset` takes new `fungiStructureName` param; resolves it via a NEW `fungi-structure-cache.js`. `fungiTypeName` becomes the species code (SHI/KOY/...). `speciesUuid` param at L49,77-79 deleted (collapsed into `fungiTypeName`).
  - `mushy:src/agents/alerter/src/farmos/commits/commit-seeding.js:22,46,52-58` -- batch call passes `fungiTypeName: '(unassigned)'` + `fungiStructureName: 'batch'`; block call passes `fungiTypeName: speciesCode` + `fungiStructureName: 'block'`. Drop the `speciesCache.getSpeciesUuid` call at L46.
  - `mushy:src/agents/alerter/src/farmos/commits/commit-harvest.js:45,55-58` -- batch and bag calls pass `fungiStructureName: 'batch' | 'bag'`; need to plumb species through the draft to set `fungiTypeName: speciesCode` (currently harvest doesn't pass species at all -- this surfaces a schema gap mushy was getting away with).
- **Schema-impact (farmOS):** requires a new bundle field `fungi_structure` on `asset--fungi`. Must be added at the Drupal config level (config entity, not JSON:API). Either a new contrib-fork module or a site-local config export. Either way, farmOS-team work. Their deliberation has already proposed this same shape under a different name (`fungi_xing`).
- **Seeder-impact:** swap `FUNGI_TYPE_TERMS` content with `SPECIES_TERMS` content. Add a new `FUNGI_STRUCTURE_TERMS = ['batch', 'block', 'bag']` (or 'fruit' if we adopt their naming) vocab. Drop the standalone `species` vocab block. Net seeder delta: ~5 lines.
- **Tradeoffs:** schema-honest re upstream. Mushy bears most of the code churn (~5 files, all in one directory). farmOS-team bears the bundle-field addition (one-time, drush-able). Most likely shape farmOS-team will counter-propose, modulo naming (see option e).

### (c) Two-field schema -- keep exactly what alerter ships today; treat as "UI/label fix only"

**One-line:** ship as-is, leave `fungi_type` with structural semantics, treat upstream-divergence as a labeling problem solved by patching the bundle field's display label.

- **Code-impact (mushy):** zero. Identical to (a) at the code level.
- **Schema-impact (farmOS):** override the bundle field's `label` and `description` from "Fungi species/variety" to "Fungi structure type" via a Drupal `entity.field_config` override (config export, not module patch). Add a separate `species` vocabulary AND a new bundle field `species` (entity_reference to `taxonomy_term:species`, not required). This is two config entities to add on farmOS side.
- **Seeder-impact:** none on the term lists, but the seed request's step 1 ("create the `species` vocabulary") becomes "create the `species` vocabulary AND attach a field to the fungi bundle." Slightly more operator work; same scripted work.
- **Tradeoffs:** lowest mushy churn, moderate farmOS churn, but it leaves a permanent semantic mismatch with upstream that bites anyone reading the module source or upgrading the contrib module. radicheta's stated reason for rejecting (a) -- "honoring upstream means our work could feed back; no module patches needed" -- applies equally here. UNLIKELY to be accepted but worth listing because it's the "minimum mushy-side change" option if a hard deadline forces our hand.

### (d) Upstream-compliant strict -- bend mushy fully to what `farm_fungi` defines, NO new fields

**One-line:** drop the structural discriminator concept entirely; rely on name prefix (`BATCH-` / `BLOCK-` / `BAG-`) for structure, use `fungi_type` for species per upstream.

- **Code-impact (mushy):** moderate-to-heavy:
  - `mushy:src/agents/alerter/src/farmos/fungi-type-cache.js` -- becomes species cache (merge with `species-cache.js`); delete the latter.
  - `mushy:src/agents/alerter/src/farmos/assets.js:48-100` -- drop the structural-discriminator param entirely; `fungiTypeName` now carries species.
  - `mushy:src/agents/alerter/src/farmos/commits/commit-seeding.js:22,52` -- batch creation must pass `fungiTypeName: '(unassigned)'` sentinel; block creation passes species code. Lose the `speciesCache` round trip.
  - `mushy:src/agents/alerter/src/farmos/commits/commit-harvest.js:45,55-58` -- harvest batch and bags must carry species (forces species-on-draft plumbing in the harvest pipeline).
  - Any downstream consumer that queries "give me all blocks" loses the typed-field query and must regex on name prefix. mushy doesn't currently do this query, but the original strawman B1-B7 was explicitly rejected in the deliberation for this exact reason ("typed-discriminator instinct was correct; name-prefix sniffing genuinely is brittle"). So this option is shipping a known-weakness.
- **Schema-impact (farmOS):** zero. No new fields, no new vocabs beyond `species` (which actually doesn't exist either under this proposal -- `fungi_type` IS species).
- **Seeder-impact:** swap `FUNGI_TYPE_TERMS` content for species codes + `(unassigned)`. Drop the standalone `species` vocab. Drop `bag`/`block`/`batch` terms entirely. ~10 line seeder delta.
- **Tradeoffs:** zero net new schema. Maximally upstream-honest. But the deliberation has already rejected name-prefix sniffing as brittle; this option re-imports the rejected weakness. ALSO unlikely to be accepted by farmOS-team.

### (e) Hybrid (radicheta's tentative lock) -- `fungi_type` = species, new `fungi_xing` field = structure

**One-line:** what `farmos:.planning/notes/2026-05-13-fungi-schema-deliberation.md` row 3 has already locked, plus a custom bundle field `fungi_xing` (Chinese 形, "form") holding `batch`/`block`/`fruit`.

- **Code-impact (mushy):** same shape as (b) with a rename. Touch points:
  - Rename the cache module `fungi-type-cache.js` -> `fungi-xing-cache.js` (keeps probing `/api/taxonomy_term/fungi_xing`). `fungi-type-cache.js` becomes the species cache (merge with current `species-cache.js`).
  - `mushy:src/agents/alerter/src/farmos/assets.js:48-100` -- add `fungiXingName` param; species comes through `fungiTypeName` (already there, just rebound). At L71-72, relationship key becomes `fungi_xing` pointing at the xing-term UUID; species moves to the same `fungi_type` slot.
  - `mushy:src/agents/alerter/src/farmos/commits/commit-seeding.js:22,46,52-58` -- batch: `fungiTypeName='(unassigned)'`, `fungiXingName='batch'`. Block: `fungiTypeName=speciesCode`, `fungiXingName='block'`.
  - `mushy:src/agents/alerter/src/farmos/commits/commit-harvest.js:45,55-58` -- batch: `fungiXingName='batch'`. Bag: `fungiXingName='fruit'` (note rename from `bag`). Species must be plumbed (gap shared with option b).
  - The string `'bag'` in two places (`commit-harvest.js:58`, `commit-harvest.js:54` "${batchName}-bag-...") needs renaming if we adopt `fruit`. Bag asset NAMES still say "bag" by farmer convention; only the typed field changes. Probably keep `bag` in names, use `fruit` in the typed field. Small UX wart.
- **Schema-impact (farmOS):** new bundle field `fungi_xing` on `asset--fungi` (config entity, drush or UI). New vocabulary `fungi_xing` with 3 terms (`batch`, `block`, `fruit`). Both are farmOS-side work. `fungi_type` reverts to its upstream semantic (species), so no field re-label needed -- this is actually less farmOS work than option (b) on the labeling axis. ALSO addresses radicheta's row-2 concern that `bag` is too vague ("bags appear all through the pipeline; `FRUIT-` names what's inside").
- **Seeder-impact:** `FUNGI_TYPE_TERMS` becomes species codes + `(unassigned)`. New `FUNGI_XING_TERMS = ['batch', 'block', 'fruit']`. Drop standalone `species` vocab (folded into `fungi_type`). Net seeder delta: ~8 lines, all mechanical.
- **Tradeoffs:** schema-honest (matches upstream `fungi_type` semantics; local custom field is an addition, not a contradiction). Most likely to land smoothly because the farmOS deliberation has already converged on this shape internally. Costs: mushy touches 4 files (assets.js, commits/commit-seeding.js, commits/commit-harvest.js, plus cache module rename); farmOS adds a bundle field and a vocabulary. The naming detail `bag` -> `fruit` is the one open friction point.

## 4. Recommendation

Option (e) -- the hybrid -- is cheapest to LAND (farmOS-team have already converged on it internally; no negotiation needed beyond confirming naming) AND most schema-honest (preserves upstream `fungi_type` semantics, makes the structural discriminator a typed field rather than a name-prefix sniff). The single tradeoff is ~4 files of mushy code churn vs. option (a)'s zero, but that churn is one-day mechanical work and avoids a permanent semantic mismatch with the upstream contrib module.

## 5. Open questions for the farmOS-team

Paste these back when the reply lands; answers collapse the option space immediately.

1. **Naming -- `fungi_xing` or `fungi_structure`?** `xing` is short and collision-free but requires an onboarding moment for every new reader; `structure` is self-documenting at the cost of being longer. Which is the local install committing to?

2. **Bag vs. fruit -- typed-field value name.** The deliberation row 2 dropped `bag` in favor of `fruit` (also dropped `harvest_batch` as separate). Mushy's `commit-harvest.js` currently creates assets with names like `${batchName}-bag-1` (`mushy:src/agents/alerter/src/farmos/commits/commit-harvest.js:54`) and `fungiTypeName: 'bag'` (L58). Does mushy keep `bag` in NAMES (farmer convention) and only use `fruit` in the TYPED FIELD, or rename names too?

3. **Harvest-batch as asset, yes/no?** The strawman defined a `HARV-` parent asset; the deliberation row 2 dropped it (harvest log carries aggregation). `mushy:commit-harvest.js:45-49` currently creates a harvest batch asset. If row 2 holds, mushy needs to delete that creation step and put the source-blocks-to-bag relationship purely on the harvest log. Confirm before we touch the code.

4. **Does `species` end up as a standalone vocabulary, or fully collapsed into `fungi_type`?** Deliberation row 3 says `fungi_type` carries species directly (no separate `species` vocab). The seed-request step 1 asked farmOS-team to CREATE the `species` vocab. If row 3 holds, that step is cancelled and we delete `mushy:src/agents/alerter/src/farmos/species-cache.js`. Confirm cancellation explicitly so we don't end up with an orphan vocab on dev-farmOS.

5. **Pre-inoc sentinel mechanic for `fungi_type` (= species).** Row 4 of the deliberation is still open: `(unassigned)` taxonomy term vs. making the field nullable on pre-inoc batches via a config override. If sentinel: mushy passes `fungiTypeName: '(unassigned)'` on batch creation. If nullable: mushy passes nothing and the API accepts the omission. Which mechanic does the farmOS side commit to? (Sentinel is the path-of-least-resistance because `farm_fungi` upstream has `required: TRUE` baked into the field definition; making it nullable means a config override that fights the module.)
