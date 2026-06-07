---
phase: 55-full-corpus-run-receipt
reviewed: 2026-06-07T00:00:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - src/agents/alerter/scripts/backfill-notebook.js
  - src/agents/alerter/scripts/backfill-notebook.test.js
  - src/agents/alerter/scripts/build-backfill-receipt.js
  - src/agents/alerter/scripts/build-backfill-receipt.test.js
findings:
  critical: 2
  warning: 3
  info: 2
  total: 7
status: issues_found
---

# Phase 55: Code Review Report

**Reviewed:** 2026-06-07
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

Reviewed the Phase 55 additions to the backfill harness: the `--all-pages` flag in
`backfill-notebook.js`, plus `buildUuidJsonl`, `computePerShapeStats`, the BACK-10 section,
and the notes copy-out wiring in `build-backfill-receipt.js`, and both test files.

The individual helper functions (`buildUuidJsonl`, `computePerShapeStats`, `buildReceipt`
notes copy-out) are solid and well-tested. Two blockers exist at the integration seam:
the strain-gate is fully dead in production runs through `main()`, and the
`sendUnknownStrainBatch` call is also missing from `main()`. Both are pre-existing
scaffolding that was wired for unit tests but never threaded into the main dispatch loop.
A third warning: the notes copy-out overwrites without a collision guard, which conflicts
with the paid-result persistence policy.

---

## Critical Issues

### CR-01: `curatedStrains` never passed to `processDraftsForCapture` in `main()` -- strain-gate is a no-op in production

**File:** `src/agents/alerter/scripts/backfill-notebook.js:733-738`

**Issue:** The call to `processDraftsForCapture` inside the page loop omits `curatedStrains`:

```js
const { drafts, commits } = await processDraftsForCapture({
  pool, client, captureId: entry.captureId, pagePath: page,
  opts, summariesFd, extractionDb, commitRouter, dryRun: false,
  // curatedStrains: ??? -- not passed
});
```

Inside `processDraftsForCapture`, the guard condition is:

```js
if (curatedStrains && curatedStrains.length > 0) { ... }
```

When `curatedStrains` is `undefined` (the default), the condition is falsy and the entire
strain-gate block is skipped. Every draft goes straight through to `flipDraftToConfirmed`
+ `commit-router`, regardless of whether its strain code is in the curated 14-code set.
The protection against blind-minting unknown strains (Cycle-1 finding B, the whole point
of BACK-T-54.1-03) is silently bypassed on every real run.

Unit tests cover the gate thoroughly, but they inject `curatedStrains` directly; none of
them exercise the `main()` code path, so this gap is invisible to the test suite.

**Fix:** Load the curated strain list before the loop and pass it through:

```js
// Before the page loop, load curated strains (same path used by the alerter tenant config):
const curatedStrains = opts.bulkBackfill
  ? (function loadCurated() {
      try {
        const yaml = require('js-yaml');
        const p = require('path').resolve(__dirname, '../tenants/mossrock/strains.yaml');
        return yaml.load(require('fs').readFileSync(p, 'utf8')).strains || [];
      } catch (_e) { return []; }
    })()
  : [];

// Then in the loop:
const { drafts, commits, heldUnknownCodes: pageHeld } = await processDraftsForCapture({
  pool, client, captureId: entry.captureId, pagePath: page,
  opts, summariesFd, extractionDb, commitRouter, dryRun: false,
  curatedStrains,
});
```

(Or inject via a parameter for testability -- see CR-02 below.)

---

### CR-02: `heldUnknownCodes` discarded in `main()`; `sendUnknownStrainBatch` never called -- farmer never receives the batched strain-confirm message

**File:** `src/agents/alerter/scripts/backfill-notebook.js:733-738`

**Issue:** `processDraftsForCapture` returns `{ drafts, commits, heldUnknownCodes }`, but
`main()` destructures only `{ drafts, commits }`. The `heldUnknownCodes` array is silently
discarded on every iteration. After the loop, `sendUnknownStrainBatch` is never called.

Even if CR-01 were fixed so the gate actually fires, the farmer would receive no batched
Signal message asking about unknown codes, and no `pending-strain-confirm.json` would be
written. The whole Task-2 round-trip (BACK-54.1-02) is wired internally but never triggered
from production.

`sendUnknownStrainBatch` is exported and tested in isolation, but there is no integration
path from `main()` to it.

**Fix:** Accumulate held codes across pages, then call `sendUnknownStrainBatch` after the
loop (before the `finally` block or at the top of `finally` before closing FDs):

```js
const allHeldUnknownCodes = [];

for (const page of selected) {
  const entry = await dispatchPage({ ... });
  if (entry.ok === true) {
    const { drafts, commits, heldUnknownCodes } = await processDraftsForCapture({
      ..., curatedStrains,
    });
    entry.draftIds = drafts.map((d) => d.id);
    entry.commits = commits;
    // Merge per-page held codes (dedup by code):
    for (const h of heldUnknownCodes) {
      const existing = allHeldUnknownCodes.find((x) => x.code === h.code);
      if (existing) {
        existing.draftIds.push(...h.draftIds);
      } else {
        allHeldUnknownCodes.push({ ...h });
      }
    }
  }
  runSummary.push(entry);
  ...
}

// After page loop, before finally:
if (allHeldUnknownCodes.length > 0) {
  await sendUnknownStrainBatch({
    unknowns: allHeldUnknownCodes,
    runDir,
    runId,
    signalSend: /* inject or require send helper */,
    recipient: sender,
    logger,
  });
}
```

---

## Warnings

### WR-01: Notes copy-out (`notesReceiptPath` / `notesJsonlPath`) overwrites without collision guard -- violates paid-result persistence policy

**File:** `src/agents/alerter/scripts/build-backfill-receipt.js:509-515`

**Issue:** `buildReceipt` calls `fs.writeFileSync` unconditionally on `notesReceiptPath`
and `notesJsonlPath`:

```js
if (notesReceiptPath) {
  fs.mkdirSync(path.dirname(notesReceiptPath), { recursive: true });
  fs.writeFileSync(notesReceiptPath, body, 'utf8');   // clobbers on second run same day
}
if (notesJsonlPath) {
  fs.mkdirSync(path.dirname(notesJsonlPath), { recursive: true });
  fs.writeFileSync(notesJsonlPath, buildUuidJsonl(runSummary), 'utf8');  // same
}
```

The filename is `<YYYY-MM-DD>-2025-notebook-backfill-receipt.{md,jsonl}`. If a full-corpus
run is attempted twice on the same calendar date (e.g. after a crash and retry with a fresh
`--run-id`), the prior notes artifacts are silently overwritten. This conflicts with the
project policy in `[[feedback_persist_paid_results_default]]` ("per-call unique paths +
append-only JSONL; never overwrite paid live-API results"). The UUID JSONL is the permanent
audit trail of which farmOS assets were created.

**Fix:** Check before writing and either refuse or suffix with the run-id:

```js
if (notesReceiptPath) {
  if (fs.existsSync(notesReceiptPath)) {
    // Append run-id to avoid clobbering
    const ext = path.extname(notesReceiptPath);
    const base = notesReceiptPath.slice(0, -ext.length);
    notesReceiptPath = `${base}-${runId}${ext}`;
  }
  fs.mkdirSync(path.dirname(notesReceiptPath), { recursive: true });
  fs.writeFileSync(notesReceiptPath, body, 'utf8');
}
```

Or pass `runId` into `buildReceipt` and always incorporate it in the notes filename (it is
already available at the call site in `backfill-notebook.js`).

---

### WR-02: `elapsedSec` is hardcoded to `0` in every `buildReceipt` call -- receipt always reports zero elapsed time

**File:** `src/agents/alerter/scripts/backfill-notebook.js:777`

**Issue:**

```js
buildReceipt({
  ...,
  elapsedSec: 0,   // <-- always 0
  ...
});
```

No wall-clock start time is captured before the page loop, so actual elapsed time is never
computed. The receipt -- the single farmer-review document for Cycle 2 -- will always show
`elapsed_seconds: 0`, which is misleading for a run over 87 corpus pages.

**Fix:** Capture start time before entering the page loop:

```js
const startMs = Date.now();
// ... page loop ...
// In finally:
buildReceipt({
  ...,
  elapsedSec: Math.round((Date.now() - startMs) / 1000),
  ...
});
```

---

### WR-03: `ANTHROPIC_API_KEY` is documented as required for non-dry-run but excluded from the missing-env guard

**File:** `src/agents/alerter/scripts/backfill-notebook.js:622-629`

**Issue:** The header comment at lines 28-33 lists `ANTHROPIC_API_KEY` as required for
non-dry-run. But the missing-env guard only checks four keys:

```js
const missing = ['FARMOS_URL', 'FARMOS_USERNAME', 'FARMOS_PASSWORD', 'DATABASE_URL']
  .filter((k) => !env[k]);
```

`ANTHROPIC_API_KEY` is absent. A real run without it will fail late (when the extractor
makes its first LLM call) rather than early at startup, after DB inserts have already been
written and summaries.log is open.

**Fix:** Add `ANTHROPIC_API_KEY` to the missing-env list:

```js
const missing = ['FARMOS_URL', 'FARMOS_USERNAME', 'FARMOS_PASSWORD', 'DATABASE_URL', 'ANTHROPIC_API_KEY']
  .filter((k) => !env[k]);
```

---

## Info

### IN-01: Redundant `require('path')` inside the `finally` block (style)

**File:** `src/agents/alerter/scripts/backfill-notebook.js:765-767`

**Issue:** `path` is already required at the top of the file (line 44), but the `finally`
block re-requires it twice as `require('path')`:

```js
const notesDir = require('path').resolve(__dirname, '../../../../.planning/notes');
notesReceiptPath = require('path').join(notesDir, `${basename}.md`);
notesJsonlPath = require('path').join(notesDir, `${basename}.jsonl`);
```

Node.js caches `require` results so this is not a runtime bug, but it is inconsistent with
the rest of the file and suggests this block was written in isolation.

**Fix:** Use the already-required `path` binding.

---

### IN-02: `main()` integration test for `--all-pages` is vacuous -- it does not verify page selection

**File:** `src/agents/alerter/scripts/backfill-notebook.test.js:186-205`

**Issue:** The `main() -- all-pages resolves limit to Infinity` test acknowledges in a
comment that it cannot test page selection via the normal path, then falls back to only
asserting `result.code === 0`. The test description promises verification of "selects all
corpus pages" but delivers only "does not crash." The actual corpus listing is not stubbed
so the corpus dir is missing and `listCorpusPages` returns `[]`, making `runSummary`
empty. The test is not wrong, but it contributes no confidence beyond "main() doesn't
crash on --all-pages".

**Fix:** Stub `fs.readdirSync` (as done in the existing `--dry-run with --bulk-backfill`
test at line 344) and assert `runSummary.length === <expected>` to actually verify
the `limit=Infinity` path.

---

_Reviewed: 2026-06-07_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
