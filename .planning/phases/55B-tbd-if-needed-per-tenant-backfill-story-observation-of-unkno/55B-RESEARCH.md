# Phase 55B: Fidelity / Corpus-Unblock -- Research

**Researched:** 2026-06-09
**Domain:** Node.js backfill harness, farmOS JSON:API, alerter commit pipeline
**Confidence:** HIGH (pure codebase archaeology; no external packages involved)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 -- Hold-everything-unverified (conservative).** Auto-commit ONLY entries that
  exactly agree with the page's CSV reading. Every CSV disagreement AND every entry with
  no CSV reading at all is held as `needs_review` (reuse the 54.1 hold state -- not
  committed). Nothing unverified reaches farmOS.
- **D-02 -- Resolution surface is the F2 session view, NOT a Signal batch.** Held
  (`needs_review`) entries must appear inside the session view alongside the attached page
  image so a human reconciles them against the actual notebook.
- **D-03 -- Attach at the session group asset, 1..N page images.** Attach every notebook
  page a session spans to the single inoc-session group asset (NOT per-log). One upload
  path (extend `commit-seeding-session.js`); no per-log attachment code in the other 4
  commit paths.
- **D-04 -- The grouping/reconcile unit is the INOC SESSION, not the notebook page.** A
  single inoc session can span more than one notebook page (and a page may hold more than
  one session / a mix of shapes). F2 is therefore a session view, not a page view.

### Claude's Discretion

- Exact mechanism for keying the CSV cross-check (per-entry strain/quantity match
  granularity; how a page's CSV rows map onto extracted entries).
- How backfill switches from plain `log_type:'seeding'` to session-shaped commits (the
  audit-findings todo notes backfill currently emits plain `seeding` -- routed to
  per-block `commit-seeding`, bypassing the session group). Researcher/planner picks the
  cleanest route into `commit-seeding-session.js`.
- Whether/how non-seeding shapes on a session (observation/harvest/activity/input) attach
  to the session group -- the original "Session-per-page shape" question Santi deferred.
  Default: member logs reference member assets which carry the group edge; the membership
  log lists them. Validate during research.
- How `needs_review` entries are rendered/queryable inside the session view.
- Smoke/re-audit set size and selection.

### Deferred Ideas (OUT OF SCOPE)

- Extraction-prompt strain-column hardening (root-cause fix for POY->KOY misreads).
- Strain-gate re-wire (CR-01/CR-02) -- moot + does not catch mode-2 silent misattribution.
- Prod cleanup of the 2026-06-07 audit set (99 assets + 98 logs) -- needs farmOS admin DELETE.
- Per-tenant backfill -- v1.12 Python port.
- Observation-of-unknown-asset standalone path -- covered by Phase 51 upsert + 54.1 strain-confirm.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FIDELITY-01 | Commit-time CSV cross-check that holds any extracted entry not exactly matched by the per-page CSV reading | `computeCsvDiff` in `build-backfill-receipt.js` is the reuse target; the hold path follows the 54.1 strain-gate pattern in `processDraftsForCapture` |
| FIDELITY-02 | `needs_review` HOLD: auto-commit only exact-CSV-verified entries; all disagreements and no-CSV-reading entries stay held | `updateDraftStatus(pool, draftId, 'needs_review', { needs_review_reason: 'fidelity_cross_check_unverified' })` pattern exists and is whitelisted |
| SESSION-01 | Backfill emits session-shaped commits so per-block logs/assets group under the inoc-session group asset | The seam is in `processDraftsForCapture`: currently routes all drafts regardless of shape; needs a session aggregation pass before per-draft dispatch |
| SESSION-02 | Source notebook page image(s) attached to the session group asset (1..N pages per session) | `files.uploadAttachments` + new call in `commitSeedingSession` after `upsertGroupAsset`; `attachment_paths` already in synthetic capture |
| SESSION-03 | Held `needs_review` entries surface inside the farmOS session view so a human can reconcile against the notebook | farmOS native: held assets remain in the group's membership log; `needs_review_reason` stored in DB only (not in farmOS) -- the image on the session asset IS the reconcile surface |
| SMOKE-01 | Re-smoke a small set with the new fidelity guard and session surface before any full run | Reuse GA1 isolation pre-flight (55-FULL-CORPUS-RUNBOOK.md); 5-page smoke gate |
</phase_requirements>

---

## Summary

Phase 55b delivers two coupled capabilities that are prerequisites for the parked
full-2025-corpus run. The root cause for parking was the 2026-06-07 prod audit: ~38%
infidelity on checkable pages, including silent misattribution (POY committed as KOY
with no error). The strain-gate (CR-01/CR-02) is moot because it cannot catch mode-2
silent misattribution -- only a commit-time CSV cross-check can.

Both capabilities build on existing infrastructure. The fidelity cross-check promotes
`computeCsvDiff` (already in `build-backfill-receipt.js`) from a receipt-only reporter to
a commit gate inside `processDraftsForCapture`. The session surface routes backfill seeding
drafts through the existing `commit-seeding-session.js` (Phase 52 mechanism) and extends
it with image upload to the session group asset.

The critical design insight: D-01 requires holding EVERYTHING unverified -- not just
strain mismatches, but also all entries on pages with no CSV reading (about half the
corpus). This means ~50% of drafts will be held, which is expected. The F2 session view
(the farmOS group asset page with attached notebook image) is the resolution UI -- not
Signal.

**Primary recommendation:** Two plan tracks (fidelity cross-check + session routing), each
with a narrow scope. Fidelity cross-check is ~100 lines concentrated in
`processDraftsForCapture`. Session routing requires one new per-page aggregation pass
before the draft loop, plus image upload wired into `commitSeedingSession`.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| CSV cross-check gate | Backfill harness (Node script) | -- | The CSV diff logic already lives here; commit-time gate belongs in `processDraftsForCapture` before the flip-to-confirmed step |
| Hold state write | Harness -> extraction-db | -- | `updateDraftStatus` with `needs_review` + audit reason; same pattern as 54.1 strain-gate |
| Session group creation | commit-seeding-session.js | groupAssets.js | Phase 52 mechanism; upsertGroupAsset already handles lookup-or-create |
| Page image attachment | commit-seeding-session.js | files.js | uploadAttachments already works (private-files live per CONTEXT.md canonical ref); only wiring is missing |
| Session membership log | activityLogs.js | commit-seeding-session.js | createGroupAssignmentLog already binds children to session group |
| F2 reconcile surface | farmOS UI (native) | -- | The group asset page in farmOS shows members + attachments natively; `needs_review` display is mushy-DB-only; nothing new needed in farmOS |
| Non-seeding shapes on session | Per-commit handlers (unchanged) | activityLogs.js | These shapes' assets are already group-members if their assets carry parent edges; the membership log binds child assets to session; no handler changes needed for non-seeding in 55b |
| Re-smoke | Operator + runbook | Harness dry-run | Reuse GA1 isolation pre-flight; 5-page paid smoke |

---

## Standard Stack

### Core (all existing -- no new packages)

| Library / Module | Version | Purpose | Why Standard |
|-----------------|---------|---------|--------------|
| `scripts/backfill-notebook.js` | existing | Harness CLI; fidelity gate goes here | The only entry point for backfill; all guards already here |
| `scripts/build-backfill-receipt.js` | existing | `computeCsvDiff` logic | Already parses CSV and computes hit/miss/extra per page; promote to commit gate |
| `src/farmos/commits/commit-seeding-session.js` | existing | Session group asset + membership log | Phase 52 mechanism; the single extension point for D-03 |
| `src/farmos/files.js` | existing | `uploadAttachments` -- POST to `/api/file/file` | Only working upload path; used by commit-observation today |
| `src/farmos/groupAssets.js` | existing | `upsertGroupAsset` (lookup-or-create) | Content-addressable by session name; idempotent |
| `src/farmos/activityLogs.js` | existing | `createGroupAssignmentLog` | Binds N child assets to the session group via `is_group_assignment=true` |
| `src/extraction/extraction-db.js` | existing | `updateDraftStatus` with `needs_review` | `needs_review_reason` is whitelisted; same channel as 54.1 strain-gate |

### No New Packages

Phase 55b introduces zero new npm dependencies. All capability is wiring of existing code.

**Package Legitimacy Audit:** Not applicable -- no new packages.

---

## Architecture Patterns

### System Architecture Diagram

```
backfill-notebook.js (main loop)
  |
  +-- dispatchPage()
  |     builds synthetic capture -> extraction pipeline -> drafts in DB
  |
  +-- [NEW] aggregateSessionsForPage()          <-- NEW per-page pass
  |     groups seeding drafts by inoc session
  |     one session = one commitSeedingSession call
  |
  +-- processDraftsForCapture() [MODIFIED]
        |
        +-- [NEW] fidelity cross-check (D-01)
        |     loadCsvForPage() -> computeCsvDiff()
        |     for each draft: strain+qty match against CSV rows
        |     no CSV reading OR mismatch -> updateDraftStatus('needs_review',
        |                                    {needs_review_reason:'fidelity_cross_check_unverified'})
        |     CSV-verified seeding drafts -> escalate to session aggregation
        |     non-seeding verified drafts -> existing per-draft commit path
        |
        +-- [EXISTING 54.1] strain-gate (still runs for non-seeding shapes)
        |
        +-- [EXISTING] flipDraftToConfirmed + commit-router dispatch
              |
              +-- seeding drafts (session-shape): commit-seeding-session.js [EXTENDED]
              |     upsertGroupAsset (session name = 'inoc YYYY-MM-DD')
              |     [NEW] uploadAttachments(pageImagePaths) -> PATCH /api/asset/group/<id>
              |     children loop + seeding logs (unchanged)
              |     createGroupAssignmentLog (unchanged)
              |
              +-- non-seeding drafts: existing commit-* handlers (unchanged)

farmOS
  |
  +-- asset--group 'inoc YYYY-MM-DD'
  |     attributes.notes: provenance trailer
  |     relationships.files[]: N page image UUIDs
  |
  +-- log--activity (is_group_assignment=true)
  |     asset[]: N child block UUIDs
  |     group[]: [session group UUID]
  |
  +-- asset--fungi (child blocks) -- each held draft's block is NOT committed
  +-- log--seeding (per child block) -- held drafts produce NO seeding log

Held drafts remain in mushy DB as status='needs_review'.
Reconcile surface: open asset--group in farmOS -> see members + page images.
Held blocks are absent from farmOS members -> visible gap in the session view.
```

### Recommended Project Structure (additions only)

```
src/agents/alerter/
  scripts/
    backfill-notebook.js           -- [MODIFIED] fidelity gate + session aggregation
    build-backfill-receipt.js      -- [USED] computeCsvDiff promoted to commit gate
  src/farmos/commits/
    commit-seeding-session.js      -- [MODIFIED] add image upload to session group asset
  test/farmos/
    commit-seeding-session-with-images.test.js  -- [NEW] image upload path tests
  scripts/backfill-notebook.test.js  -- [MODIFIED] fidelity gate unit tests
```

### Pattern 1: Fidelity Cross-Check Gate

**What:** Before flipping a draft to `confirmed`, compare the extracted strain+qty against
the CSV rows for the page. Exact match = proceed. Mismatch or no CSV rows = hold.

**When to use:** All seeding drafts in bulk-backfill mode when `curatedStrains` is set.

**Example:**

```javascript
// Source: build-backfill-receipt.js computeCsvDiff (existing) + new gate in
// processDraftsForCapture (src/agents/alerter/scripts/backfill-notebook.js)

// At the top of the per-draft loop, after strain-gate, before flipDraftToConfirmed:
const csvRowsForPage = loadCsvForPage(csvPath, pageDate);
if (csvRowsForPage.length === 0) {
  // No CSV reading for this page -- hold everything (D-01).
  await db.updateDraftStatus(pool, draftId, 'needs_review', {
    needs_review_reason: 'fidelity_cross_check_no_csv',
  });
  entry = { draftId, log_type: logType, ok: 'held', reason: 'fidelity_cross_check_no_csv',
            strain_codes: [strain], asset_ids: [], log_ids: [] };
  commits.push(entry);
  continue;
}

const verified = isCsvVerified(draft, csvRowsForPage);  // see Pattern 2
if (!verified) {
  await db.updateDraftStatus(pool, draftId, 'needs_review', {
    needs_review_reason: 'fidelity_cross_check_unverified',
  });
  entry = { draftId, log_type: logType, ok: 'held', reason: 'fidelity_cross_check_unverified',
            strain_codes: [strain], asset_ids: [], log_ids: [] };
  commits.push(entry);
  continue;
}
// Verified -- proceed to flipDraftToConfirmed.
```

**The gate ONLY fires in bulk-backfill mode** (`opts.bulkBackfill === true`) and only when
a CSV path is available (`env.MUSHROOM_LOG_CSV`). Non-backfill live paths are unchanged.

### Pattern 2: CSV Verification Key

**What:** The CSV has columns `page_date`, `strain`, (and implicitly a count-per-strain by
counting rows). An extracted draft carries `draft_json.species_code` (or `species`/`strain`
fields normalized by `commit-router`'s `normalize()` call) plus `draft_json.block_name` for
seeding shapes.

**Exact match granularity (Claude's Discretion resolution):**

The simplest correct key is **strain code** (case-insensitive) AND **page date**. Quantity
matching against `computeCsvDiff` is at the aggregate level (hit count). Per-draft
verification should be: "is the extracted strain in the CSV set for this page, AND have we
not over-committed that strain's CSV count yet?"

Implementation: maintain a per-page mutable count budget copied from `strainSetFromCsv()`.
For each verified-strain draft, decrement the budget. When budget for that strain reaches
zero, additional drafts for the same strain on the same page are held (extra protection
against silent over-commit). Drafts on pages with no CSV rows are ALL held.

```javascript
// Source: pattern derived from build-backfill-receipt.js strainSetFromCsv()

function buildCsvBudget(csvRows) {
  // Map<strainUpper, remainingCount>
  const m = new Map();
  for (const r of csvRows) {
    const s = String(r.strain || '').toUpperCase();
    if (!s) continue;
    m.set(s, (m.get(s) || 0) + 1);
  }
  return m;
}

function consumeCsvBudget(budget, strainUpper) {
  const n = budget.get(strainUpper) || 0;
  if (n <= 0) return false;  // no budget remaining -> hold
  budget.set(strainUpper, n - 1);
  return true;
}
```

**Important:** the CSV budget is per-page, shared across all drafts from that page's
capture. It must be built once per page (outside the draft loop) and passed in.

**Non-seeding shapes (observation/harvest/activity/input):** these shapes do not carry a
strain code that maps onto a CSV row. D-01 says "hold everything unverified." For non-
seeding shapes on a page with CSV rows, there is no verification key available -- the
safest interpretation of D-01 is to hold these too when CSV rows exist for the page.
However, because ~half the pages have NO CSV at all, this would hold most non-seeding
activity/harvest logs unnecessarily. Planner's recommended resolution: hold non-seeding
only when the page HAS CSV rows (if no CSV, hold too -- consistent with "no CSV = hold
all"). Log the `needs_review_reason` as `fidelity_cross_check_no_seeding_match` to
distinguish from strain mismatch, making it easier to batch-release non-seeding held
drafts in a follow-up pass.

### Pattern 3: Session Routing for Backfill

**What:** Backfill currently emits one or more `seeding` drafts per page (one per block).
Each draft is individually dispatched through `processDraftsForCapture` -> `commit-seeding`
(the per-block handler). This bypasses `commit-seeding-session.js` entirely.

**Cleanest route (Claude's Discretion resolution):**

The cleanest route is NOT to change the extractor shape or draft schema. Instead, add a
**per-page session aggregation pass** inside `processDraftsForCapture` (or as a caller
wrapper) that:

1. Collects all CSV-verified seeding drafts from the page.
2. Constructs a synthesized `seeding_session` draft from them (same shape as an LLM-
   extracted seeding_session: `{ type: 'seeding_session', event_date, groups: [...],
   notes }`).
3. Calls `commit-seeding-session.js` ONCE with the synthesized draft.
4. Returns the session commit result attributed to all constituent draft IDs.

Why this route over alternatives:
- Changing `log_type` on existing drafts from `seeding` to `seeding_session` would
  require `updateDraftStatus` with `{log_type: 'seeding_session'}` (whitelisted) plus
  a `draft_json` rewrite to the session shape. This is more invasive.
- The synthesized draft approach keeps per-draft DB state intact (each seeding draft stays
  `confirmed`, the session is committed on their behalf). The session asset UUID then gets
  backfilled onto each draft's receipt entry.
- Alternatively: mark each `seeding` draft's `log_type` as `seeding_session` and rewrite
  `draft_json` to the groups shape before dispatch. This is equivalent but puts a complex
  transformation inside the loop.

**Preferred approach: aggregate-then-synthesize.** The aggregation is a pure in-memory
transform; no additional DB writes. `processDraftsForCapture` already has all the draft
objects. Group by `event_date` (all same-page backfill drafts share the same date from the
corpus_context) -- that IS the session boundary.

```javascript
// Source: new function in backfill-notebook.js

function aggregateSeedingDraftsIntoSessionShape(verifiedSeedingDrafts, pageDate) {
  // Groups by (parent_name, species) -- matches the seeding_session groups[] shape.
  const groupsMap = new Map();
  for (const draft of verifiedSeedingDrafts) {
    const dj = draft.draft_json || {};
    const parent = dj.parent_batch_name || dj.parent || 'NO_PARENT';
    const species = (dj.species_code || dj.species || dj.strain || '').toUpperCase();
    const key = `${parent}::${species}`;
    if (!groupsMap.has(key)) {
      groupsMap.set(key, { parent: { value: parent }, species: { value: species },
                           qty: { value: 0 }, child_block_names: { value: [] } });
    }
    const g = groupsMap.get(key);
    g.qty.value += dj.qty || 1;
    if (dj.block_name) g.child_block_names.value.push(dj.block_name);
  }
  return {
    type: 'seeding_session',
    event_date: pageDate,
    groups: Array.from(groupsMap.values()),
  };
}
```

**Session identity with D-04 (session != page):** The current backfill dispatches one
page at a time, and a page maps to one `dispatchPage` call. D-04 says a session can span
multiple pages. In the initial implementation, a page is the practical session boundary
(all blocks on the same page share the same session date). This is correct for most 2025
notebook pages. Cross-page sessions (one session filling two pages) would produce two
separate session group assets -- a known gap, documented as a deferred edge case. The
receipt should note this limitation.

### Pattern 4: Image Upload on Session Group Asset

**What:** After `upsertGroupAsset` returns a `sessionGroupId` in `commitSeedingSession`,
upload the page image(s) and PATCH the group asset to associate the file UUIDs.

**How farmOS associates files to assets (verified pattern from commit-observation.js):**
`uploadAttachments` POSTs bytes to `/api/file/file`, gets back file UUIDs, then the
caller passes `fileIds` to the asset/log creation. For an existing asset (already
upserted), a PATCH is needed.

**The extension point:**

```javascript
// In commit-seeding-session.js, after upsertGroupAsset succeeds:
// Source: pattern from commit-observation.js files.uploadAttachments usage

const files = require('../files');

// attachment_paths comes from ctx (same mechanism as commit-observation).
// For backfill, ctx must carry the page path(s) for the session.
const attachPaths = (ctx && ctx.sessionPagePaths) || [];
let uploadedFileIds = [];
if (attachPaths.length > 0) {
  const upRes = await files.uploadAttachments(client, attachPaths,
    { logger: ctx && ctx.logger });
  uploadedFileIds = upRes.fileIds || [];
  // Best-effort: upload failure does NOT abort the session commit (mirrors D-05a).
  if (upRes.failed && upRes.failed.length > 0 && ctx && ctx.logger) {
    ctx.logger.warn(`[commit-seeding-session] ${upRes.failed.length} page image(s) failed`);
  }
}

// PATCH the group asset to bind the file UUIDs.
if (uploadedFileIds.length > 0) {
  await patchGroupAssetFiles(client, sessionGroupId, uploadedFileIds);
}
```

**PATCH to bind files to an asset--group (farmOS JSON:API):**

```javascript
// Source: farmOS JSON:API PATCH relationship pattern (same pattern used by assets.js)

async function patchGroupAssetFiles(client, assetId, fileIds) {
  const payload = {
    data: {
      type: 'asset--group',
      id: assetId,
      relationships: {
        file: {
          data: fileIds.map((id) => ({ type: 'file--file', id })),
        },
      },
    },
  };
  return client.patch('/api/asset/group/' + assetId, payload);
}
```

**Prerequisite (already verified):** farmOS private-files bind-mount and `file_private_path`
are live on both dev `:18080` and prod `:8082` per the canonical reference
`.planning/notes/2026-05-25-pointer-farmos-private-files-SHIPPED.md`. No infra change
needed. [ASSUMED: the PATCH relationship update for files on an asset--group works with
the same `/api/asset/group/<id>` endpoint as a standard JSON:API PATCH; needs smoke
verification against dev farmOS since it has not been tested specifically for groups.]

**ctx.sessionPagePaths threading:** The backfill harness must pass page paths to the
commit context. The existing `ctx` object passed to commit handlers is created in
`commit-router.commit()`. For the session aggregation path, the synthesized draft
dispatcher needs to enrich `ctx` with `sessionPagePaths: [page1, page2, ...]` before
calling `commitSeedingSession`. This is a minimal ctx extension.

### Pattern 5: Needs_review Rendering in the Session View (F2 surface)

**What:** D-02 says held entries must surface inside the session view. The key insight is
that `needs_review` is a MUSHY DB state only -- farmOS never sees held drafts. From
farmOS's perspective, a held entry simply does not appear as a committed asset/log.

**How the F2 session view works without code changes:**

The farmOS `asset--group` page for `inoc YYYY-MM-DD` shows:
1. The attached page image(s) (D-03) -- the physical notebook page.
2. The membership log -- the list of child block assets that WERE committed.
3. Gaps = held entries (blocks not appearing in members).

A farmer opens the session group, sees the notebook page image, counts the blocks on the
page, compares to the farmOS members list. Missing members are the held drafts. This is
the reconcile surface -- no custom UI needed.

**The one thing that DOES need to be in farmOS to make this useful:** the session group
asset itself. If a page has ALL drafts held (e.g., all entries mismatch the CSV), the
session group asset should still be created (with the page image attached) so the farmer
has a named placeholder. The membership log may have zero children in this case.

**Queryability of held drafts for operator audit:**

```sql
-- Find all held fidelity drafts for a given page date:
SELECT id, log_type, needs_review_reason, draft_json
FROM signal_draft
WHERE status = 'needs_review'
  AND needs_review_reason LIKE 'fidelity_cross_check%'
  AND draft_json->>'event_date' = '2025-02-01';
```

This is a mushy-DB query, not a farmOS query. The planner should include an operator
query snippet in the runbook.

### Pattern 6: Non-Seeding Shapes and Session Membership

**Claude's Discretion resolution -- non-seeding shapes on a session:**

For 55b scope: non-seeding shapes (observation/harvest/activity/input) on the same page
as seeding entries do NOT need to be wired into the session group. Reasons:
1. These shapes are rare in the 2025 notebook corpus (mostly seeding pages).
2. The `asset--group` membership pattern in farmOS uses `is_group_assignment` logs that
   reference `asset--fungi` IDs. Observations/harvests/activities/inputs land on
   existing assets (not creating new ones in backfill context), so their assets are
   already implicitly "in" the session via the existing seeding-membership log.
3. Wiring non-seeding shapes would require creating membership logs for assets created
   by different commit handlers, massively complicating the aggregation pass.

**Decision for 55b:** non-seeding shapes follow the existing per-draft commit path with
the fidelity hold applied. If their draft is held, it shows as missing from farmOS. If
committed, it lands on the relevant asset. No additional session membership wiring needed.

### Pattern 7: GA1 Isolation Pre-flight (Re-smoke)

The re-smoke reuses the exact isolation discipline from `55-FULL-CORPUS-RUNBOOK.md`:
- Option A (default): throwaway postgres on port 5433.
- All four common pre-flight assertions (dev :18080 reachable, FARMOS_URL clean,
  ANTHROPIC_API_KEY set, Jest suite green).
- 5-page paid smoke before any full run.

**Smoke set selection (Claude's Discretion resolution):**

Select pages that HAVE CSV ground truth and include the known failure modes:
- IMG_3775 (02-01) -- mode 1 (misread-fail: LIMA->LIM, POY->OYS)
- IMG_3776 (02-04) -- mode 2 (silent misattribution: POY->KOY)
- IMG_3778 (02-20) -- mode 1 (misread-fail: CAZ->CAR)
- IMG_3782 (04-06) -- mode 3 (under-capture: 4 SHI missed)
- IMG_3777 (no CSV) -- mode 0 (no ground truth; tests the "hold all" path)

This 5-page set exercises all three failure modes plus the no-CSV case. It is the
regression guard for the fidelity gate.

**Re-smoke success criteria:**
- IMG_3776 drafts: the POY entries are held (not committed as KOY). Commit log shows
  `ok: 'held', reason: 'fidelity_cross_check_unverified'` for the 4 POY entries.
- IMG_3775: 7 entries held (LIMA x4 + POY x3), 17 hits committed.
- IMG_3777: all entries held with `reason: 'fidelity_cross_check_no_csv'`.
- Session group assets created for each page with the page image attached.
- Receipt shows held count > 0 and `fidelity_cross_check_*` reasons.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CSV diff logic | custom comparator | `computeCsvDiff` + `strainSetFromCsv` (build-backfill-receipt.js) | Already handles case-insensitive strain match + hit/miss/extra counting; exact reuse |
| Session group upsert | ad-hoc farmOS POST | `groupAssets.upsertGroupAsset` | Content-addressable by name; LRU cache; handles existing group; collision suffix (`#N`) logic for same-date sessions |
| File upload | raw multipart | `files.uploadAttachments` | Handles missing-file skip, 30s timeout, error surfacing; private-files already live |
| Hold state write | direct SQL | `updateDraftStatus(pool, id, 'needs_review', { needs_review_reason: ... })` | Whitelisted; transactional; same path as 54.1 strain-gate |
| Membership log | custom PATCH relationship | `activityLogs.createGroupAssignmentLog` | `is_group_assignment=true` is the farmOS canonical pattern; already implemented |

**Key insight:** Every primitive for this phase is already in the codebase. The work is
wiring, not building.

---

## Common Pitfalls

### Pitfall 1: Per-page CSV budget not reset between pages

**What goes wrong:** A shared `csvBudget` object is reused across pages. A KOY on page 1
consumes the KOY budget from page 1's CSV rows, but the budget for page 2 was never
loaded. Result: KOY drafts on page 2 are all held even if the CSV for page 2 has KOY.

**Why it happens:** The budget is built from `loadCsvForPage(csvPath, pageDate)`, which
must be called per-page with the correct `pageDate`. If `pageDate` is null (not resolved
from the fixture directory), the CSV returns [] and all drafts are held (correct per D-01).

**How to avoid:** Build the `csvBudget` once per page, inside the page loop, from
`loadCsvForPage(csvPath, pageDate)`. Pass it into `processDraftsForCapture` alongside the
CSV rows.

**Warning signs:** Receipt shows 100% held on pages that should have hits.

### Pitfall 2: Held draft treated as a commit entry that counts toward the receipt aggregate

**What goes wrong:** A held draft has `ok: 'held'` and `asset_ids: []`. If
`computeAggregate` counts it as an `ok === false` "failed" entry rather than a distinct
hold bucket, the receipt shows inflated failure counts.

**Why it happens:** `computePerShapeStats` already handles `ok === 'held'` as a distinct
bucket (lines 373-376 in `build-backfill-receipt.js`). If the new hold entries use
`ok: 'held'` consistently, the stats are correct. If any path returns `ok: false` for a
held draft, the receipt mixes holds with failures.

**How to avoid:** Use `ok: 'held'` (string) consistently for all `needs_review` hold
entries. The existing stats infrastructure already handles this.

### Pitfall 3: Session group created but page image PATCH fails silently

**What goes wrong:** `patchGroupAssetFiles` returns non-ok but the error is swallowed.
The session group exists in farmOS but has no image attached. The F2 surface is broken --
a farmer opens the session and sees no notebook page.

**Why it happens:** Best-effort semantics (mirrors D-05a from commit-observation). If the
PATCH is silently no-op on failure, the session commits but the image is missing.

**How to avoid:** Surface the image upload failure in the commit result (same pattern as
`attachments_failed` in `commitObservation`). The receipt should show
`session_image_upload_failed: true` when this happens. Do NOT abort the session commit on
image failure.

**Warning signs:** Session assets in farmOS have empty file relationships. Receipt shows
`attachments_failed` on session commits.

### Pitfall 4: Synthesized seeding_session draft bypasses rollback

**What goes wrong:** The synthesized `seeding_session` draft is an in-memory object, not
a DB row. If the commit fails mid-way (e.g., child N of M fails), `_cleanup` in
`commitSeedingSession` rolls back the farmOS side but there is no draft row to flip back
to `needs_review`.

**Why it happens:** The real seeding drafts are in `status='confirmed'` when the session
commit is attempted. A partial session failure leaves those drafts confirmed but
uncommitted.

**How to avoid:** On session commit failure, flip the constituent seeding draft IDs back
to `needs_review` with `reason: 'session_commit_failed'`. The aggregation pass knows the
constituent draft IDs; pass them into the commit context so the cleanup path can reach
them.

### Pitfall 5: Session name collision with existing live sessions

**What goes wrong:** Backfill for a page dated `2025-02-01` creates session name
`inoc 2025-02-01`. If a live inoc session from a Signal message also used this date (a
May 22-style multi-parent session), the `_resolveSessionName` collision suffix logic
kicks in and creates `inoc 2025-02-01 #2`. Both are valid but separate sessions in farmOS.

**Why it happens:** `_resolveSessionName` checks whether the existing session's notes
trailer matches the current draft ID. A live session was created by a different draft ID,
so it advances to `#2`.

**How to avoid:** This is correct behavior. The collision suffix is by design. Document in
the runbook that backfill sessions will be named with `#N` suffix when live sessions for
the same date already exist. The receipt should surface the session name used.

### Pitfall 6: Non-seeding shapes held with "no seeding match" reason block future auto-release

**What goes wrong:** Activity/observation/harvest/input drafts on pages with CSV rows are
held as `fidelity_cross_check_no_seeding_match`. These could be valid commits (CSV doesn't
cover non-seeding shapes). A follow-up bulk-release pass might inadvertently release them
alongside incorrectly held seeding drafts.

**How to avoid:** Use distinct `needs_review_reason` values:
- `fidelity_cross_check_no_csv` -- page has no CSV rows at all
- `fidelity_cross_check_unverified` -- seeding draft doesn't match CSV (strain/qty)
- `fidelity_cross_check_nonseeding` -- non-seeding shape on CSV-covered page (safe to release after seeding reconcile)

This tripartite reason set makes batch-release queries unambiguous.

---

## Code Examples

### Verified CSV-budget-based hold check

```javascript
// Source: derived from build-backfill-receipt.js strainSetFromCsv (existing)
// This is NEW code for processDraftsForCapture in backfill-notebook.js

// Before the draft loop (per page):
const pageDate = page.event_date || page.pageDate ||
  pageDateForImage(path.basename(pagePath));
const csvRowsForPage = csvPath ? loadCsvForPage(csvPath, pageDate) : [];
const csvBudget = buildCsvBudget(csvRowsForPage);  // Map<strainUpper, count>

// Inside the draft loop, after strain-gate, before flipDraftToConfirmed:
const dj = (draft && draft.draft_json) || {};
const logType = draft.log_type;

if (logType === 'seeding' || logType === 'seeding_session') {
  const strain = String(
    dj.species_code || dj.species || dj.strain || dj.fungi_type || ''
  ).toUpperCase();

  if (csvRowsForPage.length === 0) {
    // No CSV for this page -- hold (D-01).
    await db.updateDraftStatus(pool, draftId, 'needs_review',
      { needs_review_reason: 'fidelity_cross_check_no_csv' });
    // ... build held entry, push to commits, continue
    continue;
  }

  if (!strain || !consumeCsvBudget(csvBudget, strain)) {
    // Strain not in CSV, or CSV budget exhausted for this strain -- hold (D-01).
    await db.updateDraftStatus(pool, draftId, 'needs_review',
      { needs_review_reason: 'fidelity_cross_check_unverified' });
    // ... build held entry, push to commits, continue
    continue;
  }
  // CSV-verified -- fall through to flipDraftToConfirmed.

} else {
  // Non-seeding shape.
  if (csvRowsForPage.length === 0) {
    // No CSV for page -- hold all shapes (D-01 conservative).
    await db.updateDraftStatus(pool, draftId, 'needs_review',
      { needs_review_reason: 'fidelity_cross_check_no_csv' });
    continue;
  }
  // Non-seeding on CSV-covered page -- hold with distinct reason.
  await db.updateDraftStatus(pool, draftId, 'needs_review',
    { needs_review_reason: 'fidelity_cross_check_nonseeding' });
  continue;
}
```

### Session group asset file attachment (PATCH)

```javascript
// Source: files.js uploadAttachments (existing) + new patchGroupAssetFiles in groupAssets.js

async function patchGroupAssetFiles(client, assetId, fileIds) {
  if (!fileIds || fileIds.length === 0) return { ok: true, skipped: true };
  const payload = {
    data: {
      type: 'asset--group',
      id: assetId,
      relationships: {
        file: {
          data: fileIds.map((id) => ({ type: 'file--file', id })),
        },
      },
    },
  };
  const r = await client.patch('/api/asset/group/' + assetId, payload);
  if (!r.ok) {
    return { ok: false, reason: 'http_' + (r.status || 'network'), http_status: r.status };
  }
  return { ok: true, http_status: r.status };
}
```

### Session aggregation from verified seeding drafts

```javascript
// Source: new helper in backfill-notebook.js
// Converts a flat list of verified 'seeding' drafts (same page/date) into a
// seeding_session draft_json for commit-seeding-session.js

function aggregateSeedingDraftsToSessionJson(verifiedDrafts, pageDate) {
  const groupsMap = new Map();
  for (const draft of verifiedDrafts) {
    const dj = draft.draft_json || {};
    const parent = dj.parent_batch_name || dj.parent || 'NO_PARENT';
    const species = String(
      dj.species_code || dj.species || dj.strain || dj.fungi_type || ''
    ).toUpperCase();
    const key = parent + '::' + species;
    if (!groupsMap.has(key)) {
      groupsMap.set(key, {
        parent: { value: parent },
        species: { value: species },
        qty: { value: 0 },
        child_block_names: { value: [] },
      });
    }
    const g = groupsMap.get(key);
    g.qty.value += (dj.qty || 1);
    if (dj.block_name) g.child_block_names.value.push(dj.block_name);
  }
  return {
    type: 'seeding_session',
    event_date: pageDate,
    groups: Array.from(groupsMap.values()),
  };
}
```

---

## Runtime State Inventory

This is a backfill extension, not a rename/refactor. No runtime state inventory needed.

The one relevant live-state item: the 2026-06-07 audit set (99 assets + 98 logs) is
already in prod farmOS and includes misattributed entries (POY-as-KOY). This is
explicitly deferred per CONTEXT.md ("Prod cleanup of the 2026-06-07 audit set").
Phase 55b does not touch those records.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js / npm | harness scripts | Yes (alerter is active) | see package.json | -- |
| Dev farmOS :18080 | session group smoke | Yes (per memory note) | running | -- |
| Throwaway postgres :5433 | GA1 isolation | Yes (Option A from runbook) | docker pull postgres:14 | Option B (stop alerter) |
| ANTHROPIC_API_KEY | paid smoke | Yes (operator-managed) | -- | -- |
| mushroom_log.csv | fidelity gate | Yes (at `/mnt/slime-kingdom/shared/mushdatadump/mushroom_log.csv`) | -- | No CSV = all held (D-01) |
| Corpus JPEG dir | backfill pages | Yes (at `/mnt/slime-kingdom/shared/mushdatadump/jpeg/`) | 73 pages | -- |
| farmOS `farm_group` module | asset--group | Yes (enabled farmos commit 1857037, confirmed by Phase 52) | -- | -- |

**Missing dependencies with no fallback:** None.

**Note on patchGroupAssetFiles:** The PATCH-to-associate-files pattern for `asset--group`
has not been exercised in this codebase. `commit-observation.js` passes `fileIds` to
`logs.createLog()` which handles file relationship inline on creation. For an existing
group asset, a PATCH is needed. This must be verified in the smoke before the full run.
[ASSUMED: farmOS JSON:API PATCH with `relationships.file` works on `asset--group`; needs
dev smoke confirmation.]

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | Jest (existing; 1383 tests green as of 2026-06-09) |
| Config file | `src/agents/alerter/package.json` (jest config inline) |
| Quick run command | `cd src/agents/alerter && npx jest --testPathPattern=backfill` |
| Full suite command | `cd src/agents/alerter && npx jest --passWithNoTests` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FIDELITY-01 | CSV cross-check holds mismatched strain | unit | `npx jest scripts/backfill-notebook.test.js -t "fidelity"` | Wave 0 gap |
| FIDELITY-01 | CSV cross-check holds when no CSV rows | unit | `npx jest scripts/backfill-notebook.test.js -t "no_csv"` | Wave 0 gap |
| FIDELITY-01 | CSV-verified draft proceeds to commit | unit | `npx jest scripts/backfill-notebook.test.js -t "csv_verified"` | Wave 0 gap |
| FIDELITY-02 | `needs_review_reason` = `fidelity_cross_check_unverified` on mismatch | unit | `npx jest scripts/backfill-notebook.test.js -t "hold_reason"` | Wave 0 gap |
| FIDELITY-02 | `needs_review_reason` = `fidelity_cross_check_no_csv` on no-CSV page | unit | `npx jest scripts/backfill-notebook.test.js -t "no_csv_reason"` | Wave 0 gap |
| SESSION-01 | aggregateSeedingDraftsToSessionJson groups by parent+species | unit | `npx jest scripts/backfill-notebook.test.js -t "aggregate"` | Wave 0 gap |
| SESSION-02 | commitSeedingSession calls uploadAttachments when ctx.sessionPagePaths provided | unit | `npx jest test/farmos/commit-seeding-session.test.js -t "image"` | Wave 0 gap |
| SESSION-02 | patchGroupAssetFiles sends correct JSON:API PATCH payload | unit | `npx jest test/farmos/commit-seeding-session.test.js -t "patch_files"` | Wave 0 gap |
| SESSION-03 | held drafts produce no farmOS assets (absent from membership log) | integration | smoke against dev :18080 (manual) | manual |
| SMOKE-01 | 5-page paid smoke receipt shows held entries for IMG_3776 | smoke | manual (operator) | manual |

### Sampling Rate

- Per task commit: `cd src/agents/alerter && npx jest --testPathPattern="backfill|commit-seeding-session" --passWithNoTests`
- Per wave merge: `cd src/agents/alerter && npx jest --passWithNoTests`
- Phase gate: full suite green before re-smoke, re-smoke green before promoting to full run

### Wave 0 Gaps

The existing `backfill-notebook.test.js` and `commit-seeding-session.test.js` have no
fidelity cross-check or image-upload coverage. The following test additions are needed
before implementation:

- [ ] `scripts/backfill-notebook.test.js` -- add `processDraftsForCapture` tests with
  mocked `loadCsvForPage`: (a) no-CSV holds all, (b) CSV-match commits, (c) CSV-mismatch
  holds, (d) budget-exhausted holds
- [ ] `test/farmos/commit-seeding-session.test.js` -- add: (a) `patchGroupAssetFiles`
  payload shape, (b) upload then patch path, (c) image upload failure is non-fatal
- [ ] `scripts/backfill-notebook.test.js` -- add `aggregateSeedingDraftsToSessionJson`
  unit tests: (a) single parent+species, (b) multi-parent, (c) block_names array

---

## Security Domain

No security surface changes. The fidelity gate adds a DB write (`updateDraftStatus`) and
a farmOS PATCH -- both are existing authenticated paths. No new inputs from external
sources. No new env vars exposed. No new secrets.

ASVS V5 (Input Validation) already applies to the existing `commit-seeding-session.js`
parameter validation (phase shape guard on entry). The CSV budget logic operates on
pre-parsed CSV content from a trusted local file.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| CSV diff in receipt only (post-commit) | CSV diff as pre-commit gate (hold-or-proceed) | Phase 55b | Catches mode-2 silent misattribution before farmOS write |
| Backfill emits plain `seeding` drafts (ungrouped) | Backfill aggregates seeding drafts per session into `seeding_session` shape | Phase 55b | Groups blocks under session group asset; F2 surface |
| No page image on session asset | Session group asset carries N page image(s) as attachments | Phase 55b | Enables 1:1 notebook reconcile in farmOS |
| Hold via Signal-batch confirm (54.1 pattern) | Hold visible in farmOS session view (F2) | Phase 55b (D-02) | Scales to corpus-level hold volume |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | PATCH with `relationships.file` on an existing `asset--group` associates files (farmOS JSON:API standard pattern) | Pattern 4, Environment Availability | Session has no image attached; F2 surface broken; smoke catches this |
| A2 | The `groups` shape in a synthesized `seeding_session` draft_json (built from flat `seeding` drafts) is correctly normalized by `normalize()` in `commit-router` before dispatch | Pattern 3 | Session commit fails with `invalid_seeding_session`; caught in hermetic tests |
| A3 | `event_date` for backfill seeding drafts is uniformly the notebook page date (from corpus_context YYYY-MM-DD), making it a valid session boundary | Pattern 3 | Incorrect grouping; blocks land in wrong session |
| A4 | Non-seeding shapes (observation/harvest/input/activity) in the 2025 notebook corpus are rare enough that holding them all (D-01) does not materially affect the re-smoke pass criteria | Pattern 3, Pitfall 6 | Higher-than-expected hold count; does not affect correctness |

---

## Open Questions (RESOLVED)

1. **Does `patchGroupAssetFiles` work for `asset--group`?** (A1 -- ASSUMED, MEDIUM confidence)
   - **RESOLVED via Wave 0 gate:** verified by the blocking dev-smoke probe in 55B-01 Task 4 (PATCH `/api/asset/group/<id>` with `relationships.file` against dev `:18080`) BEFORE any image-attach implementation (55B-03) may run; fallback = two-step create -> upload -> associate. The assumption stays honest (verified at execution time, not research time), but the resolution mechanism is planned and gating.
   - What we know: `commit-observation.js` associates files via `logs.createLog(..., fileIds)` which handles file relationship on creation, not PATCH.
   - What's unclear: Whether farmOS's `asset--group` JSON:API endpoint accepts PATCH with `relationships.file` for an already-created asset. The pattern is standard JSON:API but has not been tested specifically for groups in this codebase.
   - Recommendation: Add a smoke probe against dev `:18080` in Wave 0 (before implementation commit) to verify: `curl -X PATCH /api/asset/group/<id> -d '{"data":{"type":"asset--group","id":"<id>","relationships":{"file":{"data":[{"type":"file--file","id":"<fid>"}]}}}}'`. If it fails, the alternative is to set `file` in the POST payload at group creation time (before image upload, so this would require two-step: create group -> upload files -> PATCH).

2. **What is the correct `parent_batch_name` / `parent` field in backfill seeding drafts?**
   - **RESOLVED:** confirmed during planning against `commit-seeding-session.js:153-156` -- the consumer reads `g.parent.value` / `g.species.value` / `g.child_block_names.value`, so aggregation maps `parent_batch_name || parent -> group.parent.value` (and `species -> group.species.value`).
   - What we know: `aggregateSeedingDraftsToSessionJson` groups by `dj.parent_batch_name || dj.parent`. The actual field name from the extractor for backfill seeding drafts is resolved by `normalize()` -- see `src/farmos/commits/normalize.js`.
   - What's unclear: Whether backfill `seeding` draft_json uses `parent_batch_name` or `parent` or `species` as the group key. This matters for correct session aggregation.
   - Recommendation: Read `normalize.js` before writing the aggregation (planner action: read that file as part of Plan 1 task discovery).

3. **Smoke page count: 5 or 10?**
   - **RESOLVED:** 5 pages is sufficient; IMG_3775, 3776, 3778, 3782, 3777 cover all three failure modes.
   - What we know: The 5-page paid smoke is from the existing GA1 runbook discipline. The 10-page prod audit was the trigger for this phase.
   - What's unclear: Whether 5 pages is sufficient for the re-smoke to catch fidelity regressions.
   - Recommendation: 5 pages is sufficient; the 5 selected (see Pattern 7) cover all three failure modes. Use `--limit=5 --resume-from=IMG_3775.jpg` to reproducibly select them.

---

## Sources

### Primary (HIGH confidence)

- `src/agents/alerter/scripts/backfill-notebook.js` -- read directly; complete understanding of dispatch loop, strain-gate pattern, hold path, commit context
- `src/agents/alerter/scripts/build-backfill-receipt.js` -- read directly; `computeCsvDiff`, `strainSetFromCsv`, `buildCsvBudget` pattern, per-page CSV loading
- `src/agents/alerter/src/farmos/commits/commit-seeding-session.js` -- read directly; session group lifecycle, rollback, membership log creation
- `src/agents/alerter/src/farmos/commits/commit-observation.js` -- read directly; canonical attachment upload pattern (Phase 40 D-05a/D-05b)
- `src/agents/alerter/src/farmos/files.js` -- read directly; `uploadAttachments` implementation
- `src/agents/alerter/src/farmos/groupAssets.js` -- read directly; `upsertGroupAsset`, `patchGroupAssetFiles` target module
- `src/agents/alerter/src/farmos/activityLogs.js` -- read directly; `createGroupAssignmentLog` shape
- `src/agents/alerter/src/farmos/commits/commit-router.js` -- read directly; dispatch map
- `src/agents/alerter/src/extraction/extraction-db.js` -- read directly; `updateDraftStatus`, `UPDATE_EXTRAS_WHITELIST`
- `.planning/phases/55B-.../55B-CONTEXT.md` -- read directly; D-01 through D-04 locked decisions
- `.planning/notes/2026-06-07-prod-smoke-fidelity-audit.md` -- read directly; three failure modes, CSV-is-not-authoritative correction
- `.planning/todos/pending/2026-06-07-backfill-audit-findings.md` -- read directly; F1/F2 converged design
- `.planning/phases/55-full-corpus-run-receipt/55-FULL-CORPUS-RUNBOOK.md` -- read directly; GA1 isolation pre-flight
- `.planning/notes/2026-05-24-session-as-asset-group-design.md` -- read directly; asset--group design rationale, farmOS team questions

### Secondary (MEDIUM confidence)

- Jest test suite run: 1383 tests passing (87 suites) -- confirms baseline test health
- `find` + `grep` across codebase -- confirms no existing fidelity gate or session image upload code

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all code read directly from source; no external packages
- Architecture: HIGH -- all patterns derived from existing implementations in the codebase
- Pitfalls: HIGH -- derived from reading actual code paths and the prod audit findings
- One ASSUMED item (A1): patchGroupAssetFiles for asset--group needs smoke verification

**Research date:** 2026-06-09
**Valid until:** 2026-07-09 (stable Node.js codebase; no external dependency changes)
