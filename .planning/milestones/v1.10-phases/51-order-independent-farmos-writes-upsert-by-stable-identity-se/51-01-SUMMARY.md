---
phase: 51
plan: 01
subsystem: farmos-upsert
tags: [wave-0, infrastructure, mock-client, audit-logger, fixture, probe]
dependency_graph:
  requires: []
  provides:
    - mock-client.patch
    - mock-client.delete
    - mock-client.GET-by-id
    - mock-client.force412-protocol
    - mock-client.revisionIds-seed
    - client.opts.headers-plumbing
    - audit-logger.outcome-dimension
    - audit-logger.conflicts-dimension
    - audit-logger.etag_source-dimension
    - multi-parent-inoc-trio.json fixture
    - dev-farmos-notes-roundtrip-receipt
  affects:
    - src/agents/alerter/test/farmos/mock-client.js
    - src/agents/alerter/src/farmos/client.js
    - src/agents/alerter/src/farmos/audit-logger.js
    - src/agents/alerter/test/farmos/audit-logger.test.js
    - src/agents/alerter/test/farmos/client.test.js
tech_stack:
  added: []
  patterns:
    - Object.assign header merge with caller-WINS semantics
    - JSON Set-like merge of attributes/relationships in mock
    - byte-identical PATCH→GET round-trip probe via curl
key_files:
  created:
    - src/agents/alerter/test/farmos/mock-client.test.js
    - src/agents/alerter/test/farmos/fixtures/multi-parent-inoc-trio.json
    - .planning/notes/2026-05-24-phase-51-notes-roundtrip-probe.md
  modified:
    - src/agents/alerter/test/farmos/mock-client.js
    - src/agents/alerter/src/farmos/client.js
    - src/agents/alerter/src/farmos/audit-logger.js
    - src/agents/alerter/test/farmos/audit-logger.test.js
    - src/agents/alerter/test/farmos/client.test.js
decisions:
  - "mock-client.knownAssetsByName accepts BOTH legacy string-id and new {id, attributes, relationships} object form so the 18 existing call sites keep working unchanged"
  - "audit payload extension preserves insertion order (outcome → conflicts → etag_source after reason) for grep stability and JSON-line readability"
  - "fixture event 2 expresses multi-parent (SHI_23 + SHI_26 → 3 children) as TWO groups[] entries because commit-seeding-session.js parses g.parent.value as a scalar — Plan 05 property tests will reconstruct the lineage from the expected_final.parent_lineage map"
  - "probe ran against dev with prod mushy-bot creds (same account exists on both Mossrock-named farmOS instances per [[reference_farmos_dev_vs_prod_on_elder_plops]])"
metrics:
  duration_minutes: 20
  completed_date: 2026-05-24
  tasks_completed: 4
  files_created: 3
  files_modified: 5
  test_count_before: 213
  test_count_after: 219
---

# Phase 51 Plan 01: Wave-0 Infrastructure Summary

Front-loaded every Wave-0 enabling change so Plans 02-06 can build and test
the upsert layer in isolation: mock-client gains PATCH/DELETE/GET-by-id +
412 protocol, real client plumbs opts.headers (If-Match), audit-logger
payload extends from 13 to 16 named keys, the multi-parent inoc fixture
ships, and a manual probe attests that `notes` field `\n---\n` separator
survives PATCH→GET byte-identical on dev farmOS.

## Tasks completed

| Task | Name | Commits | Files |
|------|------|---------|-------|
| 1 | Extend mock-client.js with patch / delete / GET-by-id / 412 protocol | `3bbd296` (RED), `5e2c095` (GREEN) | mock-client.js, mock-client.test.js |
| 2 | Plumb opts.headers through client._doFetch + extend audit-logger payload | `2152e72` (RED), `1095f61` (GREEN) | client.js, audit-logger.js, audit-logger.test.js, client.test.js |
| 3 | Author multi-parent inoc trio fixture | `2048a09` | fixtures/multi-parent-inoc-trio.json |
| 4 | CHECKPOINT — dev farmOS notes round-trip probe | `00ac6a1` | .planning/notes/2026-05-24-phase-51-notes-roundtrip-probe.md |

All six per-task commits live on `worktree-agent-a5c484f299f691151`.

## Verification

- `npx jest test/farmos/mock-client.test.js` — 8/8 ✓
- `npx jest test/farmos/audit-logger.test.js test/farmos/client.test.js` — 21/21 ✓
- Full farmos slice: `npx jest test/farmos/` — **219 passing**, 8 skipped, 1
  failure in `integration/extractor-to-commit.test.js` (pre-existing,
  unrelated: `@anthropic-ai/sdk` not resolvable under the npx Jest
  resolver — out of scope per fix-attempt-limit rules).
- Dev farmOS probe: PATCH `entry_A\n---\nentry_B\n---\nentry_C` to asset
  `SHI-260425-1`, GET back, hex match — byte-identical. Receipt committed.

## Acceptance criteria (all PASS)

- `grep -c "patch:" mock-client.js` ⇒ 1 (≥1 required) ✓
- `grep -c "delete:" mock-client.js` ⇒ 1 (≥1 required) ✓
- `grep -cE "force412Ids|_force412" mock-client.js` ⇒ 5 (≥1 required) ✓
- `grep -nE "outcome|conflicts|etag_source" audit-logger.js` ⇒ 6 matches in payload literal (≥3 required) ✓
- `grep -nE "Object.assign\(" client.js` ⇒ 2 (≥1 required, the headers merge) ✓
- `audit-logger.test.js` key-count assertion is 16 ✓
- multi-parent-inoc-trio.json: 3 events, 4 stub UUIDs, multi-parent lineage `["260118_SHI_23","260118_SHI_26"]` ✓
- dev farmOS notes round-trip byte-identical (hexdumps match: `656e7472795f410a2d2d2d0a656e7472795f420a2d2d2d0a656e7472795f43`) ✓

## Deviations from Plan

None — plan executed exactly as written. The probe (Task 4) succeeded
inline; the orchestrator's fallback path (write probe note documenting the
blocker if creds were unavailable) was not needed because:

1. Dev farmOS at `http://10.68.155.50:18080` was reachable.
2. The `mushy-bot` account auth in `.env` (port 8082 prod creds) also
   authenticates against dev (same Drupal user on both instances per
   [[reference_farmos_dev_vs_prod_on_elder_plops]]).
3. A non-load-bearing test asset (`SHI-260425-1`) was available to probe
   without touching farmer-tracked stubs.

## Self-Check: PASSED

Files exist:
- ✓ `src/agents/alerter/test/farmos/mock-client.test.js`
- ✓ `src/agents/alerter/test/farmos/mock-client.js` (modified)
- ✓ `src/agents/alerter/src/farmos/client.js` (modified)
- ✓ `src/agents/alerter/src/farmos/audit-logger.js` (modified)
- ✓ `src/agents/alerter/test/farmos/audit-logger.test.js` (modified)
- ✓ `src/agents/alerter/test/farmos/client.test.js` (modified)
- ✓ `src/agents/alerter/test/farmos/fixtures/multi-parent-inoc-trio.json`
- ✓ `.planning/notes/2026-05-24-phase-51-notes-roundtrip-probe.md`

Commits exist on branch `worktree-agent-a5c484f299f691151`:
- ✓ `3bbd296` test(51-01): add failing tests for mock-client patch/delete/GET-by-id/412
- ✓ `5e2c095` feat(51-01): extend mock-client with patch/delete/GET-by-id/412 protocol
- ✓ `2152e72` test(51-01): add failing tests for opts.headers plumbing + audit outcome/conflicts/etag_source
- ✓ `1095f61` feat(51-01): plumb opts.headers through client._doFetch + extend audit payload
- ✓ `2048a09` feat(51-01): add multi-parent inoc trio fixture for property tests
- ✓ `00ac6a1` docs(51-01): dev farmOS notes \n---\n round-trip probe — byte-identical PASS

## TDD Gate Compliance

Both behavior-adding tasks followed RED → GREEN sequence:

- Task 1: RED `3bbd296` (7 failing, 1 passing) → GREEN `5e2c095` (8/8 pass)
- Task 2: RED `2152e72` (8 failing, 13 passing) → GREEN `1095f61` (21/21 pass)

Task 3 (fixture) and Task 4 (probe receipt) are doc/data — no behavior
added, no TDD gate required.

## Downstream consumption

Plans 02-06 may now build against these surfaces:

- `client.patch(path, body, {headers:{'If-Match': revId}})` reaches fetch
- `auditLogger.logCommit(event, draft, {outcome, conflicts, etag_source})`
- `makeMockClient({force412Ids:['id1'], revisionIds:{name:42},
   knownAssetsByName:{name:{id, attributes, relationships}}})`
- `require('./test/farmos/fixtures/multi-parent-inoc-trio.json')` for
  property-test seeding (Plan 05)
- Dev farmOS confirmed byte-identical for `\n---\n` — Plan 02 may hard-code
  the separator with no normalize-on-read fallback
