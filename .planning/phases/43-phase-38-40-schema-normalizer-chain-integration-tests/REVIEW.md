---
phase: 43
plan: phase-wide
review_date: 2026-05-16
reviewer: gsd-code-reviewer
status: fixed
blocker_count: 0
warning_count: 0
info_count: 0
---

# Phase 43: Code Review Report

**Reviewed:** 2026-05-16
**Depth:** deep
**Files Reviewed:** 6
**Files reviewed list:**
- src/agents/alerter/src/farmos/commits/normalize.js
- src/agents/alerter/src/farmos/commits/commit-router.js
- src/agents/alerter/src/farmos/qr.js
- src/agents/alerter/test/farmos/normalize.test.js
- src/agents/alerter/test/farmos/integration/extractor-to-commit.test.js
- src/agents/alerter/test/farmos/qr.test.js

**Status:** findings

---

## Summary

Phase 43 ships a router-side normalizer (`normalize.js`), a name-fallback extension to `resolveQr`, and a 5-test chain integration suite. The core architecture is sound: D-02 (DB never touched, normalize called once per commit invocation from fresh extractor-shape) means most latent issues cannot be triggered in the current production flow. The 2026-05-15 regression guard (Test 2) is present with the verbatim transcript, no env gate exists, and the wire-in is correctly placed at the dispatch site. However, one blocker is present: `normalize.js` falsely claims `recipe_lot` is "consumed and removed" while it stays in the output `draft_json`, violating the idempotency contract for the `input` (and `observation` `state`) cases -- and both extractor-side fields survive in the normalized output without guard, so any future caller that runs `normalize()` twice on the same result (e.g., after architectural change to D-02) will produce duplicate notes lines. Three warnings cover the shallow-copy array aliasing, a misleading comment that contradicts the code, and a test fixture species/block_name mismatch. Two info items note an unreachable-but-wrong note-count edge and a naming inconsistency in Test 4's assertion message.

---

## Critical Issues (BLOCKER)

### CR-01: `normalize.js` does NOT satisfy its own idempotency contract for `input` and `observation` -- `recipe_lot` and `state` keys survive in output `draft_json` unguarded

**File:** `src/agents/alerter/src/farmos/commits/normalize.js:95-108`

**Issue:** The normalizer comment at line 96 states "the field is consumed and removed from the extractor-shape" about `recipe_lot`. This is false -- `recipe_lot` is never deleted from `out`. After `normalize()` runs, the output `draft_json` contains BOTH `recipe_lot: 'RB-2026-05'` AND `notes: 'recipe_lot: RB-2026-05\n...'`. If `normalize()` is called a second time on that output (e.g., any future code path that writes the normalized shape back to the DB and re-reads it), `recipe_lot` triggers the guard again and prepends a second `'recipe_lot: RB-2026-05\n'` line to notes. The same structural failure applies to the `observation` `state` field: it survives in the normalized output, so a second `normalize()` call appends `'\nstate: pinning'` a second time.

Verified by direct execution:
```
normalize() pass 1 notes: "recipe_lot: RB-2026-05\nexisting notes"
recipe_lot still in draft_json after pass 1: true

normalize() pass 2 notes: "recipe_lot: RB-2026-05\nrecipe_lot: RB-2026-05\nexisting notes"
```

The SCHEMA-03 unit test in `normalize.test.js:257-269` does NOT catch this because it feeds a *commit-shape* input (which has no `recipe_lot` key). The idempotency test proves "commit-shape passes through unchanged" but does NOT prove "extractor-shape passes through unchanged if normalize() is run twice."

**Current architecture mitigation:** D-02 (DB keeps extractor-shape; `commit-router.js` reads fresh from DB each invocation) means this path is unreachable today. The bug is latent but the misleading comment actively invites the mistake in any future refactor that writes normalized shape back to DB for performance or retry caching. The comment should say "field is NOT removed" with an explicit architectural dependency note.

**Fix:** Either delete the extractor-side field from `out` after consuming it, or correct the comment and add a guard:

```js
// Option A: delete after use (cleanest, eliminates the hazard)
case 'input':
  if (typeof out.recipe_lot === 'string') {
    out.notes = 'recipe_lot: ' + out.recipe_lot + (out.notes ? '\n' + out.notes : '');
    delete out.recipe_lot;   // consume -- field must not survive into commit-shape
  }
  break;

case 'observation':
  if (typeof out.state === 'string' && out.state !== '') {
    out.notes = out.notes ? (out.notes + '\nstate: ' + out.state) : ('state: ' + out.state);
    delete out.state;         // consume -- field must not survive into commit-shape
  }
  break;
```

```js
// Option B: correct the comment and add an explicit guard
// Guard: skip if recipe_lot field absent (idempotency).
// NOTE: recipe_lot is NOT deleted from out -- it remains in the normalized
// draft_json. This means calling normalize() twice on the same input WILL
// double-prepend. This is architecturally safe only because D-02 guarantees
// normalize() is called once per commit invocation against fresh extractor-shape from DB.
// If D-02 ever changes, delete out.recipe_lot here.
```

Option A is preferred -- it eliminates the maintenance trap, makes SCHEMA-03 provable without architectural assumptions, and is two lines.

A matching unit test should feed extractor-shape through `normalize()` TWICE and assert the second call produces identical output to the first:
```js
it('input: normalize twice on extractor-shape produces same result as normalize once', () => {
  const draft = makeDraft('input', { recipe_lot: 'RB', asset_ref: 'Q1', timestamp: 1000 });
  const pass1 = normalize(draft);
  const pass2 = normalize(pass1);
  expect(pass2.draft_json.notes).toEqual(pass1.draft_json.notes);
});
```

---

## Warnings

### WR-01: `normalize.js` performs a shallow copy of `draft_json` -- arrays from the original are aliased by reference in the returned object

**File:** `src/agents/alerter/src/farmos/commits/normalize.js:27`

**Issue:** `Object.assign({}, dj)` shallow-copies `dj`. Any array already present in `dj` (e.g., `dj.qr_codes`, `dj.source_block_refs`, `dj.bags`) is shared by reference between the original `draft.draft_json` and the normalized output's `draft_json`. Verified:

```js
const orig_qr = ['Q1'];
const draft = { ..., draft_json: { qr_codes: orig_qr, ... } };
const result = normalize(draft);
result.draft_json.qr_codes.push('Q2');
// draft.draft_json.qr_codes is now ['Q1', 'Q2'] -- original mutated
```

The commit handlers currently only read these arrays (no `push`/`splice`), so no mutation happens in production today. But the D-01 contract says normalize "does NOT mutate its input." That guarantee is broken if any downstream consumer pushes to a returned array. This is a maintenance trap.

**Fix:** Deep-copy arrays that are passed through from the original `dj`:
```js
// At the shallow copy site, clone arrays defensively:
const out = Object.assign({}, dj);
// Deep-clone any array fields already present in dj:
if (Array.isArray(out.qr_codes)) out.qr_codes = out.qr_codes.slice();
if (Array.isArray(out.source_block_refs)) out.source_block_refs = out.source_block_refs.slice();
if (Array.isArray(out.bags)) out.bags = out.bags.slice();
if (Array.isArray(out.source_qr_codes)) out.source_qr_codes = out.source_qr_codes.slice();
if (Array.isArray(out.input_ingredients)) out.input_ingredients = out.input_ingredients.slice();
```
Alternatively, use `JSON.parse(JSON.stringify(dj))` for a full deep clone, which is safe given `draft_json` is always JSON-serializable.

---

### WR-02: `normalize.js:96` comment misrepresents code behavior -- states `recipe_lot` is "consumed and removed" when it is not

**File:** `src/agents/alerter/src/farmos/commits/normalize.js:95-97`

**Issue:** The comment reads:

```
// Guard: skip if recipe_lot field absent (idempotency for commit-shape which
// has no recipe_lot field -- the field is consumed and removed from the
// extractor-shape, so the guard naturally fires on pass-through).
```

The phrase "consumed and removed from the extractor-shape" is factually wrong. `recipe_lot` is read but never deleted from `out`. The comment will mislead the next person who reads this code into assuming the idempotency is robust, potentially causing them to skip the "delete on consume" fix. This comment directly reinforces the CR-01 latent bug.

**Fix:** Replace the misleading comment:
```js
// Guard: skip if recipe_lot field absent.
// WARNING: recipe_lot is NOT deleted from out -- it survives in the normalized
// draft_json. The idempotency guarantee holds only because D-02 (43-CONTEXT.md)
// guarantees this function is called once per commit() against fresh extractor-shape.
// If that assumption ever changes, add: delete out.recipe_lot; below the assignment.
if (typeof out.recipe_lot === 'string') {
```

Or, preferably, fix CR-01 by deleting the field and update this comment to reflect that.

---

### WR-03: Test 1 seeding fixture has an internally inconsistent block_name/species pairing that could mask future species-routing bugs

**File:** `src/agents/alerter/test/farmos/integration/extractor-to-commit.test.js:100-105`

**Issue:** The mocked extractor output has `species: 'SHI'` (shiitake) but `block_name: '260516_DT_1'` (DT = oyster mushroom by the B5 `YYMMDD_SPECIES_SEQ` convention). The test message text says "with 1kg shiitake grain" yet the block ID encodes 'DT'. These are contradictory. If a future bug causes species to be extracted from `block_name` (e.g., as a fallback), the test would pass on wrong species because the mock LLM returns a hardcoded `species: 'SHI'` regardless of the block name.

More practically: `commit-seeding.js:44` has a 4-alias chain `dj.species_code || dj.species || dj.strain || dj.fungi_type`. After normalization, `species_code: 'SHI'` is set. The mock client resolves `SHI` to `'ft-shi'`. A test with `block_name: '260516_SHI_1'` and `species: 'SHI'` would be internally consistent and equally valid without any code change.

**Fix:** Change the fixture to `block_name: '260516_SHI_1'` (matching species SHI) or change `species` to `'DT'` and update related assertions and mock expectations. Either direction is a one-field change:
```js
const extractorDraft = {
  type: 'seeding',
  species: 'SHI',
  block_name: '260516_SHI_1',   // was '260516_DT_1' -- corrected to match B5 convention
  ...
};
// Also update the assertion:
expect(client._created.assets[0].name).toBe('260516_SHI_1');
```

---

## Info

### IN-01: `normalize.js` comment on `recipe_lot` notes order differs from actual commit-input serializer output

**File:** `src/agents/alerter/src/farmos/commits/normalize.js:89-91`

**Issue:** The comment shows an expected final notes output of:
```
recipe_lot: RB-2026-05

Ingredients:
- oat 1kg
- gypsum 50g
```

This implies a blank line between `recipe_lot` and `Ingredients:`. In practice, `commit-input.js:25` produces:
```
recipe_lot: RB-2026-05\n
Ingredients:\n- oat 1kg
```
(with only a single newline from the `dj.notes + '\n'` join, no blank separator). Since the extractor never emits `input_ingredients`, the actual live output for Phase 43 is just `'recipe_lot: RB-2026-05\n'` with no ingredients section at all. The double-blank-line in the comment is aspirational documentation for a future state that doesn't exist yet.

Minor documentation accuracy issue -- doesn't affect runtime behavior.

---

### IN-02: Test 4 assertion checks `toContain('recipe_lot: RB-2026-05')` on `logNotes` but `logNotes` has a trailing newline -- toContain still passes but the assertion is less precise than it could be

**File:** `src/agents/alerter/test/farmos/integration/extractor-to-commit.test.js:294-295`

**Issue:** `logNotes` ends up as `'recipe_lot: RB-2026-05\n'` (trailing newline from `commit-input.js:25`'s `dj.notes + '\n'`). `toContain` passes on this. However a `toBe` or `toMatch(/^recipe_lot: RB-2026-05/)` would be more precise about the position and eliminate a future regression where recipe_lot appears somewhere in the middle of a longer notes string.

D-09 specifies PREPEND. The current assertion validates presence but not position. The `normalize.test.js:179` test uses exact `toBe` -- the integration test is weaker.

**Fix (optional):** Replace `toContain` with `toMatch(/^recipe_lot: RB-2026-05/)` to assert leading position, consistent with the D-09 contract and the unit test at `normalize.test.js:285`.

---

## What Looks Good (Do Not Change)

- **Wire-in placement (D-02):** `commit-router.js:40` calls `normalize(draft)` exactly once, at the dispatch site, before `fn(client, ...)`. The original `draft` argument (which came from the DB) is not mutated. This is the correct placement.

- **D-06 network-error early-return:** `qr.js:39` returns `{ found: false, error: 'http_' + r.status, path: 'id_tag' }` immediately when the id_tag lookup returns a non-OK HTTP status. The name-fallback is NOT attempted on transport errors. The `qr.test.js:55-63` test explicitly asserts `getImpl` called exactly once on 500. This correctly implements the D-06 requirement that "transport failures are NOT a miss."

- **Test 2 regression guard fidelity (D-16):** The verbatim transcript `"Two days ago, I put a lion's mane block into the fruiting chamber to fruiting Two days ago forgot to tell to tell you so yeah log it up Lion"` matches the `43-FIXTURES.md` authoritative source exactly (character-for-character verified). The test correctly uses the commit-failure path (Option A from 43-FIXTURES.md), asserting `commit_success: false` with reason `no_target_asset_for_activity` -- the classifiable failure that distinguish post-normalize behavior from the pre-normalize crash.

- **SCHEMA-04 no env gate:** The integration test file has no `FARMOS_INTEGRATION`, `describe.skip`, or conditional `require` patterns. It runs under `npm test` by default.

- **Non-mutation (for scalar fields):** `normalize()` creates a new `out` object via `Object.assign` and returns `Object.assign({}, draft, { draft_json: out })`. Scalar fields on `draft` and `draft_json` are not mutated. The non-mutation unit tests (`normalize.test.js:289-306`) correctly verify this for the scalar case.

- **Idempotency for the stated SCHEMA-03 contract:** When a commit-shape draft (with `qr_codes`, numeric `timestamp`, `activity_subtype` already set, and no `recipe_lot`/`state` key) is passed to `normalize()`, it passes through byte-identical. The SCHEMA-03 unit tests at `normalize.test.js:219-283` cover all 5 log_types with commit-shape inputs. This guarantee holds for the architectural invariant in D-02.

- **Mock-client route ordering:** The `mock-client.js` regex handlers check `filter[name][value]` before `filter[id_tag.id][value]`, but this is irrelevant -- the URL patterns are mutually exclusive by URL structure, so the GET dispatch is always correct regardless of check order.

---

_Reviewed: 2026-05-16_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_

---

## Fixes Applied

- **CR-01** (+ WR-02): fixed in commit `4779434` -- `normalize.js` now deletes `out.recipe_lot` (input) and `out.state` (observation) after consuming them into notes; comment updated to reflect "consumed and removed" is now accurate. New tests: input/observation idempotency-on-extractor-shape (two-pass assert) in `normalize.test.js`.
- **WR-01**: fixed in commit `4779434` -- added `.slice()` clones for all known array fields (`qr_codes`, `source_block_refs`, `source_qr_codes`, `bags`, `input_ingredients`) immediately after the initial `Object.assign`. New test: push to `result.draft_json.qr_codes` does not mutate original.
- **WR-03**: fixed in commit `1062019` -- Test 1 `block_name` changed from `260516_DT_1` to `260516_SHI_1` (species SHI); updated extractor boundary assertion and asset name assertion to match.
- **IN-02**: fixed in commit `1062019` -- Test 4 commit boundary assertion changed from `toContain('recipe_lot: RB-2026-05')` to `toMatch(/^recipe_lot: RB-2026-05/)` asserting PREPEND position per D-09.
- **IN-01**: skipped (cosmetic comment nit, per scope).

_Fixed: 2026-05-16_
_Fixer: Claude (gsd-code-fixer)_
