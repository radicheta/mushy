---
phase: 48-session-entity-per-bag-commit-fan-out-session-shaped-confirm
plan: 05
subsystem: alerter / farmOS commit pipeline ship-gate
tags: [ship-gate, integration-tests, hermetic, live-fire-operator-deferred, inoc-04, inoc-05, inoc-06, seeding-session]
requires:
  - "48-02 (commitSeedingSession + assets.deleteFungiAsset + client.delete shipped)"
  - "48-03 (preview-builder seeding_session branch -- not exercised here)"
  - "48-04 (commit-outcome-preview reasonMap entries + send_commit_outcome_ack dispatch for seeding_session)"
provides:
  - "Three hermetic CI integration tests exercising the FULL producer-to-consumer chain (commit-watchdog -> commit-router -> commit-seeding-session -> assets/logs -> mock farmosClient -> commitDb -> outboundConfirm.dispatch -> auditLogger)"
  - "INOC-04 (single-parent legacy) hermetic attestation: 1 group of 5 children still mints session asset + 5 child logs"
  - "INOC-05 (idempotency / no double-write / no double-ack) hermetic attestation: layer 1 (findConfirmedCandidates filters status='committed') + layer 2 (cache-probe short-circuit for re-presented rows)"
  - "INOC-06 (session asset + per-bag fan-out + asset-->asset lineage [source, session]) hermetic attestation"
  - "Orphan-cleanup-on-partial-fail hermetic attestation: log #4 -> 422 -> 9 reverse-order DELETEs + commit_failed reason='partial_commit_failed' + outboundConfirm.dispatch outcome='failed' + (deeper) orphan_cleanup_failed audit on DELETE-itself-fails"
  - "48-LIVE-FIRE.md operator runbook (mirror of 47-LIVE-FIRE.md): step-by-step curl + node -e script for real farmOS dev replay; gated behind EVAL_RUN_LIVE=1 + FARMOS_DEV_URL + FARMOS_API_TOKEN; operator-deferred"
affects:
  - "src/agents/alerter/test/farmos/integration/ (new directory siblings to extractor-to-commit.test.js)"
  - "src/agents/alerter/test/fixtures/seeding-session-may22-commit/ (new fixture pair)"
  - "No source files touched -- this is a pure ship-gate plan"
tech-stack:
  added: []
  patterns:
    - "Shared harness (_session-commit-harness.js) wires the REAL commit-watchdog + REAL commit-router + REAL commit-seeding-session + REAL assets.js + REAL logs.js against a mock farmOS client and an in-memory commitDb. The only mocks are at the I/O boundaries (HTTP client, pg pool, outboundConfirm, auditLogger). Producer-to-consumer chain is exercised in one process per [[feedback_unit_tests_dont_catch_wiring]]."
    - "Mock-client extension for DELETE + per-log-POST failure injection: extendClientWithDelete(client, {failLogIndex, deleteResponse}) wraps makeMockClient.post to fail the Nth seeding-log POST and adds a client.delete jest.fn(). Keeps mock-client.js itself untouched (Plan 02 left it alone; same convention here)."
    - "Defense-in-depth idempotency probe: Test 3 (idempotent) asserts BOTH layers -- (a) findConfirmedCandidates filters status='committed' so a re-tick is a complete no-op (no SQL hit on the row); AND (b) if a row IS somehow re-presented at status='confirmed' with a cached farmos_response, commit-watchdog.js line 77 short-circuits via getCachedResponse + commit_idempotent_noop audit before any POST or dispatch."
    - "commitRetryMax=0 in the harness config forces terminal failure on first attempt (no retry loop) -- the partial-fail test asserts the terminal commit_failed state directly without needing to drive multiple ticks."
    - "Live-fire operator runbook (48-LIVE-FIRE.md) follows the 47-LIVE-FIRE.md paper-trail shape: prerequisites + step-by-step operator commands + deviation policy + empty Result section to be filled when run."
key-files:
  created:
    - src/agents/alerter/test/farmos/integration/_session-commit-harness.js
    - src/agents/alerter/test/farmos/integration/seeding-session-commit-may22.test.js
    - src/agents/alerter/test/farmos/integration/seeding-session-commit-partial-fail.test.js
    - src/agents/alerter/test/farmos/integration/seeding-session-commit-idempotent.test.js
    - src/agents/alerter/test/fixtures/seeding-session-may22-commit/draft.json
    - src/agents/alerter/test/fixtures/seeding-session-may22-commit/expected-farmos-payloads.json
    - .planning/phases/48-session-entity-per-bag-commit-fan-out-session-shaped-confirm/48-LIVE-FIRE.md
  modified: []
decisions:
  - "Plan 05 ships THREE test files (not one fat file). Mirrors the 47-05 / Plan 02 layout; keeps each test concern isolated and reportable independently (happy / partial-fail / idempotent)."
  - "Shared harness lives at _session-commit-harness.js (underscore prefix so jest does not pick it up as a test file). All three test files import buildHarness() and pass per-scenario knobs (failLogIndex, deleteResponse, draft override, rowOverrides)."
  - "Fixture draft.json is a copy of the canonical May 22 draft at test/fixtures/seeding-session-may22/expected-draft.json (the Phase 47 extractor's gold output). Plan 05's <files> block listed it as a NEW fixture under the seeding-session-may22-commit/ namespace; copying (not symlinking or sharing the path) makes the commit-side fixture independent of any future extraction-side fixture edits. Cost: 117 lines of JSON duplicated -- acceptable for the isolation."
  - "expected-farmos-payloads.json documents the gold POST/DELETE counts as a single source of truth that the test assertions reference. Counts: happy_path=17 assets+11 logs; partial_fail=9 DELETEs at failed_at_child_index=3; idempotent=zero new writes/dispatches on second tick; single_parent=7 assets+5 logs."
  - "Live-fire is OPERATOR-DEFERRED per Plan 05 directive. The hermetic tests carry an EVAL_RUN_LIVE branch that explicitly throws to remind the operator to follow the 48-LIVE-FIRE.md runbook (mock-vs-real proof cannot be automated inside jest without wiring the real HTTP client, which is operator-territory). This mirrors the 47-05 deferral pattern and the [[feedback_real_data_before_ship_gate_pass]] curated-fixtures-are-not-sufficient policy."
  - "commitRetryMax=0: the partial-fail integration test asserts the TERMINAL commit_failed state. With retryMax>=1 the watchdog would requeue on transient errors; 422 is NOT transient (per _isTransient: http_status<500 + no transient reason match), but pinning retryMax=0 is defense-in-depth + makes the test intent explicit."
  - "INOC-04 attestation lives in seeding-session-commit-may22.test.js (the 'single-parent legacy' it() block) rather than its own file. Rationale: it shares the happy-path harness + assertions; a separate file would just duplicate the harness wiring. The describe() titles make the INOC-04 coverage explicit."
metrics:
  duration_min: 25
  completed: 2026-05-23
---

# Phase 48 Plan 05: hermetic integration ship-gate (May 22 commit replay)

One-liner: Ship the producer-to-consumer integration tests proving the seeding_session commit pipeline writes 17 assets + 11 logs on the May 22 fixture, reverse-DELETEs 9 orphans on partial fail, and is a no-op on double-YES; operator runbook for the real-farmOS live-fire mock-vs-real proof.

## What shipped

### 1. Hermetic integration tests (3 files, 7 tests, <0.5s)

`test/farmos/integration/seeding-session-commit-may22.test.js` -- happy path (2 it() blocks + 1 LIVE-FIRE reminder):
- **May 22 happy path (INOC-06):** 5 groups / 11 children. Asserts 17 asset POSTs (1 session + 5 source + 11 child) + 11 seeding-log POSTs + 0 DELETEs. Session asset is the first POST, name `inoc 2026-05-22`, no fungi_type relationship (allowNoFungiType:true), fungi_xing 'block' present. Every child block's `relationships.parent.data` is length 2 with `data[1].id === sessionId` and `data[0].id` is one of the 5 source-block UUIDs. The signal_draft row in the in-memory commitDb transitions confirmed -> committing -> committed. `outboundConfirm.dispatch('send_commit_outcome_ack', row, {outcome:'success'})` called exactly once.
- **Single-parent legacy (INOC-04):** 1 group / 5 children / parent 260118_KOY_12. 7 assets (1 session + 1 source + 5 child) + 5 logs. Every child has `parent.data` equal to `[sourceBlockId, sessionId]` in that order.
- **LIVE-FIRE reminder:** returns no-op unless `EVAL_RUN_LIVE=1`; on `=1` throws a message pointing at 48-LIVE-FIRE.md (operator-deferred).

`test/farmos/integration/seeding-session-commit-partial-fail.test.js` -- orphan cleanup (2 it() blocks):
- **Log #4 returns 422:** 9 reverse-order DELETEs (last child first, session asset last). Asset[last] = the 4th child block (260522_KOY_*); first DELETE path matches its UUID. signal_draft row -> commit_failed with reason='partial_commit_failed'. auditLogger: commit_attempt + commit_failed present; commit_success + orphan_cleanup_failed absent. outboundConfirm.dispatch called once with `{outcome:'failed', reason:'partial_commit_failed'}`.
- **DELETEs themselves fail (500):** still 9 DELETEs attempted; 9 `orphan_cleanup_failed` audit lines emitted (one per failed DELETE, each carrying one orphan UUID); failed-ack STILL dispatched (Phase 45 no-silent-failure invariant holds).

`test/farmos/integration/seeding-session-commit-idempotent.test.js` -- INOC-05 (2 it() blocks):
- **Double tickOnce (layer 1):** first tick is full happy-path commit; second tick is a complete no-op because findConfirmedCandidates filters out the now-status='committed' row. Zero new POSTs / GETs / dispatches / audit events between tick 1 and tick 2.
- **Cache-probe re-presentation (layer 2):** simulates a status='confirmed' row whose getCachedResponse returns `{ok:true, status:'committed', farmos_response:...}`. commit-watchdog.js line 77 short-circuits BEFORE the lock + commit. farmosClient.post NEVER called; outboundConfirm.dispatch NEVER called; audit `commit_idempotent_noop` logged; commit_success / commit_attempt absent.

### 2. Shared harness (`_session-commit-harness.js`)

Underscore-prefixed so jest does NOT treat it as a test. Exports `buildHarness({draft, failLogIndex, deleteResponse, knownAssetsByName, rowOverrides})` returning `{watchdog, commitDb, farmosClient, auditLogger, outboundConfirm, row}`. Wires:

- REAL `createCommitWatchdog` from `src/farmos/commit-watchdog.js`
- REAL `commitRouter` from `src/farmos/commits/commit-router.js` (DISPATCH.seeding_session)
- REAL `commit-seeding-session.js` (entire orphan-cleanup branch is exercised)
- REAL `assets.js` + `logs.js` (createFungiAsset / createLog actually run against the mock client)
- Mock farmosClient (mock-client.js + DELETE verb extension + per-log-POST failure injection)
- In-memory commitDb (same shape as commit-watchdog.test.js's fake)
- Mock auditLogger + outboundConfirm

Cache resets (`assets._clearCache`, `fungiTypeCache._clear`, `fungiXingCache._clear`) on every buildHarness call.

### 3. Fixture pair (`test/fixtures/seeding-session-may22-commit/`)

- `draft.json` -- canonical May 22 seeding_session draft (5 groups, 11 children, copied from Phase 47's gold extractor output for commit-side independence)
- `expected-farmos-payloads.json` -- gold counts (17/11 happy, 9 DELETEs at index 3 for partial-fail, zero new writes for idempotent, 7/5 for single-parent legacy) referenced by name in test assertions

### 4. Operator runbook (`.planning/phases/48-*/48-LIVE-FIRE.md`)

Mirror of 47-LIVE-FIRE.md. Prerequisites (farmOS dev reachable, bearer token, fungi_xing 'block' + fungi_type SHI/KOY exist, no pre-existing `inoc 2026-05-22`), step-by-step (hermetic check, node-e live-fire script, curl session-asset lookup, lineage walk verification on 260522_KOY_7, children count check, optional collision branch, cleanup, fill-in Result section), deviation policy (if live-fire differs from hermetic, FAIL and open Phase 49 follow-up -- do not silently fix). Result section is empty pending the operator's first run.

## Verification

Per the plan's `<verification>` block:

- `cd src/agents/alerter && npx jest test/farmos/integration/seeding-session-commit --no-coverage` -> **3 suites passed, 7 tests passed, 0 failed**, total elapsed **0.431s** (well under the <10s budget).
- `.planning/phases/48-*/48-LIVE-FIRE.md` exists with prerequisites + steps + Result template; awaits operator run.
- The 11 child-block names (`260522_SHI_1..3, 260522_KOY_4..11`) appear in both the runbook (cleanup loop) and the fixture (`grep -c "260522_SHI\|260522_KOY" 48-LIVE-FIRE.md` -> 11 distinct names referenced).

Full `test/farmos` suite regression sweep:

```
Test Suites: 1 skipped, 23 passed, 23 of 24 total
Tests:       8 skipped, 207 passed, 215 total
Snapshots:   13 passed, 13 total
Time:        0.751 s
```

No pre-existing tests broken by Plan 05's additions. The 1 skipped suite + 8 skipped tests pre-date this plan (verified against the Plan 04 SUMMARY's full-sweep counts).

## INOC requirement-by-requirement attestation

| Req | Lock | Hermetic test | Live-fire | Verdict |
|---|---|---|---|---|
| INOC-04 | Single-parent legacy still mints session asset + N child logs | `seeding-session-commit-may22.test.js` "single-parent legacy" it() block: 1 group / 5 children -> 7 assets + 5 logs; child.parent[] = [source, session] | Operator-deferred runbook covers this implicitly via the May 22 fixture (which includes single-child groups 1-3) | **PASS (hermetic) + operator-deferred (live)** |
| INOC-05 | Double-YES no double-write; no double-ack | `seeding-session-commit-idempotent.test.js` BOTH it() blocks: layer 1 (findConfirmedCandidates filter) + layer 2 (cache-probe short-circuit) | Operator runbook documents but does not automate; consider re-running Step 2 on the same draft to verify | **PASS (hermetic) + operator-deferred (live)** |
| INOC-06 | Session asset + per-bag fan-out + lineage [source, session] | `seeding-session-commit-may22.test.js` "May 22 happy path" it() block: 17 assets + 11 logs; lineage walk asserted on every child | Operator runbook Step 4 (curl lineage walk on 260522_KOY_7) is the live proof of the asset-->asset encoding | **PASS (hermetic) + operator-deferred (live)** |

## Threat-flag scan

All 3 STRIDE threats from the plan's `<threat_model>` resolved without new surface:

| Threat ID | Resolution |
|-----------|------------|
| T-48-05-01 (Tampering, live-fire pollutes farmOS dev) | 48-LIVE-FIRE.md Step 7 (cleanup loop) DELETEs every test-created child + session; source blocks intentionally retained as real parents. Operator-attestable trail. |
| T-48-05-02 (Repudiation, no paper trail) | 48-LIVE-FIRE.md is the paper trail; Result section template per [[feedback_keep_paper_trail_of_intermediates]]. |
| T-48-05-03 (Tampering, mock-vs-live drift) | Hermetic tests document the EXPECTED shape; 48-LIVE-FIRE.md Step 4 (curl lineage walk) is the proof of agreement; deviation policy mandates re-open if they disagree. |
| T-48-05-SC | Zero npm deps added (verified by no package.json change). |

No new threat flags emitted. No new network surface, no new auth paths, no new file access.

## Deviations from Plan

**None functional.** Two minor observations:

**1. [Note] EVAL_RUN_LIVE=1 branch in `seeding-session-commit-may22.test.js` is a "throw and point at runbook" reminder, not an automated harness.**

- **Found during:** writing Task 1.
- **Rationale:** Plan 05's `<files>` block listed "src/agents/alerter/test/farmos/integration/seeding-session-commit-may22.test.js (add EVAL_RUN_LIVE branch only)" but Task 2 explicitly says live-fire is operator-deferred. Wiring the real farmOS client (`createFarmOSClient`) into jest would (a) duplicate the `node -e` script in 48-LIVE-FIRE.md, (b) require the operator to also set env in the jest invocation, and (c) leave real farmOS writes behind on test failure with no DELETE rollback (jest does not run the orphan-cleanup branch on assertion failures). Throwing a pointer to the runbook is the safer compromise per Plan 05's "operator-deferred" directive.
- **Impact:** None on hermetic CI (the throw is gated behind EVAL_RUN_LIVE=1). An operator who sets the env explicitly is reminded to switch to the runbook.

**2. [Naming] Test 2 (partial-fail) expects DELETE count = 9, matching Plan 02 Test E.**

- **Found during:** writing the partial-fail test.
- **Rationale:** Plan 05's `<behavior>` block has two phrasings: "DELETE count = 4 child + 5 source + 1 session = 10" AND "(re-read 48-02-SUMMARY to confirm exact cleanup set)". The 48-02 SUMMARY's Test E pin (commit `ebd1f98`'s predecessor) settled on 1 session + 4 source + 4 child = 9 because group 5's source block has NOT been touched yet when log #4 fails. The integration test asserts the 9-count to stay consistent with the unit test; Plan 05's intent matches once you read the SUMMARY's correction.
- **Impact:** Aligned with the existing Phase 48-02 ship.

No auth gates. No blockers.

## Out-of-scope items observed (NOT touched per Rule 3)

While running the regression sweep I observed the following pre-existing state, NOT touched by Plan 05:

- `test/extraction/integration/seeding-session-may22.test.js` -- documented as pre-existing in 48-02 / 48-04 SUMMARYs; Plan 03's preview-builder drift. Out of scope here.
- `test/extraction/integration/seeding-session-photo-absent.test.js` -- same.

Plan 05's targeted suite (`test/farmos/integration/seeding-session-commit`) is 100% green. The full `test/farmos` suite (23 of 24 suites passed; 1 pre-existing skipped) is also green.

## Handoff to Phase 49

The v1.9 milestone ship-gate is NOT this plan. Plan 05 proves the seeding_session COMMIT pipeline writes correctly in a mock environment + provides the operator runbook for the real-farmOS mock-vs-real proof. The REAL ship gate -- end-to-end reprocessing of the original 2026-05-22 production capture (audio + paper-log photo via Phase 47's extraction, through Phase 48's commit, into farmOS dev) -- is Phase 49's purview.

Phase 49 entry conditions, in priority order:

1. (Pre-49) Operator runs the 48-LIVE-FIRE.md runbook and records the Result section. If PASS, Phase 49 inherits a known-good commit pipeline. If FAIL, Phase 49's first plan is the deviation fix.
2. Phase 49 Plan 01 candidates: (a) replay the original May 22 audio + photo through extractor + watchdog + farmer-confirm + commit-watchdog end-to-end; (b) operator-attested ship gate; (c) mark the original `e3a564d0...` + `6edaaba7...` failed drafts as `discarded`.
3. Phase 50 (already CONTEXT'd): Signal-quote-native EDIT routing; orthogonal to the v1.9 ship.

## Self-Check

- `src/agents/alerter/test/farmos/integration/_session-commit-harness.js` exists. FOUND.
- `src/agents/alerter/test/farmos/integration/seeding-session-commit-may22.test.js` exists. FOUND.
- `src/agents/alerter/test/farmos/integration/seeding-session-commit-partial-fail.test.js` exists. FOUND.
- `src/agents/alerter/test/farmos/integration/seeding-session-commit-idempotent.test.js` exists. FOUND.
- `src/agents/alerter/test/fixtures/seeding-session-may22-commit/draft.json` exists. FOUND.
- `src/agents/alerter/test/fixtures/seeding-session-may22-commit/expected-farmos-payloads.json` exists. FOUND.
- `.planning/phases/48-session-entity-per-bag-commit-fan-out-session-shaped-confirm/48-LIVE-FIRE.md` exists. FOUND.
- Targeted command `npx jest test/farmos/integration/seeding-session-commit --no-coverage` -> **7 passed, 0 failed, 0.431s**. FOUND.
- Full `test/farmos` regression sweep -> **207 passed, 8 skipped, 0 failed**. FOUND.

## Self-Check: PASSED
