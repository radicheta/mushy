---
phase: 55B-fidelity-corpus-unblock
reviewed: 2026-06-14T00:00:00Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - src/agents/alerter/scripts/a1-probe.js
  - src/agents/alerter/scripts/backfill-notebook.js
  - src/agents/alerter/scripts/backfill-notebook.test.js
  - src/agents/alerter/src/farmos/commits/commit-seeding-session.js
  - src/agents/alerter/src/farmos/groupAssets.js
  - src/agents/alerter/test/farmos/commit-seeding-session.test.js
findings:
  critical: 2
  warning: 6
  info: 4
  total: 12
status: issues_found
---

# Phase 55B: Code Review Report

**Reviewed:** 2026-06-14
**Depth:** standard
**Files Reviewed:** 6
**Status:** issues_found

## Summary

Reviewed the 55B fidelity-corpus-unblock surface: the dev A1 smoke probe, the backfill
driver/fidelity-gate, the seeding-session commit handler, and the asset--group primitives,
plus their hermetic tests. The architecture is careful (audit-first logging, prod-guard,
santi-only gating, all-or-nothing rollback) but two correctness defects can silently drop or
corrupt real backfill data, and several gate inconsistencies undermine the fidelity guarantee
the phase exists to provide.

The most serious issue: the session-aggregation path can build a `seeding_session` whose
`qty` exceeds its `child_block_names` count, which fails the entire page's commit and rolls
back every CSV-verified draft on that page. The second blocker: the fidelity budget is keyed
by the **raw** extracted strain string while the strain-gate that precedes it resolves to
**canonical** codes, so legitimate variant codes that the strain-gate accepts are then held
as fidelity-unverified -- the gate silently rejects data it should pass.

## Critical Issues

### CR-01: Session qty>1 with a single block_name fails the whole page commit

**File:** `src/agents/alerter/scripts/backfill-notebook.js:317-318` (and consumed at `src/agents/alerter/src/farmos/commits/commit-seeding-session.js:214-219`)

**Issue:** `aggregateSeedingDraftsToSessionJson` sums quantities with
`g.qty += (typeof dj.qty === 'number' ? dj.qty : 1)` but only appends one child name per draft
(`if (dj.block_name) g.childBlockNames.push(dj.block_name)`). A single backfill draft carrying
`qty: 3` (or any qty > number of block_names) produces a group with `qty.value=3` and
`child_block_names.value` of length 1. `commitSeedingSession` then loops
`for (let i = 0; i < qty; i++)` and reads `childNames[i]`; at `i=1` `childName` is `undefined`,
triggering the `missing_child_block_name` cleanup -> the ENTIRE session commit fails and the
Pitfall-4 rollback flips every CSV-verified constituent draft on the page back to
`needs_review`. One malformed draft silently nukes an entire page of otherwise-good data. This
is exactly the "silent data loss" class the fidelity work is meant to prevent.

**Fix:** Reconcile qty with the actual child-name count before building the group, and refuse
to emit a group where they disagree rather than letting the session handler fail opaquely:
```js
// in aggregateSeedingDraftsToSessionJson, when building the group:
g.qty += 1;                       // one verified draft == one child block
if (dj.block_name) g.childBlockNames.push(dj.block_name);
// ...
for (const g of groupMap.values()) {
  // qty MUST equal the number of named children, or commitSeedingSession will
  // dereference childNames[i]===undefined and fail the whole session.
  const qty = g.childBlockNames.length || g.qty;
  groups.push({
    parent: { value: g.parent },
    species: { value: g.species },
    qty: { value: qty },
    child_block_names: { value: g.childBlockNames },
  });
}
```
Alternatively, have `commitSeedingSession` validate `qty === childNames.length` up front and
return a per-group reason instead of dereferencing past the array end.

### CR-02: Fidelity budget keyed by raw strain while strain-gate resolves canonical codes -- verified data silently held

**File:** `src/agents/alerter/scripts/backfill-notebook.js:513-516` (vs strain-gate at `:446-449`)

**Issue:** The strain-gate (step 1a) calls `resolveStrain(rawStrain, curatedStrains)` and only
proceeds when `resolved.known` -- i.e. it accepts extraction variants that normalize to a
curated code (per memory: `LIMA<-LIM`, `SHIITAKE<-SHI`, `POY->OYS/KOY`). The fidelity gate
(step 1b) then computes `strainUpper = String(rawStrain).toUpperCase()` from the **raw** code
and calls `consumeCsvBudget(budget, strainUpper)`, where the budget is keyed by the CSV's
canonical strain (`buildCsvBudget` uppercases the CSV `strain` column). When the extractor
emits a variant (e.g. raw `SHIITAKE`) that the strain-gate happily resolves to `SHI`, the
fidelity lookup uses `SHIITAKE`, which is absent from the budget -> the draft is held as
`fidelity_cross_check_unverified` even though it is genuinely CSV-verified. The gate rejects
correct data, defeating its own purpose and re-creating the "drop on disagreement" failure
mode the phase is unblocking. (Symmetric risk: if CSV itself carries a variant, verified
drafts are dropped the other direction.)

**Fix:** Resolve the strain to its canonical code once and use that canonical value for BOTH
the strain-gate hold check and the fidelity budget key:
```js
const resolved = resolveStrain(rawStrain, curatedStrains);   // do this once, before 1b
const canonical = resolved.known ? resolved.code : String(rawStrain || '').toUpperCase();
// strain-gate uses resolved.known; fidelity gate consumes budget by `canonical`
const verified = canonical && consumeCsvBudget(budget, canonical);
```
Ensure `buildCsvBudget` also normalizes CSV strains through the same resolver so both sides
key on identical canonical codes.

## Warnings

### WR-01: A1 probe "prod guard" is dead code that can never trip

**File:** `src/agents/alerter/scripts/a1-probe.js:12-13`

**Issue:** `DEV_URL` is a hardcoded literal `http://10.68.155.50:18080`, and line 13 tests that
same literal against `/:8082|prod/i`. The regex can only ever evaluate the constant, which by
construction never matches, so the guard is unreachable and provides zero protection -- yet the
header comment advertises it as "prod (:8082) is refused". The probe is in fact safe because
the hardcoded URL is what is handed to the client, but the guard gives a false sense of an
active runtime check.

**Fix:** Either drop the dead guard, or make it meaningful by asserting the constant at module
load is dev and documenting it as a compile-time tripwire (e.g. `assert(!/8082|prod/i.test(DEV_URL))`)
so a future edit to the constant fails loudly. Do not describe it as refusing a runtime/env URL.

### WR-02: A1 probe loads .env values without stripping trailing whitespace

**File:** `src/agents/alerter/scripts/a1-probe.js:22-23`

**Issue:** The regex `^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$` uses a greedy `(.*)` that consumes any
trailing spaces, leaving `\s*$` to match empty. A `FARMOS_PASSWORD=secret ` line (trailing
space, common in hand-edited env files) yields a password with a trailing space, producing a
confusing auth failure that the probe will report as a generic upload/login error.

**Fix:** Trim the captured value: `process.env[m[1]] = m[2].replace(/^["']|["']$/g, '').trim();`
(or make the capture non-greedy and anchor the trailing-whitespace strip explicitly).

### WR-03: Session-failure rollback issues N sequential awaited updates with no failure handling

**File:** `src/agents/alerter/scripts/backfill-notebook.js:725-730`

**Issue:** On session-commit failure the rollback loop does `await db.updateDraftStatus(...)`
per constituent with no check of the return value. If one `updateDraftStatus` rejects
(DB blip) the whole `processDraftsForCapture` throws out of the page loop; if it resolves
`{ ok:false }` the draft is left `confirmed` (from the earlier flip at :547) while its
`commits[]` entry says `ok:false` -- an inconsistent state where a draft is marked confirmed but
was never committed and never visibly rolled back. The per-draft flip-failure path (:548)
checks the return; this rollback path does not.

**Fix:** Capture and inspect each rollback result; on failure, record it on the commit entry
(e.g. `rollback_failed: true`) so the receipt surfaces the stranded `confirmed` draft instead
of silently leaving it inconsistent. Consider wrapping each in try/catch so one DB error does
not abort the remaining rollbacks.

### WR-04: `qty` from draft_json is trusted without bounds in the per-draft non-session path

**File:** `src/agents/alerter/src/farmos/commits/commit-seeding-session.js:179, 214`

**Issue:** `qty = g.qty && g.qty.value` is used directly as the loop bound with no validation
that it is a positive integer. A non-numeric or absurd qty (e.g. a string `"5"` -> loop never
runs because `"5" && 0 < "5"` coerces oddly, or a huge number) is not guarded. The truthiness
check `if (!species || !parentName || !qty)` rejects `0`/missing but accepts strings and
floats; `for (let i = 0; i < qty; i++)` with a string bound or float produces wrong child
counts. Backfill data is machine-extracted and untrusted here.

**Fix:** Coerce and validate: `const qty = Number(g.qty && g.qty.value); if (!Number.isInteger(qty) || qty < 1) return _cleanup(... 'invalid_qty' ...);`

### WR-05: `_resolveSessionName` swallows non-OK GET on a colliding group and treats it as foreign

**File:** `src/agents/alerter/src/farmos/commits/commit-seeding-session.js:47-54`

**Issue:** When a candidate name hits an existing group, the handler GETs the group to read its
notes trailer. If that GET fails (network/5xx), `r.ok` is false, the trailer check is skipped,
and the loop silently "advances to next #N" as if the group were foreign. A transient error on
the idempotent re-commit path therefore creates a brand-new `#N` group instead of reusing the
draft's own session group, breaking idempotency and leaking a duplicate session asset.

**Fix:** Distinguish "GET failed" from "trailer did not match". On a failed GET, abort the
resolve with a retryable reason rather than treating the collision as foreign:
```js
if (!r.ok) return null; // or surface a distinct retryable error; do not silently mint #N
```

### WR-06: Strain-gate is skipped entirely when `curatedStrains` is empty, so the fidelity gate runs on unresolved raw codes

**File:** `src/agents/alerter/scripts/backfill-notebook.js:444`

**Issue:** The strain-gate only fires `if (curatedStrains && curatedStrains.length > 0)`. The
real driver (`main`) never passes `curatedStrains` into `processDraftsForCapture` (see the call
at :1069-1073 -- no `curatedStrains` key), so in production the strain-gate is OFF and only the
fidelity gate runs. That means unknown/variant codes are never resolved before the fidelity
budget comparison, compounding CR-02: the live run keys the budget on raw extractor output with
no canonicalization at all. The hermetic tests pass `curatedStrains` but the wired driver does
not, so tests do not cover the production configuration.

**Fix:** Wire `curatedStrains` (from the tenant strain set) into the driver's
`processDraftsForCapture` call, or document and test that the strain-gate is intentionally a
test-only layer. Either way, ensure the fidelity budget keys on canonicalized codes in the
live path (see CR-02).

## Info

### IN-01: `dispatchPage` returns `corpusContext` from the caller but builds the row with a freshly hardcoded context

**File:** `src/agents/alerter/scripts/backfill-notebook.js:191, 204-209`

**Issue:** `buildSyntheticCapture` hardcodes `corpus_context: { default_year: 2025, source: 'paper_log' }`
while `dispatchPage` separately receives a `corpusContext` arg and forwards it to
`pipeline.enqueue`. The two can diverge (the inserted DB row's context is always 2025/paper_log
regardless of the passed `corpusContext`). Today they always match, but the duplication is a
latent inconsistency.

**Fix:** Pass `corpusContext` into `buildSyntheticCapture` so the persisted row and the enqueued
job share one source of truth.

### IN-02: Magic collision ceiling and pricing constants

**File:** `src/agents/alerter/src/farmos/commits/commit-seeding-session.js:25`, `src/agents/alerter/scripts/backfill-notebook.js:829-832`

**Issue:** `COLLISION_MAX = 9` and the four per-MTok pricing constants are reasonable but
undocumented as to why 9 (the `#N` suffix only goes to single digits) and carry a hand-dated
rate card that will silently drift. These are acknowledged inline for pricing; the `#9` cap is
not justified.

**Fix:** Add a one-line note on why the suffix caps at 9 (single-digit name convention) and a
TODO to source pricing from a shared rate-card module.

### IN-03: `up.reason` referenced on a success object in the A1 probe

**File:** `src/agents/alerter/scripts/a1-probe.js:66`

**Issue:** `throw new Error('image upload failed: ' + (up.reason || 'unknown'))` only runs when
`!up.ok`, so `up.reason` exists there -- correct. Noted only because the success object from
`uploadFieldAttachment` has no `reason` field; the guard is fine but the pattern invites
confusion if reused.

**Fix:** None required; optionally normalize the upload result to always carry `reason`.

### IN-04: Test comments still label RED scaffolds that are now GREEN

**File:** `src/agents/alerter/scripts/backfill-notebook.test.js:1116-1122, 1171-1172, 1412-1413`

**Issue:** Several test blocks are commented as "intentionally RED" / "not yet honored" / "RED
until the dispatch is wired" but the corresponding functionality (`buildCsvBudget`,
`csvRowsForPage`, session dispatch) is now implemented and exported, so the comments are stale
and misleading to future readers.

**Fix:** Remove or update the RED-scaffold comments now that the features have landed.

---

_Reviewed: 2026-06-14_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
