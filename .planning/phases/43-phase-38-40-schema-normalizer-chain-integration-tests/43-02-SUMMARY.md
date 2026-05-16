---
phase: 43-phase-38-40-schema-normalizer-chain-integration-tests
plan: 02
subsystem: farmos
tags: [farmos, qr, fungi, json-api, tdd, jest]

requires:
  - phase: 40-farmos-write-path
    provides: qr.js resolveQr with id_tag lookup and path field

provides:
  - resolveQr with id_tag-first, name-on-miss fallback per D-06
  - path field ('id_tag' | 'name') indicating which lookup matched
  - 3 new test cases covering name-fallback scenarios

affects:
  - 43-03 (normalize.js -- uses resolveQr for source_qr_codes resolution)
  - 43-05 (chain integration tests -- Test 5 harvest chain uses resolveQr name-fallback)

tech-stack:
  added: []
  patterns:
    - "id_tag-first, name-on-miss two-phase farmOS asset lookup"
    - "mockResolvedValueOnce chaining for multi-call mock sequences in jest"

key-files:
  created: []
  modified:
    - src/agents/alerter/src/farmos/qr.js
    - src/agents/alerter/test/farmos/qr.test.js

key-decisions:
  - "HTTP errors on id_tag call do NOT trigger name fallback (transport failure vs empty-result miss)"
  - "Both-miss returns path='name' (the last lookup attempted)"
  - "Updated existing both-miss test expectation from path='id_tag' to path='name' to match new behavior"

patterns-established:
  - "resolveQr path field enum: 'id_tag' | 'name' indicates which farmOS lookup matched"

requirements-completed: [SCHEMA-01]

duration: 20min
completed: 2026-05-16
---

# Phase 43 Plan 02: QR Resolver Name-Fallback Summary

**resolveQr extended with id_tag-first, name-on-miss fallback returning path='id_tag'|'name' per D-06, enabling block-name resolution in harvest chain**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-05-16T19:40:00Z
- **Completed:** 2026-05-16T20:00:00Z
- **Tasks:** 2 (TDD: RED + GREEN)
- **Files modified:** 2

## Accomplishments
- Extended `resolveQr` to fall back to `filter[name][value]=<qrCode>` when `filter[id_tag.id][value]=<qrCode>` returns empty
- Return shape gains `path: 'id_tag' | 'name'` indicating which lookup matched
- HTTP errors on id_tag call return immediately (transport failure is not a miss -- no fallback)
- 8 tests pass (5 pre-existing + 3 new), full npm test suite 658 tests GREEN

## Task Commits

1. **Task 1: Add name-fallback tests (RED)** - `fe5c1b7` (test)
2. **Task 2: Implement name-fallback in resolveQr (GREEN)** - `6599cf6` (feat)

## Files Created/Modified
- `src/agents/alerter/src/farmos/qr.js` - resolveQr extended with name-fallback, D-06/D-08 comment block
- `src/agents/alerter/test/farmos/qr.test.js` - 3 new tests (name hit, both-miss, http error no fallback), updated existing both-miss expectation

## Decisions Made
- Transport failures (http_* on id_tag) do NOT trigger the name fallback. An HTTP error is a transport problem, not an empty-result miss. Test D codifies this.
- Both-miss returns `path: 'name'` (reflects the last lookup attempted, consistent with the name-fallback path being the terminal branch).
- Updated existing "no rows match" test expectation from `path: 'id_tag'` to `path: 'name'` -- the old expectation was correct pre-fallback but becomes incorrect once the fallback is wired (empty id_tag now always proceeds to name lookup).

## Deviations from Plan

None -- plan executed exactly as written. The existing "both-miss" test update (changing `path: 'id_tag'` to `path: 'name'`) was anticipated by the plan's RED task (it said to verify existing tests still pass in test setup, and the updated assertion is the correct behavior post-implementation).

## Issues Encountered
- Worktree at `/mnt/slime-kingdom/opt/mushy/.claude/worktrees/agent-ac0c977560ceb3a4e` had no node_modules. Ran `npm install` there before tests could execute. Not a blocker.

## Next Phase Readiness
- `resolveQr` is ready for Plan 43-03 (normalize.js) which calls it for `source_qr_codes` resolution in the harvest chain.
- Plan 43-05 chain integration Test 5 (harvest) can now resolve block names (e.g., `260512_DT_11`) via the name-fallback path without id_tag values being required.

---
*Phase: 43-phase-38-40-schema-normalizer-chain-integration-tests*
*Completed: 2026-05-16*
