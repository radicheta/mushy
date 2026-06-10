---
phase: 55B-fidelity-corpus-unblock
plan: 02
type: execute
wave: 1
depends_on: ["55B-01"]
files_modified:
  - src/agents/alerter/scripts/backfill-notebook.js
autonomous: true
requirements: [FIDELITY-01, FIDELITY-02]
must_haves:
  truths:
    - "A backfill seeding draft whose strain is not in the page's CSV reading is HELD, never committed"
    - "A backfill draft on a page with no CSV reading at all is HELD"
    - "Only exact-CSV-verified seeding drafts proceed to flipDraftToConfirmed"
    - "Held drafts use ok:'held' (string) so the receipt counts them as held, not failed"
    - "Three distinct needs_review_reason values disambiguate no-csv / unverified / nonseeding holds"
  artifacts:
    - path: "src/agents/alerter/scripts/backfill-notebook.js"
      provides: "buildCsvBudget, consumeCsvBudget, fidelity gate in processDraftsForCapture"
      contains: "fidelity_cross_check"
  key_links:
    - from: "processDraftsForCapture fidelity gate"
      to: "db.updateDraftStatus(pool, draftId, 'needs_review', ...)"
      via: "needs_review_reason fidelity_cross_check_*"
      pattern: "needs_review.*fidelity_cross_check"
    - from: "processDraftsForCapture"
      to: "loadCsvForPage / strainSetFromCsv"
      via: "require build-backfill-receipt"
      pattern: "require.*build-backfill-receipt"
---

<objective>
Promote the existing per-page CSV diff from a receipt-only reporter to a COMMIT-TIME
gate (D-01): inside `processDraftsForCapture`, after the 54.1 strain-gate and before
`flipDraftToConfirmed`, hold every draft that is not exact-verified against the page's
CSV reading. This is the catch for the 2026-06-07 mode-2 silent misattribution
(POY committed as KOY with no error).

Purpose: Nothing unverified reaches farmOS. A committed wrong strain cannot be
upsert-fixed (Phase 51 converges names, not fungi_type), so the gate is the only
durable defense. The CSV is a fallible 2nd interpretation, so disagreement HOLDS
(needs_review) — never hard-rejects, never silently commits.
Output: buildCsvBudget/consumeCsvBudget helpers + the three-branch fidelity hold gate;
turns the Plan 01 RED fidelity/budget scaffolds GREEN.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-CONTEXT.md
@.planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-RESEARCH.md
@.planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-PATTERNS.md

<interfaces>
Confirmed against source (2026-06-09):

scripts/backfill-notebook.js:
- processDraftsForCapture signature line 292-295; destructured params include
  curatedStrains. Add `csvPath` + `pageDate` (or pre-loaded `csvRowsForPage` + `csvBudget`)
  the same way curatedStrains was added.
- Strain-gate hold path lines 343-376 — the EXACT pattern to copy. New gate slots
  AFTER line 376, BEFORE flipDraftToConfirmed (line 380+).
- flipDraftToConfirmed lines 253-261 (sets needs_review_reason 'bulk_backfill_santi').
- Held entry shape (copy from strain-gate lines 360-367): { draftId, log_type, ok:'held',
  reason, strain_codes, block_name, asset_ids:[], log_ids:[] }.
- Single call site in main() at line 748; csvPath already resolved at line 772
  (env.MUSHROOM_LOG_CSV || '/mnt/slime-kingdom/shared/mushdatadump/mushroom_log.csv')
  inside the receipt block — thread it (and pageDate) into the processDraftsForCapture call.

build-backfill-receipt.js exports (lines 531-546): loadCsvForPage, strainSetFromCsv,
computeCsvDiff, pageDateForImage. strainSetFromCsv (lines 77-85) builds Map<strainUpper,count>;
loadCsvForPage(csvPath, pageDate) filters rows by r.page_date === pageDate;
pageDateForImage(basename) resolves the page date. computePerShapeStats lines 373-378
already buckets `c.ok === 'held'` distinctly from failed.

extraction-db.updateDraftStatus(pool, id, 'needs_review', { needs_review_reason }) —
needs_review_reason is whitelisted (strain-gate already uses it).
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: buildCsvBudget + consumeCsvBudget helpers (turn budget scaffold green)</name>
  <files>src/agents/alerter/scripts/backfill-notebook.js</files>
  <read_first>
    - src/agents/alerter/scripts/backfill-notebook.js (the file being modified — module-level requires + export block line 822 region)
    - src/agents/alerter/scripts/build-backfill-receipt.js (analog: strainSetFromCsv lines 77-85 — copy the Map construction, .toUpperCase() + `|| ''` null-guard + empty-strain skip exactly)
    - src/agents/alerter/scripts/backfill-notebook.test.js (the RED 'buildCsvBudget / consumeCsvBudget' describe from Plan 01 — the contract to satisfy)
  </read_first>
  <behavior>
    - buildCsvBudget([{strain:'POY'},{strain:'poy'},{strain:''},{strain:'SHI'}]) returns Map { 'POY' => 2, 'SHI' => 1 } (uppercased, empty skipped).
    - consumeCsvBudget(map, 'POY') returns true and decrements POY to 1; a 3rd consume of POY returns false (budget exhausted).
    - consumeCsvBudget(map, 'UNKNOWN') returns false (no budget).
  </behavior>
  <action>
    Add `buildCsvBudget(csvRows)` (rename+reuse of strainSetFromCsv: Map of uppercased
    strain -> count, skip empty) and `consumeCsvBudget(budget, strainUpper)` (returns false
    when remaining <= 0, else decrement-and-return-true) to backfill-notebook.js. Export
    both in module.exports so the Plan 01 tests can require them.
  </action>
  <verify>
    <automated>cd src/agents/alerter && npx jest scripts/backfill-notebook.test.js -t "buildCsvBudget"</automated>
  </verify>
  <acceptance_criteria>
    - `npx jest scripts/backfill-notebook.test.js -t "buildCsvBudget"` GREEN.
    - buildCsvBudget + consumeCsvBudget exported from backfill-notebook.js.
    - consumeCsvBudget returns false at budget 0 (over-commit protection).
  </acceptance_criteria>
  <done>Budget helpers green; decrement-on-match semantics proven.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Fidelity hold gate in processDraftsForCapture (3 branches)</name>
  <files>src/agents/alerter/scripts/backfill-notebook.js</files>
  <read_first>
    - src/agents/alerter/scripts/backfill-notebook.js (the file being modified — strain-gate lines 343-376 to copy the hold shape; flipDraftToConfirmed lines 253-261; processDraftsForCapture signature line 292; main() call site line 748 + csvPath at line 772)
    - src/agents/alerter/scripts/build-backfill-receipt.js (loadCsvForPage + pageDateForImage to resolve the page's CSV rows; `ok === 'held'` bucket lines 373-378)
    - src/agents/alerter/scripts/backfill-notebook.test.js (the RED 'processDraftsForCapture (fidelity cross-check)' describe from Plan 01 — the contract)
    - .planning/phases/55B-*/55B-RESEARCH.md ("Verified CSV-budget-based hold check" Code Example — the three-branch logic)
  </read_first>
  <behavior>
    - Page has NO CSV rows -> EVERY draft (seeding or not) held with needs_review_reason 'fidelity_cross_check_no_csv', entry.ok==='held', router.commit NOT called.
    - Seeding draft whose strain IS in budget -> consume budget, fall through to flipDraftToConfirmed + router.commit (no needs_review write).
    - Seeding draft whose strain NOT in budget (or budget exhausted) -> held with 'fidelity_cross_check_unverified'.
    - Non-seeding draft on a CSV-covered page -> held with 'fidelity_cross_check_nonseeding'.
  </behavior>
  <action>
    Extend processDraftsForCapture's destructured params with `csvPath` and `pageDate`
    (mirroring how curatedStrains was added — no other caller exists). Before the draft
    loop, resolve per-page CSV once: `csvRowsForPage = csvPath ? loadCsvForPage(csvPath, pageDate) : []`
    and `csvBudget = buildCsvBudget(csvRowsForPage)`. Inside the loop, AFTER the 54.1
    strain-gate block (after line 376) and BEFORE the flipDraftToConfirmed call, insert
    the gate, ONLY when `opts.bulkBackfill === true`. Three branches per RESEARCH Code
    Example: (a) csvRowsForPage.length===0 -> hold all with reason 'fidelity_cross_check_no_csv';
    (b) seeding/seeding_session draft -> resolve strain via
    `dj.species_code || dj.species || dj.strain || dj.fungi_type` uppercased; if strain
    falsy OR !consumeCsvBudget(csvBudget, strain) -> hold with 'fidelity_cross_check_unverified',
    else fall through to commit; (c) non-seeding draft on CSV-covered page -> hold with
    'fidelity_cross_check_nonseeding'. Every hold MUST: call
    db.updateDraftStatus(pool, draftId, 'needs_review', { needs_review_reason: <reason> }),
    build the held entry with `ok:'held'` (string, NOT false) + the appropriate reason +
    strain_codes ([strain] for seeding, [] for non-seeding) + block_name + empty asset_ids/log_ids,
    push to commits, emit the summary line under the `summariesFd != null` guard, and `continue`.
    Thread csvPath + pageDate from the main() call site at line 748 (csvPath already resolved
    at line 772; derive pageDate via pageDateForImage(path.basename(pagePath))). Live/non-backfill
    paths (opts.bulkBackfill false) are UNCHANGED.
  </action>
  <verify>
    <automated>cd src/agents/alerter && npx jest scripts/backfill-notebook.test.js -t "fidelity|no_csv|csv_verified|hold_reason|no_csv_reason"</automated>
  </verify>
  <acceptance_criteria>
    - All Plan 01 fidelity scaffolds GREEN (-t "fidelity|no_csv|csv_verified|hold_reason|no_csv_reason").
    - Hold entries carry `entry.ok === 'held'` (never false).
    - The three reason strings are exactly `fidelity_cross_check_no_csv`,
      `fidelity_cross_check_unverified`, `fidelity_cross_check_nonseeding`.
    - CSV-verified seeding drafts still reach router.commit; non-backfill paths untouched.
    - Full backfill suite green: `cd src/agents/alerter && npx jest --testPathPattern=backfill`.
  </acceptance_criteria>
  <done>Fidelity gate holds all unverified/no-csv/nonseeding drafts; only exact-verified seeding commits.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| local CSV file -> commit gate | mushroom_log.csv is trusted local corpus data parsed by existing parseCsv; not external-user input |
| harness -> DB | authenticated updateDraftStatus writes (existing whitelisted path) |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-55B-03 | Tampering | extracted-strain vs CSV mismatch silently committed | mitigate | the gate itself — any strain not in the per-page CSV budget is held, never flipped to confirmed (closes mode-2) |
| T-55B-04 | Repudiation | which drafts were held + why is unauditable | mitigate | distinct needs_review_reason per branch + summaries.log line per held draft (existing summariesFd path) |
| T-55B-05 | Denial of service | shared csvBudget reused across pages holds everything | accept | budget is rebuilt per-page from loadCsvForPage(pageDate); Pitfall 1 documented; no cross-page state |
| T-55B-SC | Tampering | npm installs | mitigate | zero new packages this phase; no install task |
</threat_model>

<verification>
- Plan 01 RED fidelity + budget scaffolds now GREEN.
- `cd src/agents/alerter && npx jest --testPathPattern=backfill` GREEN.
- Full suite green: `cd src/agents/alerter && npx jest --passWithNoTests`
  (only the image-upload scaffolds from Plan 01 remain RED until Plan 03).
- Manual spot-read: confirm the gate is inside `if (opts.bulkBackfill === true)` and that
  flipDraftToConfirmed is unreachable for held drafts.
</verification>

<success_criteria>
- FIDELITY-01: CSV cross-check holds mismatched-strain and no-CSV drafts; verified strains commit.
- FIDELITY-02: correct needs_review_reason per branch; held drafts never reach farmOS.
- ok:'held' bucketing keeps receipt held-vs-failed counts correct.
</success_criteria>

<output>
Create `.planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-02-SUMMARY.md` when done.
</output>
