---
phase: 48-session-entity-per-bag-commit-fan-out-session-shaped-confirm
plan: 04
subsystem: alerter / farmer-ack renderer + commit-watchdog
tags: [seeding_session, commit-outcome-ack, phase45-contract, no-silent-failure, inoc-05]
requires:
  - "48-02 (commitSeedingSession returns reasons: session_name_exhausted, partial_commit_failed)"
  - "45-04 (Phase 45 ack contract: commit-watchdog dispatches send_commit_outcome_ack on both terminal states; tryMarkOutcomeAckSent CAS guarantees ack-once)"
provides:
  - "LOG_TYPE_LABEL.seeding_session = 'Inoc session' (renderer farmer-facing label)"
  - "reasonMap += { partial_commit_failed, session_name_exhausted, session_fungi_type_term_missing }"
  - "buildDisambiguator seeding_session branch -> '{event_date} Inoc session (N blocks across M parents)'"
  - "renderOutcomeAck success short-circuit for seeding_session -> 'Hi {Name}, saved {what}.' (no general-farm-note boilerplate)"
affects:
  - "src/agents/alerter/src/farmos/commit-outcome-preview.js"
  - "src/agents/alerter/test/farmos/commit-outcome-preview.test.js (+9 tests)"
  - "src/agents/alerter/test/farmos/commit-watchdog.test.js (+4 tests)"
tech-stack:
  added: []
  patterns:
    - "log_type-shaped disambiguator dispatch: buildDisambiguator now branches on log_type before falling through to the generic name/notes path; legacy log_types render byte-identically (Test F regression guard)."
    - "renderOutcomeAck success short-circuit: target==null + log_type=seeding_session bypasses the legacy 'general farm note' template, which is misleading for a multi-parent inoc session (the session DID commit cleanly to a session asset + N children, just not to a single block)."
    - "Watchdog is type-agnostic: Phase 45 Plan 04's _maybeDispatchOutcomeAck already passes lockedRow as-is and the renderer dispatches on lockedRow.log_type. Phase 48's new draft type rides this machinery with ZERO commit-watchdog code changes -- only regression tests added."
key-files:
  created: []
  modified:
    - src/agents/alerter/src/farmos/commit-outcome-preview.js
    - src/agents/alerter/test/farmos/commit-outcome-preview.test.js
    - src/agents/alerter/test/farmos/commit-watchdog.test.js
decisions:
  - "renderOutcomeAck short-circuit (not refactor): the planner pre-authorized an extracted per-log_type formatter map under [[planner-authority-limits]]. Chose the surgical short-circuit branch instead -- ~10 lines, preserves legacy byte-identical output, no risk to the 13 Phase 45 snapshot fixtures. A formatter-map refactor is deferred until a 3rd or 4th log_type needs the same special-casing."
  - "Disambiguator counts: read child_block_names.value.length FIRST, fall back to qty.value, fall back to 0. Mirrors the Plan 03 preview-builder counting logic so the preview-vs-ack farmer experience is consistent (same counts shown in both messages)."
  - "event_date is rendered as the raw 'YYYY-MM-DD' string (not fmtDate'd to 'MMM D'). Rationale: the session draft already carries a clean ISO date and the farmer's notebook uses ISO dates too. 'MMM D' is a Phase 45 convention for legacy log_types whose event_timestamp is a JS Date; for seeding_session we preserve the unambiguous full date. Legacy log_types still get the 'MMM D' format (no regression)."
  - "session_fungi_type_term_missing was added to reasonMap as a future-proofing entry. The Plan 02 handler does NOT currently emit this code (it uses allowNoFungiType:true so the term isn't required). The map entry exists so that if a future plan tightens the session-asset path to require a real 'session' fungi_type term, the ack contract is already wired."
  - "tryMarkOutcomeAckSent CAS verification: confirmed the existing in-memory ack-claimed Set in commit-watchdog.test.js works for seeding_session by inspection of the dispatch path (the CAS is type-agnostic; it keys on draft id, not log_type). The Test C 'idempotent no-op' regression test asserts that already-committed seeding_session rows short-circuit at commit-watchdog.js line 77 BEFORE _maybeDispatchOutcomeAck is reached, so tryMarkOutcomeAckSent is never called -- which is the correct behavior."
metrics:
  duration_min: 10
  completed: 2026-05-23
---

# Phase 48 Plan 04: ack contract for seeding_session

One-liner: Wire the Phase 45 farmer-ack contract end-to-end for the new `seeding_session` draft type by extending `LOG_TYPE_LABEL`, `reasonMap`, `buildDisambiguator`, and the `renderOutcomeAck` success-path short-circuit; the commit-watchdog needed no code changes (only regression tests).

## What shipped

### 1. `src/farmos/commit-outcome-preview.js` (modified)

**LOG_TYPE_LABEL diff:**

```diff
 const LOG_TYPE_LABEL = Object.freeze({
-  seeding:     'seeding',
-  activity:    'activity',
-  input:       'input log',
-  observation: 'observation',
-  harvest:     'harvest',
+  seeding:         'seeding',
+  activity:        'activity',
+  input:           'input log',
+  observation:     'observation',
+  harvest:         'harvest',
+  seeding_session: 'Inoc session',
 });
```

**reasonMap diff (+3 entries):**

```diff
   taxonomy_term_missing:        'missing a taxonomy term',
   generic_validation_error:     'data validation failed',
+  partial_commit_failed:           'a write partway through failed, nothing saved',
+  session_name_exhausted:          'too many same-day session names already exist',
+  session_fungi_type_term_missing: 'farmOS session taxonomy term missing',
 });
```

**buildDisambiguator branch (new helper `_seedingSessionDisambiguator`):**

When `draftRow.log_type === 'seeding_session'` (or `draft_json.type === 'seeding_session'`), render `"{event_date} Inoc session (N blocks across M parents)"` where:
- `event_date` = `draft_json.event_date` (raw `YYYY-MM-DD`); falls back to `fmtDate(pickBestDate(...))` for legacy event_timestamp-only drafts.
- `N` = sum of `groups[i].child_block_names.value.length` (falls back to `groups[i].qty.value`).
- `M` = `groups.length`.

All other log_types fall through to the legacy `date + summary` path unchanged (Test F regression guard asserts byte-identical legacy output).

**renderOutcomeAck success short-circuit (new branch):**

```js
if (outcome === 'success') {
  const djType = row.draft_json && row.draft_json.type;
  if (logType === 'seeding_session' || djType === 'seeding_session') {
    let body = `${hi}saved ${what}.`;
    if (typeof opts.farmosLink === 'string' && opts.farmosLink.trim() !== '') {
      body += ` Open in farmOS: ${opts.farmosLink.trim()}`;
    }
    return sanitizeFarmerText(body);
  }
  // ... legacy target!=null and farm-level no-target branches unchanged
}
```

Rationale: the legacy `target==null` branch renders `"... as a general farm note since I couldn't match a specific block. Send EDIT to attach a block if you want."` -- which is **factually wrong** for a successful seeding_session commit (the session DID commit cleanly to a session asset + N child blocks; there was just never a single-block target to begin with). The short-circuit produces a clean session-shaped success.

### 2. Rendered ack strings (May 22 fixture: 5 groups, 11 children)

Captured live from `node -e "renderOutcomeAck(...)"`:

```
SUCCESS:
  Hi Santi, saved 2026-05-22 Inoc session (11 blocks across 5 parents).

FAIL partial_commit_failed:
  Hi Santi, about the 2026-05-22 Inoc session (11 blocks across 5 parents): couldn't save it because a write partway through failed, nothing saved. Send EDIT to fix or NO to drop.

FAIL session_name_exhausted:
  Hi Santi, about the 2026-05-22 Inoc session (11 blocks across 5 parents): couldn't save it because too many same-day session names already exist. Send EDIT to fix or NO to drop.

FAIL session_fungi_type_term_missing:
  Hi Santi, about the 2026-05-22 Inoc session (11 blocks across 5 parents): couldn't save it because farmOS session taxonomy term missing. Send EDIT to fix or NO to drop.
```

All four strings are ASCII-only, no em-dash, no en-dash, no emoji (Test G asserts).

### 3. `test/farmos/commit-outcome-preview.test.js` (+9 tests)

New `describe('seeding_session (Phase 48 Plan 04)')` block with:
- Test A: success renders clean session-shaped ack; no "general farm note" boilerplate.
- Test B: failed / `partial_commit_failed` -> farmer phrase 'a write partway through failed, nothing saved'.
- Test C: failed / `session_name_exhausted` -> 'too many same-day session names already exist'.
- Test D: failed / `session_fungi_type_term_missing` -> 'farmOS session taxonomy term missing'.
- Test E: failed / unknown reason -> falls back to `generic_validation_error` phrasing.
- Test F: legacy seeding ack byte-identical regression guard.
- Test G: no em-dash, en-dash, or emoji in any of the 4 seeding_session ack variants.
- Counts tests (x2): `child_block_names.value.length` primary, `qty.value` fallback.

### 4. `test/farmos/commit-watchdog.test.js` (+4 tests)

Regression coverage that the new log_type rides the Phase 45 ack contract correctly:
- Phase 48 / success: stub commit-router returns ok=true for log_type='seeding_session'; assert `outboundConfirm.dispatch('send_commit_outcome_ack', row, { outcome: 'success' })` called exactly once; `args[1].log_type === 'seeding_session'`.
- Phase 48 / terminal failure: stub commit-router returns ok=false + http_status:422 + reason:'partial_commit_failed'; assert markFailed status + ack dispatch with `{ outcome: 'failed', reason: 'partial_commit_failed' }`.
- Phase 48 / idempotent no-op: row already in status='committed' -> commit-watchdog short-circuits at the cache probe; `outboundConfirm.dispatch` NOT called; `tryMarkOutcomeAckSent` NOT called (early return before _maybeDispatchOutcomeAck).
- Phase 48 / no double-ack: a row that has already been marked `commit_failed` is not re-fetched by `findConfirmedCandidates` (which filters on status='confirmed'); second tickOnce is a no-op for ack purposes; total dispatch count stays at 1.

## Verification

Per the plan's `<verification>` block:

- `npx jest test/farmos/commit-outcome-preview test/farmos/commit-watchdog --no-coverage` -> **62 passed, 0 failed** (13 snapshot + 4 style + 4 reasonMap-fallback + 7 disambiguator + 9 seeding_session + 3 named-address + 22 watchdog).
- `grep -c "seeding_session" src/agents/alerter/src/farmos/commit-outcome-preview.js` -> **7** (>= 2, target met).
- `grep -v '^//' src/agents/alerter/src/farmos/commit-outcome-preview.js | grep -c "partial_commit_failed\|session_name_exhausted\|session_fungi_type_term_missing"` -> **3** (>= 3, target met).

## Threat-flag scan

All three STRIDE threats in the plan's `<threat_model>` resolved with no new surface introduced:

| Threat ID | Resolution |
|-----------|------------|
| T-48-04-01 (Repudiation, no terminal ack) | Tests "Phase 48: seeding_session success ..." + "Phase 48: seeding_session terminal failure ..." explicitly assert dispatch fires on BOTH paths. |
| T-48-04-02 (Tampering, double-ack on retry) | Tests "Phase 48: idempotent no-op" + "Phase 48: commit_failed ... not re-fetched" both assert. Plus the pre-existing Phase 45 ACK-04 idempotency test (in-memory CAS Set) which is log_type-agnostic. |
| T-48-04-03 (Info disclosure, conflict values leak) | `_seedingSessionDisambiguator` reads ONLY `draft_json.event_date` + `groups[i].child_block_names.value.length` / `qty.value` + `groups.length`. Never touches `draft_json.conflicts` or any conflict-candidate field. Verified by code inspection. |
| T-48-04-SC | Zero npm deps added. Confirmed via no `package.json` modification in this plan. |

No new threat flags emitted.

## Deviations from Plan

**None functional.** Two minor adjustments:

**1. [Naming] LOG_TYPE_LABEL value 'Inoc session' (capital I) rather than 'inoc session' (lowercase).**

- **Found during:** writing Test A.
- **Rationale:** All other LOG_TYPE_LABEL values are lowercase ('seeding', 'activity', etc.) per the existing convention. However, the plan's must-have-truth #1 uses 'Inoc session' (capital I) in the literal expected ack string ('Hi {Name}, saved Inoc session 2026-05-22...'). Plan + tests dominate; shipped 'Inoc session' to match the truth literal. The capital I also reads better as an event-name in the middle of a sentence ('saved 2026-05-22 Inoc session') -- the lowercase 'inoc' looked like a typo in farmer-readback dry runs.
- **Impact:** None on legacy log_types (their labels unchanged).

**2. [Disambiguator order] Rendered as "{event_date} Inoc session (counts)" not "Inoc session {event_date} (counts)".**

- **Found during:** writing Test A.
- **Rationale:** Matches the existing legacy buildDisambiguator output order ("May 13 observation (sterilize)") -- date first, then label, then parenthesized detail. Symmetric across all log_types. The plan's `<behavior>` block proposed `${eventDate} ${label} (...)` which IS this order; documenting here that I followed the plan order exactly.

No other deviations. No auth gates. No blockers.

## Out-of-scope items observed (NOT touched per Rule 3)

While running the targeted suite I observed pre-existing failures in `test/extraction/integration/seeding-session-may22.test.js` and `seeding-session-photo-absent.test.js` (Phase 47 placeholder vs Plan 03 renderer drift). These were already documented as out-of-scope in the Plan 02 SUMMARY and remain Plan 03's purview. Plan 04's targeted suite (commit-outcome-preview + commit-watchdog) is 100% green.

## Self-Check

- `src/agents/alerter/src/farmos/commit-outcome-preview.js` contains `LOG_TYPE_LABEL.seeding_session`. FOUND (line 49 area).
- `src/agents/alerter/src/farmos/commit-outcome-preview.js` contains 3 new reasonMap entries. FOUND (grep returns 3).
- `src/agents/alerter/src/farmos/commit-outcome-preview.js` contains `_seedingSessionDisambiguator` helper. FOUND.
- `src/agents/alerter/src/farmos/commit-outcome-preview.js` contains renderOutcomeAck seeding_session success short-circuit. FOUND.
- `src/agents/alerter/test/farmos/commit-outcome-preview.test.js` contains `describe('seeding_session (Phase 48 Plan 04)')` block. FOUND.
- `src/agents/alerter/test/farmos/commit-watchdog.test.js` contains 4 Phase-48 regression tests. FOUND.
- Targeted command `npx jest test/farmos/commit-outcome-preview test/farmos/commit-watchdog --no-coverage` -> 62 passed, 0 failed. FOUND.

## Self-Check: PASSED
