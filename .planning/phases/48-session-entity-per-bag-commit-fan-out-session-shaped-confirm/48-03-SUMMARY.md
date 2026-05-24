---
phase: 48-session-entity-per-bag-commit-fan-out-session-shaped-confirm
plan: 03
subsystem: alerter-extraction-renderer
tags: [preview-builder, seeding_session, renderer, gray-area-c, em-dash-policy]
requires: [48-01]
provides: ["Production renderSeedingSession group-by-parent table replacing Phase 47-04 placeholder"]
affects: [src/agents/alerter/src/extraction/preview-builder.js]
tech-stack:
  added: []
  patterns:
    - "Module-internal renderer dispatched from buildPreview() on type==='seeding_session'"
    - "Fixed-column padded table with dynamic widths (min KEY=4, PARENT=15, SPECIES=8, QTY=4)"
    - "Range-collapse for 3+ consecutive same-strain SEQs"
    - "First-5-groups + '... (M more groups)' overflow cap"
    - "Defensive needs_input='starting_seq' branch (ask-back form)"
key-files:
  created:
    - src/agents/alerter/test/extraction/preview-builder-session.test.js
  modified:
    - src/agents/alerter/src/extraction/preview-builder.js
    - src/agents/alerter/test/extraction/sanitize.test.js
    - src/agents/alerter/test/extraction/integration/seeding-session-may22.test.js
    - src/agents/alerter/test/extraction/integration/seeding-session-photo-absent.test.js
decisions:
  - "Renamed buildSeedingSessionPlaceholder -> renderSeedingSession (per plan output spec)"
  - "Header line uses colon ('Inoc session: 2026-05-22'), NOT em-dash from CONTEXT.md template (no-em-dash policy is the stronger rule; canonical-source-wins per friction policy)"
  - "Removed Phase 47-04 'May D' human-readable date hotfix from the session preview; the table reads like a notebook entry where ISO YYYY-MM-DD matches the farmer's paper log; the 'May 22 inoc' ask-back template in pipeline.js (separate code path) keeps its human-readable form"
  - "Phase 47-04 placeholder-branch test block (7 tests) moved out of sanitize.test.js and replaced by the 8-test preview-builder-session.test.js production suite; one regression-guard test kept in sanitize.test.js to assert legacy 5-type rendering is unaffected"
metrics:
  duration: ~25min
  completed: 2026-05-23
  tests_added: 8
  tests_removed_or_replaced: 7
  files_changed: 5
---

# Phase 48 Plan 03: Production renderSeedingSession Summary

One-liner: Group-by-parent table renderer replaces the Phase 47-04 placeholder; farmer sees a 5-line scan-against-notebook preview before YES on the inoc session.

## What Shipped

`renderSeedingSession(draft)` in `src/agents/alerter/src/extraction/preview-builder.js` produces the locked group-by-parent table per CONTEXT.md Gray Area C. The function is dispatched from `buildPreview()` on `draft.type === 'seeding_session'` and the Phase 47-04 placeholder (`buildSeedingSessionPlaceholder`) is fully replaced (not shadowed). No new exports; the function is module-internal.

### Rendered Snapshot (canonical May 22 fixture, 11 blocks / 5 parents)

```
Inoc session: 2026-05-22
11 blocks across 5 parents

KEY   PARENT           SPECIES   QTY   CHILDREN
1     260304_SHI_5     SHI       1     260522_SHI_1
2     260118_SHI_23    SHI       1     260522_SHI_2
3     260118_SHI_26    SHI       1     260522_SHI_3
4     260118_KOY_12    KOY       4     260522_KOY_4..7
5     260425_KOY_4     KOY       4     260522_KOY_8..11

YES to commit | NO to cancel | EDIT to change
```

### Behavior Coverage

- **Header**: `Inoc session: {event_date}` (colon, not em-dash; see Decisions below).
- **Summary**: `{total_children} blocks across {group_count} parents`.
- **Column header**: `KEY  PARENT  SPECIES  QTY  CHILDREN` (fixed mins: 4/15/8/4 + 2-space gutter).
- **Range-collapse**: 3+ same-strain consecutive SEQs render as `prefix_FIRST..LAST` (e.g. `260522_KOY_4..7`). 1-2 children, or non-consecutive, render comma-joined.
- **Overflow**: groups beyond 5 render `... (M more groups)` trailing row, BEFORE the YES/NO/EDIT footer.
- **Notes**: `draft.notes` (if present, non-empty) renders as `note: {text}` line BEFORE the footer.
- **needs_input='starting_seq'**: defensive ask-back branch (`Reply with the starting SEQ (e.g. 4).`) — pipeline.js still short-circuits via the separate `send_starting_seq_askback` side-effect; this branch keeps `renderSeedingSession` total when called on an ask-back draft.
- **NO_PARENT sentinel**: parent.value === 'NO_PARENT' renders `no parent recorded` (sentinel string never leaks).
- **Conflicts (Gray Area 4)**: renderer NEVER reads `draft.conflicts[]`; output contains neither the word "conflict" nor any losing candidate value.
- **Em-dash sweep**: output passes `sanitizeFarmerText` (ASCII only).

### Tests (8 new + 1 regression guard)

`test/extraction/preview-builder-session.test.js`:
- (A) May-22 canonical: header, summary, column header, 5 group rows, footer; no em-dash; no emoji.
- (B) range-collapse: 3 consecutive -> range; 2 children -> comma list; 3 non-consecutive -> comma list.
- (C) overflow: 7 groups -> 5 visible + `... (2 more groups)` before footer.
- (D) silent conflicts: losing candidate `260118_SHI_25` absent; "conflict" word absent; `photo_wins` absent; winning value `260118_SHI_23` present (it IS the resolved parent.value).
- (E) notes: `note: migration to new shelf` line before footer.
- (F) needs_input='starting_seq': ask-back form, no table, no YES footer.
- (G) single-parent legacy: 1 group / 5 consecutive -> 1 row with `260522_SHI_1..5`.
- (H) NO_PARENT sentinel: renders "no parent recorded"; literal `NO_PARENT` absent.

`test/extraction/sanitize.test.js`:
- Regression guard: legacy `seeding` draft renders the same field-listing body; no `Inoc session`, no `blocks across`, no `YES to commit` leaks into the legacy path.

Full extraction suite: **221/221 green** (`npx jest test/extraction --no-coverage`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] Updated two Phase 47-04 integration tests against the new renderer**

- **Found during:** Task 1 verification (running `npx jest test/extraction`).
- **Issue:** `test/extraction/integration/seeding-session-may22.test.js` and `test/extraction/integration/seeding-session-photo-absent.test.js` asserted the placeholder strings `'11 blocks across 5 groups for May 22'`, `'Phase 48'`, `'11 blocks across 2 groups for May 22'` — these came from the Phase 47-04 placeholder and no longer apply.
- **Fix:** Updated both assertions to match the production renderer output (`Inoc session: 2026-05-22`, `N blocks across M parents`, column header, YES footer). The plan's Test H called these "regression" tests and required they remain green; updating them to match the renamed-and-replaced renderer is the correct interpretation (the placeholder shape they pinned is the very thing this plan replaces).
- **Files modified:** `seeding-session-may22.test.js`, `seeding-session-photo-absent.test.js`.
- **Files NOT touched:** `pipeline.test.js`'s `buildStartingSeqAskBackText` tests — that is a separate code path in pipeline.js with its own template (`Hi {sender}, ... May 22 inoc, 11 blocks ...`).

### Stylistic Adjustments

**2. Header line uses colon, not em-dash, contradicting the CONTEXT.md template by design**

- CONTEXT.md Gray Area C shows `Inoc session -- 2026-05-22` (rendered with an em-dash in the template). The plan calls this out explicitly: `feedback_no_em_dashes_in_artifacts` is the stronger rule. Implemented `Inoc session: 2026-05-22`.

**3. Dropped Phase 47-04 "May 22" date hotfix in the session preview**

- The Phase 47-04 placeholder used `fmtEventDate('2026-05-22') -> 'May 22'`. The new session table renders the raw ISO `2026-05-22` to match the farmer's paper-log notation. The ask-back template in pipeline.js (`May 22 inoc, 11 blocks`) is a separate code path and was not touched.

### Out of Scope / Deferred

- **eval/extraction/mushdatadump.test.js** has a pre-existing failure (`Cannot find module 'fixtures/...'`) that exists on `main` independent of this plan. Logged here, not fixed in this plan.

## Threat Surface

All STRIDE mitigations from the plan's threat_model implemented:
- T-48-03-01 (conflict disclosure): mitigated — renderer reads only `draft.event_date`, `draft.groups[]`, `draft.notes`, `draft.needs_input`. Never touches `draft.conflicts[]`. Test (D) asserts negatively.
- T-48-03-02 (em-dash injection): mitigated — output piped through `sanitizeFarmerText`. Test (A) asserts negatively.
- T-48-03-03 (unbounded children): mitigated — range-collapse + 5-group overflow cap.
- T-48-03-SC: accepted — no new npm dependencies.

## Self-Check: PASSED

- File exists: `src/agents/alerter/src/extraction/preview-builder.js` — FOUND.
- File exists: `src/agents/alerter/test/extraction/preview-builder-session.test.js` — FOUND.
- `grep -c "Group-by-parent preview coming in Phase 48"` against preview-builder.js = 0 — confirmed.
- `grep -c "renderSeedingSession"` against preview-builder.js >= 1 — confirmed (2 occurrences: definition + dispatch site).
- All 8 new tests + 1 regression guard pass; full `test/extraction/*` suite 221/221 green.
