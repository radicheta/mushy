---
date: 2026-05-16
author: claude (read-only research; no code changed)
companion: .planning/notes/2026-05-15-lion-mane-bridged-uat.md (Finding 4)
purpose: Pre-discussion audit -- enumerate Phase 38 (extractor) vs Phase 40 (commit handler) schema mismatches across all 5 log_types, then propose fix shape.
scope: read-only static analysis of src/agents/alerter/{src/extraction,src/farmos/commits}. No runtime probes, no paid API calls.
verdict: 4 of 5 log_types are wire-incompatible end-to-end. Only `seeding` happens to overlap enough to commit. Recommend a router-side normalizer (Option A) plus a chain-integration test suite (Option C); do NOT change extractor prompts (Option B is wrong direction).
---

# Phase 38 <-> Phase 40 schema audit

## 0. Executive summary

Phase 38 (extractor) and Phase 40 (commit handlers) were planned and shipped
independently, each with its own internal "draft" shape:

- **Extractor-shape** (Phase 38, Zod-validated, lives in
  `src/agents/alerter/src/extraction/schemas/`) is *farmer-input-centric*:
  one referenced thing per log = `asset_ref` (string), one timestamp =
  `event_timestamp` (ISO 8601), one species = `species` (common name),
  activity name = `name` (enum).

- **Commit-shape** (Phase 40, lives in
  `src/agents/alerter/src/farmos/commits/`) is *farmOS-write-centric*:
  arrays of QR codes = `qr_codes: string[]`, unix-seconds = `timestamp:
  number`, strain code = `species_code` / `strain` / `fungi_type`,
  activity name = `activity_subtype`.

The pipeline writes the **extractor-shape** into `signal_draft.draft_json`
(`src/agents/alerter/src/extraction/pipeline.js:282-309`) and the commit
watchdog reads `draft.draft_json` and hands it to the commit handler
(`commit-router.js:37`). There is **no normalizer** between them.

Three independent things hid the bug until 2026-05-15:

1. **Curated commit fixtures** in `test/farmos/fixtures/curated/` and the
   ship-gate fixture in `test/farmos/fixtures/prod-confirmed-draft.json`
   are all **hand-written in commit-shape** -- they were never round-tripped
   through Phase 38. So every commit-*.test.js and the integration suite
   pass against a draft shape the live extractor does not actually produce.
2. **Phase 39 EDIT** re-extracts with `farmerCorrection` and writes back
   into the same `draft_json` field in extractor-shape
   (`src/confirm/edit-handler.js:46-89`). EDIT validates extractor-shape
   ergo cannot detect a downstream shape mismatch.
3. **Prod cutover smoke 2026-05-14** exercised **seeding** + **harvest**
   only (`.planning/phases/40-farmos-write-path/40-PROD-SMOKE-20260514.md`
   Tests 1 + 2). Both used synthetic drafts in commit-shape. Activity,
   observation, and input never crossed the live wire until Santi's
   2026-05-15 lion's-mane message.

Net: 4 of 5 log_types have at least one terminal mismatch. The fifth
(seeding) ships only because the extractor's `block_name` + `species` are
acceptable substitutes for the commit handler's `block_name` + `strain`
fallback chain, and because `qr_codes` is optional on Path A (asset
creation) -- which is the only seeding path the extractor naturally
produces (since extractor-shape has no `qr_codes` field at all).

The recommended fix is **Option A (router-side normalizer) + Option C
(extractor->router chain tests)**, sized at ~1 day of work combined.
Option B (reshape extractor prompts) is rejected because the extractor's
asset_ref/event_timestamp/name semantics carry meaning the farmer-facing
preview depends on -- those names appear directly in askback text and in
EDIT-loop validation.

---

## 1. Per-log_type comparison matrix

Reading order per row: **commit-side reads** (every `dj.X` reference, with
expected type) -> **extractor-side emits** (Zod schema fields, with type)
-> **DIFF** -> **test/fixture coverage**.

### 1.1 seeding

**Commit-side** (`src/agents/alerter/src/farmos/commits/commit-seeding.js`):

| line | code | reads | expected type |
|------|------|-------|---------------|
| 22 | `const dj = draft.draft_json \|\| {};` | -- | -- |
| 23 | `Array.isArray(dj.qr_codes) ? dj.qr_codes : []` | `dj.qr_codes` | `string[]` |
| 24 | `typeof dj.timestamp === 'number' ? dj.timestamp : (Date.now() / 1000)` | `dj.timestamp` | `number` (unix sec) |
| 44 | `dj.species_code \|\| dj.species \|\| dj.strain \|\| dj.fungi_type` | strain (any of 4 names) | `string` |
| 47 | `const blockName = dj.block_name;` | `dj.block_name` | `string` (B5: `YYMMDD_SPECIES_SEQ`) |
| 63 | `const batchName = dj.batch_name;` | `dj.batch_name` | `string` (optional) |
| 65 | `if (dj.notes) noteParts.push(dj.notes);` | `dj.notes` | `string` (optional) |

**Extractor-side** (`src/agents/alerter/src/extraction/schemas/seeding.js:18-29`):

```
SeedingLog = {
  type: literal('seeding'),
  species: string,                            // common name OR 2-4-letter code
  block_name: string (B5 regex),
  qty: int positive,
  event_timestamp: ISO 8601 datetime,
  parent_batch_name: string (optional),
  notes: string (optional),
  confidence: Record<string, number>,
}
```

**DIFF**:

| field | commit reads | extractor emits | severity |
|-------|--------------|-----------------|----------|
| qr_codes (array) | yes (optional; Path A creates new) | NEVER emitted | MINOR -- Path A still works without QR |
| timestamp (unix sec) | yes (falls back to `Date.now()/1000`) | NOT emitted; emits `event_timestamp` (ISO) instead | MEDIUM -- commit silently uses *current* wallclock, dropping the actual event date the farmer reported |
| strain | reads `species_code` / `species` / `strain` / `fungi_type` (4 aliases) | emits `species` (common name like "shiitake") | MINOR -- the `species` alias catches it; but the value is a common name not the 2-4 letter code; commit relies on the farmOS-side fungi_type cache to resolve "shiitake" -> "SHI" (works only because the cache holds both) |
| block_name | reads `dj.block_name` | emits `block_name` | OK (matches) |
| batch_name | reads `dj.batch_name` | NOT emitted; extractor has `parent_batch_name` (different semantics: parent block lineage, not the sterilization batch) | MEDIUM -- the sterilization batch ID the farmer mentions is dropped; commit's `sterilization_batch:` note line is always blank in live use |
| qty | NOT read by commit handler | emits `qty: int` | LOW -- silently ignored |
| parent_batch_name | NOT read | emits | LOW -- C4 lineage info dropped |
| notes | reads | emits | OK |

**Why seeding survived the 2026-05-14 prod smoke**: the smoke draft was
synthetic and hand-shaped in commit-shape (block_name + species_code +
qr_codes + timestamp + batch_name). It never traversed Phase 38.

**Tests/fixtures**:
- `test/farmos/fixtures/curated/seeding-happy.json`: commit-shape (qr_codes,
  timestamp, species_code, batch_name). Bypasses Phase 38.
- `test/farmos/fixtures/prod-confirmed-draft.json` (the "ship gate"): also
  commit-shape (qr_codes, timestamp, species_code, batch_name). Despite the
  `_provenance.source_session` pointing at a real audio session, the
  `draft_json` was **hand-shaped, not produced by Phase 38**.
- Phase 38 plan08 eval report
  (`.planning/phases/38-extraction-pipeline/38-EVAL-REPORT-plan09-smoke-results.json`)
  records actual extractor seeding outputs with `species`/`event_timestamp`/no
  `qr_codes` -- the real shape.

### 1.2 activity

**Commit-side** (`src/agents/alerter/src/farmos/commits/commit-activity.js`):

| line | code | reads | expected type |
|------|------|-------|---------------|
| 15 | `const dj = draft.draft_json \|\| {};` | -- | -- |
| 17 | `Array.isArray(dj.qr_codes) ? dj.qr_codes : []` | `dj.qr_codes` | `string[]` |
| 18 | `typeof dj.timestamp === 'number' ? dj.timestamp : (Date.now() / 1000)` | `dj.timestamp` | `number` (unix sec) |
| 19 | `const subtype = dj.activity_subtype \|\| 'activity';` | `dj.activity_subtype` | `string` (enum: water/sterilize/relocate/...) |
| 31 | `notes: dj.notes \|\| ''` | `dj.notes` | `string` |

**Extractor-side** (`src/agents/alerter/src/extraction/schemas/activity.js:12-21`):

```
ActivityLog = {
  type: literal('activity'),
  name: enum('sterilize'|'sterilize_failed'|'water'|'relocate'|'cold_shock'|'archive_spent'|'contam'),
  asset_ref: string (1 ref, no array),
  event_timestamp: ISO 8601 datetime,
  notes: string (optional),
  confidence: Record<string, number>,
}
```

**DIFF** (THIS IS THE 2026-05-15 LIVE BUG):

| field | commit reads | extractor emits | severity |
|-------|--------------|-----------------|----------|
| qr_codes (array) | required (else `no_target_asset_for_activity` terminal) | NEVER emitted; emits `asset_ref` (single string, with `<UNKNOWN>` sentinel) | **TERMINAL** -- live failure 2026-05-15 |
| timestamp (unix sec) | yes (falls back to `Date.now()`) | NOT emitted; emits `event_timestamp` (ISO) | **MEDIUM** -- silently wallclocks the event |
| activity_subtype | yes (falls back to literal `'activity'`) | NOT emitted; emits `name` (same enum values) | **MEDIUM** -- log name becomes `activity 2026-05-15` instead of `relocate 2026-05-13`; semantically wrong but commit succeeds |

**Why Phase 39 EDIT couldn't catch this**: EDIT calls `extractor.extract(...)`
with `farmerCorrection` (`src/confirm/edit-handler.js:46-59`), receives a
new draft in extractor-shape, validates against
`stateMachineExtraction.REQUIRED_FIELDS[draft.type]`
(`edit-handler.js:82-83`), and writes back into `draft_json` -- the entire
EDIT loop is sealed inside extractor-shape. The downstream commit-shape is
invisible to it.

**Tests/fixtures**:
- `test/farmos/fixtures/curated/activity-water.json`: commit-shape
  (`activity_subtype: "water"`, `qr_codes: ["QR-FX-SEED-001"]`,
  `timestamp: 1747180800`). PASS in unit tests, but does NOT represent any
  draft Phase 38 actually produces.
- `test/farmos/commit-activity.test.js:8-46`: every assertion passes
  commit-shape directly into `commitActivity(...)`. Zero extractor coupling.
- No fixture or test anywhere exercises an `asset_ref`/`event_timestamp`/
  `name`-shape input into the activity commit handler.

### 1.3 input

**Commit-side** (`src/agents/alerter/src/farmos/commits/commit-input.js`):

| line | code | reads | expected type |
|------|------|-------|---------------|
| 10 | `const dj = draft.draft_json \|\| {};` | -- | -- |
| 12 | `Array.isArray(dj.qr_codes) ? dj.qr_codes : []` | `dj.qr_codes` | `string[]` |
| 13 | `typeof dj.timestamp === 'number' ? dj.timestamp : (Date.now() / 1000)` | `dj.timestamp` | `number` |
| 14 | `Array.isArray(dj.input_ingredients) ? dj.input_ingredients : []` | `dj.input_ingredients` | `string[]` |
| 25 | `dj.notes` | `dj.notes` | `string` |

**Extractor-side** (`src/agents/alerter/src/extraction/schemas/input.js:8-17`):

```
InputLog = {
  type: literal('input'),
  recipe_lot: string,
  asset_ref: string,
  event_timestamp: ISO 8601 datetime,
  notes: string (optional),
  confidence: Record<string, number>,
}
```

**DIFF**:

| field | commit reads | extractor emits | severity |
|-------|--------------|-----------------|----------|
| qr_codes | required (else `no_target_asset_for_activity` -- yes, same string as activity; see commit-input.js:22) | NEVER emitted; emits `asset_ref` | **TERMINAL** |
| timestamp | yes | emits `event_timestamp` ISO | MEDIUM (wallclocked) |
| input_ingredients | reads (serialized into notes) | NEVER emitted | MEDIUM -- the whole point of input log (ingredient list) is dropped |
| recipe_lot | NOT read | emits | LOW -- a recipe lot ID the farmer gave us is silently discarded |
| notes | reads | emits | OK |

**Tests/fixtures**:
- `test/farmos/fixtures/curated/input-recipe.json`: commit-shape
  (qr_codes, input_ingredients, timestamp). No extractor coverage.

### 1.4 observation

**Commit-side** (`src/agents/alerter/src/farmos/commits/commit-observation.js`):

| line | code | reads | expected type |
|------|------|-------|---------------|
| 12 | `const dj = draft.draft_json \|\| {};` | -- | -- |
| 14 | `Array.isArray(dj.qr_codes) ? dj.qr_codes : []` | `dj.qr_codes` | `string[]` |
| 15 | `typeof dj.timestamp === 'number' ? dj.timestamp : (Date.now() / 1000)` | `dj.timestamp` | `number` |
| 37 | `notes: dj.notes \|\| ''` | `dj.notes` | `string` |

Also reads `draft.source_capture_ids` (top-level, not in draft_json) at
line 26 -- that path is OK.

**Extractor-side** (`src/agents/alerter/src/extraction/schemas/observation.js:12-21`):

```
ObservationLogBase = {
  type: literal('observation'),
  asset_ref: string,
  state: string (optional),
  notes: string (optional),
  event_timestamp: ISO 8601 datetime,
  confidence: Record<string, number>,
}
```

**DIFF**:

| field | commit reads | extractor emits | severity |
|-------|--------------|-----------------|----------|
| qr_codes | required (else `observation_requires_target` terminal) | NEVER emitted; emits `asset_ref` | **TERMINAL** |
| timestamp | yes | emits `event_timestamp` ISO | MEDIUM |
| state | NOT read | emits (optional) | LOW -- pinning/fruiting/contam state info silently dropped |
| notes | reads | emits | OK |

**Tests/fixtures**:
- `test/farmos/fixtures/curated/observation-photo.json`: commit-shape only.

### 1.5 harvest

**Commit-side** (`src/agents/alerter/src/farmos/commits/commit-harvest.js`):

| line | code | reads | expected type |
|------|------|-------|---------------|
| 27-36 | `resolveStrain(dj)` reads `dj.strain` / `dj.fungi_type` / `dj.species_code` / `dj.species` / `dj.harvest_batch_name` (regex extract) | strain | `string` |
| 40 | `const dj = draft.draft_json \|\| {};` | -- | -- |
| 42 | `typeof dj.timestamp === 'number' ? dj.timestamp : (Date.now() / 1000)` | `dj.timestamp` | `number` |
| 44 | `Array.isArray(dj.source_qr_codes) ? dj.source_qr_codes : []` | `dj.source_qr_codes` | `string[]` |
| 45 | `Array.isArray(dj.bags) ? dj.bags : []` | `dj.bags` | `Array<{qr_code, name, weight_grams}>` |
| 74 | `const batchName = dj.harvest_batch_name;` | `dj.harvest_batch_name` | `string` |
| 96 | `dj.notes` | `dj.notes` | `string` |

**Extractor-side** (`src/agents/alerter/src/extraction/schemas/harvest.js:9-19`):

```
HarvestLog = {
  type: literal('harvest'),
  harvest_batch_id: string,
  source_block_refs: string[] (min 1),
  qty_g: number (positive),
  event_timestamp: ISO 8601 datetime,
  notes: string (optional),
  confidence: Record<string, number>,
}
```

**DIFF**:

| field | commit reads | extractor emits | severity |
|-------|--------------|-----------------|----------|
| source_qr_codes | required (`missing_source_block` terminal) | NOT emitted; emits `source_block_refs` (refs by block_name, not QR code) | **TERMINAL** -- the QR resolution loop in commit-harvest.js:49-58 takes the strings and calls `qrMod.resolveQr`. If the extractor emitted `source_block_refs: ["260512_DT_11"]` (block name), the QR lookup will fail because QRs are not block names. |
| bags | required (no-bag harvest still posts log but no bag assets) | NOT emitted; extractor flattens to `qty_g` (single number) | **TERMINAL** -- the whole multi-bag-per-harvest model collapses to one number, and the commit-handler creates zero bag assets |
| harvest_batch_name | reads (for strain regex + notes) | emits `harvest_batch_id` (different field name) | **TERMINAL** -- strain resolution falls back to `harvest_batch_id` (still extractable IF the regex matches), but the commit handler will not parse it because the field name is different |
| timestamp (unix sec) | yes | emits `event_timestamp` ISO | MEDIUM |
| strain | reads via 4-name chain incl. regex from `harvest_batch_name` | NOT emitted as a top-level field; only available via regex on `harvest_batch_id` (wrong name) | **TERMINAL** -- chain fails, `missing_strain` |
| qty_g | NOT read | emits | LOW -- total harvest weight discarded |
| notes | reads | emits | OK |

Harvest is the most broken: literally every shape-bearing field has a
different name. The 2026-05-14 prod smoke harvest passed because the
draft was hand-shaped (`source_qr_codes`, `bags`, `harvest_batch_name`,
`timestamp` -- all commit-shape).

**Tests/fixtures**:
- `test/farmos/fixtures/curated/harvest-multi-bag.json`: commit-shape only.

---

## 2. Findings

### 2.1 Why Phase 39 EDIT never catches the mismatch

`src/agents/alerter/src/confirm/edit-handler.js:46-89`: the EDIT handler
re-runs `extractor.extract(...)` with `farmerCorrection`, validates the
result against `stateMachineExtraction.REQUIRED_FIELDS[draft.type]`
(line 82-83) -- a map keyed on extractor-shape -- and writes the result
back into `draft_json`. The EDIT loop is closed inside extractor-shape.
It cannot see commit-shape, because commit-shape exists only inside the
commit handlers.

### 2.2 Why the 2026-05-14 prod cutover smoke didn't catch it

`.planning/phases/40-farmos-write-path/40-PROD-SMOKE-20260514.md` exercised
only **seeding** (Test 1) and **harvest** (Test 2). Both used synthetic
drafts hand-shaped in commit-shape, with the source noted as "synthetic
confirmed-... draft" (e.g. `smoke20260514174524_prod_seed_v2_56b7fae3`).
Neither draft traversed Phase 38. Activity, observation, and input were
never live-tested at all -- the smoke note's "what this proves" section
lists only the seeding + harvest paths.

The ship-gate fixture (`test/farmos/fixtures/prod-confirmed-draft.json`)
that the integration test calls "SHIP GATE: real-prod fixture commits
end-to-end" is in fact commit-shape; the `_provenance` block names a real
source session but the `draft_json` was hand-written, not extracted.
That fixture would not be produced by today's Phase 38 even if the same
audio were re-played through it. (Compare the eval-report extractor
outputs in
`.planning/phases/38-extraction-pipeline/38-EVAL-REPORT-plan09-smoke-results.json`
lines 2936/3410 -- the real extractor emits `asset_ref`.)

### 2.3 Which integration tests would have caught this

`test/farmos/integration.test.js:130-213` runs the 8 commit scenarios
(seeding/activity/input/observation/harvest + idempotency + unsupported
log_type + ship gate). All 8 inputs are pre-staged in commit-shape on
disk. The suite never invokes `extractor.extract(...)` or the Phase 38
pipeline -- it skips straight to `commitWatchdog.tickOnce(...)` against
a draft row already inserted as commit-shape.

A test that would have caught it: take a real captured audio (or text)
through `extractionPipeline.runPipeline(...)` end-to-end, persist the
real `draft_json` in extractor-shape, mark confirmed, then run
`commitWatchdog.tickOnce(...)` against the SAME row and assert
`commit_success`. That test does not exist anywhere in the repo. (Grep
target verified: `grep -rn "extractor.extract" test/farmos/` returns
zero hits.)

### 2.4 The curated-fixture trap

This is the same anti-pattern flagged in
`feedback_real_data_before_ship_gate_pass`: curated fixtures are
necessary-but-insufficient. Here the curated fixtures are not even
*shaped* like real production -- they're shaped like what the commit
handler authors imagined the upstream would emit. The "ship gate" was
declared cleared 2026-05-14 with a fixture that does not represent the
live Phase 38 output.

---

## 3. Recommendations

### Option A: router-side normalizer (RECOMMENDED, core)

Insert a pure function between `commit-watchdog.js` and
`commit-router.js` that translates extractor-shape -> commit-shape per
log_type. Idiomatic location: a new file
`src/agents/alerter/src/farmos/commits/normalize.js`, called from
`commit-router.commit(...)` before the DISPATCH lookup.

Signature sketch:

```js
// src/agents/alerter/src/farmos/commits/normalize.js
function normalize(draft) {
  // Returns a NEW draft with draft_json reshaped to commit-shape.
  // Idempotent: if draft_json already in commit-shape (has qr_codes /
  // timestamp / activity_subtype / etc.), pass through unchanged.
  const dj = draft.draft_json || {};
  const out = { ...dj };

  // Common: event_timestamp (ISO) -> timestamp (unix sec).
  if (typeof out.timestamp !== 'number' && typeof out.event_timestamp === 'string') {
    const ms = Date.parse(out.event_timestamp);
    if (Number.isFinite(ms)) out.timestamp = Math.floor(ms / 1000);
  }

  // Common: asset_ref -> qr_codes[]. Filter <UNKNOWN> sentinel.
  if (!Array.isArray(out.qr_codes) && typeof out.asset_ref === 'string') {
    out.qr_codes = out.asset_ref === '<UNKNOWN>' ? [] : [out.asset_ref];
  }

  switch (draft.log_type) {
    case 'activity':
      if (!out.activity_subtype && typeof out.name === 'string') out.activity_subtype = out.name;
      break;
    case 'harvest':
      // source_block_refs -> source_qr_codes (note: this is NOT actually
      // a QR; if extractor gave us a block_name we still need to resolve
      // it. Open question for discussion: do we (a) treat block_name as
      // resolvable by qr.resolveQr, (b) add a parallel resolve-by-name
      // path in commit-harvest, or (c) push back to extractor to emit
      // the QR string when one is available)?
      if (!Array.isArray(out.source_qr_codes) && Array.isArray(out.source_block_refs)) {
        out.source_qr_codes = out.source_block_refs;
      }
      if (!out.harvest_batch_name && typeof out.harvest_batch_id === 'string') {
        out.harvest_batch_name = out.harvest_batch_id;
      }
      // qty_g + bags: extractor has only qty_g. Synthesize a single
      // unnamed bag IF qty_g present, else leave bags absent.
      if (!Array.isArray(out.bags) && typeof out.qty_g === 'number') {
        out.bags = [{ weight_grams: out.qty_g }];
      }
      break;
    case 'seeding':
      if (!out.species_code && typeof out.species === 'string') out.species_code = out.species;
      // parent_batch_name -> batch_name? UNCLEAR semantics. Discussion
      // item. They are NOT the same thing: parent_batch_name is the
      // lineage parent (C4); batch_name is the sterilization batch
      // (pre-inoc, not yet a farmOS asset). Recommend leaving these
      // distinct and bridging them only after farmOS-side pasteurization
      // log lands.
      break;
    case 'input':
      // recipe_lot has no commit-side equivalent today. Either prepend
      // it to notes, or extend commit-input.js to read it. Discussion item.
      if (typeof out.recipe_lot === 'string') {
        out.notes = (out.notes ? out.notes + '\n' : '') + 'recipe_lot: ' + out.recipe_lot;
      }
      // input_ingredients: extractor doesn't emit; nothing to normalize.
      break;
    case 'observation':
      // state -> append to notes if state present and notes absent or short.
      if (typeof out.state === 'string' && out.state !== '') {
        out.notes = out.notes ? (out.notes + '\nstate: ' + out.state) : ('state: ' + out.state);
      }
      break;
  }
  return { ...draft, draft_json: out };
}

module.exports = { normalize };
```

Wiring change (1 line in `commit-router.js:36`):

```js
const r = await fn(client, require('./normalize').normalize(draft), ctx);
```

**Sizing**: ~150-200 LOC normalize.js + 1-line router edit + ~10 unit
tests in a new `test/farmos/normalize.test.js`. Half a day, including
code-review notes.

**Blast radius**: lowest. Both schemas keep their meaning at their
boundary. Audit trail (`signal_draft.draft_json`) keeps the extractor
shape farmers/operators have been seeing in askback previews. The
normalized shape lives only inside the commit dispatch.

**Open questions for the discussion (the normalizer cannot answer alone)**:

1. **harvest source_block_refs**: the extractor emits block_name strings,
   not QR strings. Does commit-harvest's `qr.resolveQr` resolve by both?
   Need to read `farmos/qr.js`. Likely needs an extension of qr.js or a
   parallel resolve-by-name path.
2. **seeding batch_name vs parent_batch_name**: keep distinct or fold?
   The 2026-05-14 schema notes
   (`.planning/notes/2026-05-14-reply-from-farmos-fungi-schema.md`)
   imply they're different. Defer until pasteurization-log lands.
3. **input recipe_lot + ingredients**: extractor emits recipe_lot but no
   ingredient list; commit reads ingredient list but not recipe_lot.
   These two modules were planned by different humans and never
   reconciled. Discussion needed on which side to extend.
4. **harvest qty_g vs bags**: the extractor's "one harvest = one number"
   model loses bag-level QR/weight. For real harvest commits we need the
   extractor schema extended OR the farmer asked to submit bag-shaped
   reports (which is a UX change). Discussion item; not a same-week-fix.

### Option B: reshape Phase 38 extractor (NOT RECOMMENDED)

Reshape the Zod schemas in
`src/agents/alerter/src/extraction/schemas/{activity,observation,input,harvest,seeding}.js`
to emit commit-shape directly, and update
`src/agents/alerter/src/extraction/prompts/system.js` to teach the LLM
the new field names.

**Why not**:

- The farmer-facing askback preview
  (`src/agents/alerter/src/extraction/preview-builder.js`) uses the
  extractor-shape field names. Renaming `asset_ref` to `qr_codes` would
  collide with Finding 1d from the lion's mane note (the very
  pushback Santi gave: "speak in farmer to me"). The right move there
  is to make preview-builder *more* farmer-friendly, not to push the
  commit-side jargon up into the farmer's eyes.
- `event_timestamp` (ISO) is human-debuggable in DB rows; `timestamp`
  (unix sec) is not. We lose audit ergonomics.
- The prompt edits would touch ~80 example lines in
  `prompts/system.js` (38 grep hits across the affected field names) and
  re-invalidate the entire Phase 38 evaluation suite. The 2026-05-12
  eval corpus (`.planning/phases/38-extraction-pipeline/38-EVAL-REPORT-*.json`)
  would all need re-runs at LLM cost.
- It conflates two distinct contracts: farmer-input shape (what we ask
  the LLM to extract) and farmOS-write shape (what farmOS expects). The
  current separation is sound; the missing piece is the explicit bridge.

### Option C: chain integration tests (RECOMMENDED, paired with A)

Add a new test file
`src/agents/alerter/test/integration/extractor-to-commit.test.js` that
runs the full pipeline for each of the 5 log_types. Skeleton:

- **Test 1 -- seeding chain**: feed a known transcript ("Inoc-ed block
  260516_DT_1 from batch BATCH-2026-05-16-001 with 1kg shiitake grain")
  through `extractor.extract(...)`. Assert the result is in
  extractor-shape. Run it through `normalize(...)`. Assert the
  normalized shape is in commit-shape. Run it through
  `commitSeeding(...)` against a mock farmOS client. Assert
  `commit_success` and that the asset relationship references include
  the right block + the right strain term.

- **Test 2 -- activity chain (THE 2026-05-15 REGRESSION GUARD)**: feed
  the lion's-mane transcript ("Two days ago I put a lion's mane block
  into the fruiting chamber") + a follow-up edit ("260415_LIMA_1")
  through `extractor.extract(...)`. Assert extractor emits
  `name: 'relocate'`, `asset_ref: '260415_LIMA_1'`, ISO
  `event_timestamp`. Normalize. Assert
  `activity_subtype: 'relocate'`, `qr_codes: ['260415_LIMA_1']`,
  numeric `timestamp`. Commit. Assert `commit_success`. **This test
  failing today is the bug from 2026-05-15.**

- **Test 3 -- observation chain**: feed a photo + caption ("pin
  emergence on 260513_SHI_2"). Assert state field captured in notes
  post-normalization. Commit. Assert log created with photo file_id.

- **Test 4 -- input chain**: feed a recipe report ("Mixed substrate for
  260514_KOY_3 with oat 1kg, gypsum 50g, recipe RB-2026-05"). Assert
  the `recipe_lot` is captured in notes; ingredients gap is documented.

- **Test 5 -- harvest chain**: feed a multi-bag harvest report ("Picked
  3 bags from 260512_DT_11: 250g, 230g, 260g, batch HBATCH-2026-05-15-DT-001").
  Assert the chain produces ONE bag asset (single qty_g normalization)
  with the right strain regex-resolved. Document the multi-bag gap
  inline.

Each test uses the existing `mock-client.js`
(`test/farmos/mock-client.js`) for the farmOS side and a mocked
Anthropic responder (using extractor test helpers in
`test/extraction/helpers/`) for the LLM side. No paid API calls; no
prod-farmOS dependency. Suite runs under `npm test` by default (not
gated by `FARMOS_INTEGRATION=1`).

**Sizing**: ~5 tests x ~60 LOC each = ~300 LOC + small helpers. Half a
day.

### Recommendation: A + C, bundled

- **A** closes today's known mismatches with the smallest blast radius
  and preserves both shape boundaries at their natural homes.
- **C** ensures the *next* drift (which is inevitable as either side
  evolves) is caught before it ships. Specifically, Test 2 is the
  regression guard for the exact 2026-05-15 bug.
- **B** is the wrong direction for the four reasons listed above; punt
  unless the discussion surfaces a reason to reverse course.

Optional follow-on (NOT for this fix, but log it):

- **D**: a small `extractorShape -> commitShape` JSON Schema declared
  as a separate artifact under `src/agents/alerter/src/farmos/commits/`
  so that any third party reading the code can see the contract without
  reading both schemas + the normalizer code. Useful for the
  Phase 41+42 ingestion harness work.

---

## 4. Appendix: code references

All citations are file:line against the working tree at the start of this
audit (2026-05-16). Quoted excerpts copied verbatim from the source.

### A1. commit-router dispatch

`src/agents/alerter/src/farmos/commits/commit-router.js:14-20`:
```js
const DISPATCH = {
  seeding: commitSeeding,
  activity: commitActivity,
  input: commitInput,
  observation: commitObservation,
  harvest: commitHarvest,
};
```

`commit-router.js:36-37`:
```js
const fn = DISPATCH[logType];
try {
  const r = await fn(client, draft, ctx);
```

No transformation between watchdog and handler.

### A2. Extractor schema -- activity (the live regression)

`src/agents/alerter/src/extraction/schemas/activity.js:12-21`:
```js
const ActivityLog = z
  .object({
    type: z.literal('activity'),
    name: z.enum(ACTIVITY_NAMES),
    asset_ref: z.string().min(1),
    event_timestamp: z.string().datetime(),
    notes: z.string().optional(),
    confidence: z.record(z.string(), z.number().min(0).max(1)),
  })
  .strict();
```

### A3. commit-activity reads

`src/agents/alerter/src/farmos/commits/commit-activity.js:14-29`:
```js
async function commitActivity(client, draft, ctx) {
  const dj = draft.draft_json || {};
  const draftId = draft.id;
  const qrCodes = Array.isArray(dj.qr_codes) ? dj.qr_codes : [];
  const timestamp = typeof dj.timestamp === 'number' ? dj.timestamp : (Date.now() / 1000);
  const subtype = dj.activity_subtype || 'activity';

  const assetIds = [];
  for (const qr of qrCodes) {
    const r = await qrMod.resolveQr(client, qr);
    if (r.found && r.assetId) assetIds.push(r.assetId);
  }
  if (assetIds.length === 0) {
    return { ok: false, reason: 'no_target_asset_for_activity' };
  }
```

The `dj.qr_codes` (line 17) + `dj.timestamp` (line 18) + `dj.activity_subtype`
(line 19) reads vs the extractor's `asset_ref` + `event_timestamp` + `name`
emits are the 2026-05-15 mismatch.

### A4. Pipeline writes extractor-shape into draft_json

`src/agents/alerter/src/extraction/pipeline.js:282-309`:
```js
{
  draft_json: draft,
  per_field_confidence: extractResult.per_field_confidence || null,
  log_type: logType || null,
},
...
// start_new -> insert.
const ins = await extractionDb.insertDraft(pool, {
  id: draftId,
  sender_e164: sender,
  farmos_person: captureCtx.farmosPerson || null,
  source_capture_ids: sourceCaptureIds,
  status: DRAFT_STATUS.PENDING,
  log_type: logType || null,
  draft_json: draft,
```

The `draft` here is the raw Zod-validated extractor output, written
unchanged.

### A5. EDIT loop is sealed inside extractor-shape

`src/agents/alerter/src/confirm/edit-handler.js:46-89`:
```js
result = await extractor.extract({
  captures: [
    {
      captureId: 'edit-' + draftRow.id,
      ...
      farmerCorrection: editStr,
    },
  ],
  inFlightDraft: draftRow.draft_json,
  farmerCorrection: editStr,
});
...
const draft = result.draft;
const required = (stateMachineExtraction.REQUIRED_FIELDS &&
                  stateMachineExtraction.REQUIRED_FIELDS[draft && draft.type]) || [];
const newPreview = previewBuilderConfirm.buildPreviewWithSuffix({
  draft,
  perFieldConfidence: result.per_field_confidence || {},
  requiredFields: required,
  threshold: config.extractionConfidenceThreshold,
});
```

`REQUIRED_FIELDS` is keyed on the extractor-shape field names. Commit-shape
never enters this code path.

### A6. Curated fixtures are commit-shape (bypassing Phase 38)

`test/farmos/fixtures/curated/activity-water.json`:
```json
{
  "log_type": "activity",
  "draft_json": {
    "activity_subtype": "water",
    "qr_codes": ["QR-FX-SEED-001"],
    "timestamp": 1747180800,
    "notes": "watered block at 9am"
  }
}
```

`test/farmos/fixtures/curated/harvest-multi-bag.json`:
```json
{
  "log_type": "harvest",
  "draft_json": {
    "source_qr_codes": ["QR-FX-SRC-001", "QR-FX-SRC-002"],
    "harvest_batch_name": "HBATCH-2026-05-13-DT-001",
    "bags": [
      { "qr_code": "QR-FX-BAG-001", "weight_grams": 250 },
      ...
```

Compare to extractor schemas in A2 / `schemas/harvest.js:9-19`.

### A7. The "ship gate" fixture is also commit-shape (not real extractor output)

`test/farmos/fixtures/prod-confirmed-draft.json` (lines 41-49):
```json
"log_type": "seeding",
"draft_json": {
  "batch_name": "BATCH-2026-05-12-PROD",
  "block_name": "260512_DT_11",
  "species_code": "DT",
  "qr_codes": ["QR-PROD-FIXTURE-001"],
  "timestamp": 1747082040,
  "notes": "source strain 118.24; substrate bag"
}
```

Vs the actual extractor output for the same kind of input (eval-report
`38-EVAL-REPORT-plan09-smoke-results.json` shows `asset_ref` /
`event_timestamp` -- extractor-shape, not commit-shape).

### A8. Real extractor output (from eval reports)

`.planning/phases/38-extraction-pipeline/38-EVAL-REPORT-plan09-smoke-results.json:2936-2947`
(real LLM call against a real audio):
```json
"asset_ref": "250401_CAS_9",
...
"asset_ref": 0.85,
...
"asset_ref": 0.85,
```

The extractor really does emit `asset_ref`. The commit handlers really do
read `qr_codes`. No code bridges them today.

### A9. 2026-05-14 prod smoke verdict (only 2 of 5 log_types live)

`.planning/phases/40-farmos-write-path/40-PROD-SMOKE-20260514.md`:
> ## Test 1 -- Seeding (PASS)
> ## Test 2 -- Harvest (PASS, with QR-bound source)

Activity, observation, input never appear in the smoke -- never live-
tested before the 2026-05-15 lion's-mane failure.

### A10. Integration suite never invokes the extractor

`test/farmos/integration.test.js:130-213` runs `commitWatchdog.tickOnce`
against pre-staged commit-shape draft rows. Zero
`extractor.extract` calls; verified by grep.

---

# Next-step proposal for the 2026-05-16 discussion

1. Confirm direction: Option A + C bundled, Option B rejected.
2. Resolve the four normalizer open questions in section 3.A
   (harvest QR-vs-block-name resolution, seeding batch_name semantics,
   input recipe_lot placement, harvest qty_g/bags collapse).
3. Decide whether normalize.js lives inside `commits/` or as a sibling
   bridge module (style/discoverability choice).
4. File a v1.8 candidate for the multi-bag harvest extractor extension
   (out of scope for this same-week-fix).
5. Decide whether to re-run the 2026-05-14 prod smoke with the new
   chain test suite as the gate, or treat A+C unit-level green as
   sufficient given the bridged 2026-05-15 happy-path attestation
   already covers activity end-to-end manually.

EOF -- pre-discussion prep; do not act on without Don Santiago sign-off.
