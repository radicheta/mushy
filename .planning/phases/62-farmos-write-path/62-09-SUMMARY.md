---
phase: 62-farmos-write-path
plan: "09"
subsystem: farmos-write-path
tags: [farmos, seeding, group-assets, activity-logs, image-upload, rollback]
dependency_graph:
  requires: ["62-05", "62-06", "62-07"]
  provides:
    - group_assets.py (find_group_asset_by_name, upsert_group_asset, delete_group_asset)
    - activity_logs.py (create_group_assignment_log, delete_activity_log)
    - commits/commit_seeding.py (QR path A/B, block upsert, seeding log)
    - commits/commit_seeding_session.py (group preflight, image attach, rollback)
  affects:
    - FWR-01 (seeding + seeding_session log types + image upload)
tech_stack:
  added: []
  patterns:
    - asset--group primitives with LRU name cache (cap-32 OrderedDict)
    - log--activity is_group_assignment=True for session membership
    - field-scoped octet-stream upload to /api/asset/group/{uuid}/image
    - reverse-order all-or-nothing rollback (_cleanup) with orphan accounting
    - collision-suffix name resolution (inoc YYYY-MM-DD, #2..#9) with mushy:draft idempotency
key_files:
  created:
    - src/farm-agent/farm_agent/farmos/group_assets.py
    - src/farm-agent/farm_agent/farmos/activity_logs.py
    - src/farm-agent/farm_agent/farmos/commits/commit_seeding.py
    - src/farm-agent/farm_agent/farmos/commits/commit_seeding_session.py
    - src/farm-agent/tests/test_farmos_group_assets.py
    - src/farm-agent/tests/test_farmos_commit_seeding.py
    - src/farm-agent/tests/test_farmos_commit_seeding_session.py
  modified:
    - src/farm-agent/farm_agent/farmos/commits/__init__.py
decisions:
  - group_assets uses lookup-or-create only (no merge layer in v1.10.1), mirroring JS Phase 52 decision
  - activity_logs is creation-only; duplicates on retry are acceptable (semantic-noop; Phase 51 upsert will dedupe later)
  - image attach targets group 'image' field via field-scoped binary route -- 'file' field rejects jpg; legacy two-step was falsified live (Phase 55B)
  - children carry parent=[sourceBlock] ONLY; no session-group edge on children (C4 -- lineage is an event, not a property)
  - _cleanup rollback order: membership log first, then assets in reverse, then session group last
  - attach failure is non-fatal by design (best-effort D-03); attachments_failed surfaced in envelope
metrics:
  duration: "~35 min"
  completed: "2026-06-28"
  tasks: 2
  files: 8
---

# Phase 62 Plan 09: Seeding Commit Family Summary

Faithful Python port of the Node.js seeding commit family: `group_assets.py` +
`activity_logs.py` + `commits/commit_seeding.py` + `commits/commit_seeding_session.py`.

## One-liner

Seeding family ported: group asset LRU cache, activity log membership writer,
single-inoc commit (QR path A/B), and multi-parent session commit with
field-scoped group image attach and reverse-order all-or-nothing rollback.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Port group_assets.py + activity_logs.py + commit_seeding.py | `1a6e9d8` | group_assets.py, activity_logs.py, commit_seeding.py, test_farmos_group_assets.py, test_farmos_commit_seeding.py |
| 2 | Port commit_seeding_session.py (image attach + rollback) | `cfdc5c4` | commit_seeding_session.py, test_farmos_commit_seeding_session.py |

## Verification

- All 42 new tests pass (16 group_assets, 10 commit_seeding, 16 commit_seeding_session)
- Full suite: 594 passed, 25 skipped, 0 failed (no regressions)
- `grep -c "/api/asset/group" commit_seeding_session.py` returns 4 (route present)
- No `/api/file/file` usage in any commit handler (grep-in-pytest acceptance gate passes)

## Acceptance Criteria Status

- [x] commit_seeding path B reuses resolved block (asset_ids empty); test asserts
- [x] ambiguous (>1 QR resolved) returns reason "ambiguous_qr_seeding"
- [x] missing strain returns "missing_strain"; missing block_name returns "missing_block_name"
- [x] upsert_group_asset on re-run with same name returns outcome="reused"; no POST
- [x] seeding log name is "Inoc <block_name or block_id>"; asset_ids carries only created blocks
- [x] image attach targets group 'image' field via upload_field_attachments to /api/asset/group
- [x] attach failure leaves ok=True with attachments_failed populated; test asserts
- [x] children carry parent=[sourceBlock] ONLY; test asserts parent length=1, not session-group id
- [x] child-block failure triggers reverse-order cleanup; session group DELETE is last; test asserts
- [x] idempotent re-commit: reuses session group matched by mushy:draft trailer; 0 duplicate POSTs

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Mock client fungi_type_uuids={} should replace defaults, not merge**
- **Found during:** Task 1 test run (test_unknown_strain_returns_fungi_type_not_found failed)
- **Issue:** Mock client used `{**DEFAULT, **(fungi_type_uuids or {})}` which meant an explicit `{}` still included all defaults. The JS test passes `{ fungiTypeUuids: {} }` to get an empty map (no strains resolve).
- **Fix:** Changed to `DEFAULT if fungi_type_uuids is None else fungi_type_uuids` so explicit empty dict replaces defaults.
- **Files modified:** `tests/test_farmos_commit_seeding.py`

**2. [Rule 3 - Blocking] Comment in commit_seeding_session.py triggered grep-based legacy-route test**
- **Found during:** Full suite run after Task 2
- **Issue:** An explanatory comment mentioned "upload-to-/api/file/file" which the existing `test_no_legacy_file_file_route_in_commits` grep caught.
- **Fix:** Rephrased comment to "two-step (upload + relationships.file PATCH)" without naming the legacy route path.
- **Files modified:** `src/farm-agent/farm_agent/farmos/commits/commit_seeding_session.py`

## Known Stubs

None -- all functions write real data and return real responses.

## Threat Flags

None -- the /api/asset/group surface was already in the plan's threat model (T-62-24/25/26).

## Self-Check: PASSED

Files created:
- /mnt/slime-kingdom/opt/mushy/src/farm-agent/farm_agent/farmos/group_assets.py -- FOUND
- /mnt/slime-kingdom/opt/mushy/src/farm-agent/farm_agent/farmos/activity_logs.py -- FOUND
- /mnt/slime-kingdom/opt/mushy/src/farm-agent/farm_agent/farmos/commits/commit_seeding.py -- FOUND
- /mnt/slime-kingdom/opt/mushy/src/farm-agent/farm_agent/farmos/commits/commit_seeding_session.py -- FOUND

Commits:
- 1a6e9d8 -- FOUND (feat(62-09): port group_assets.py + activity_logs.py + commit_seeding.py)
- cfdc5c4 -- FOUND (feat(62-09): port commit_seeding_session.py with image attach + rollback)
