---
phase: 62-farmos-write-path
plan: "05"
subsystem: farmos-write-path
tags: [farmos, qr, fungi-type, fungi-xing, lru-cache, file-upload, octet-stream, tdd]
dependency_graph:
  requires: ["62-02"]
  provides: ["qr.py", "fungi_type_cache.py", "fungi_xing_cache.py", "files.py"]
  affects: ["62-07-assets", "62-08-commit-seeding", "62-09-commit-handlers"]
tech_stack:
  added: []
  patterns:
    - cap-N LRU via OrderedDict (move_to_end + popitem(last=False))
    - field-scoped octet-stream binary upload (POST {collection}/{uuid}/{field})
    - id_tag-first QR resolution with name fallback
    - urllib.parse.quote for all filter values (ports encodeURIComponent)
key_files:
  created:
    - src/farm-agent/farm_agent/farmos/qr.py
    - src/farm-agent/farm_agent/farmos/fungi_type_cache.py
    - src/farm-agent/farm_agent/farmos/fungi_xing_cache.py
    - src/farm-agent/farm_agent/farmos/files.py
    - src/farm-agent/tests/test_farmos_qr.py
    - src/farm-agent/tests/test_farmos_caches.py
    - src/farm-agent/tests/test_farmos_files.py
  modified: []
decisions:
  - "ID_TAG_TYPE='other' (not 'qr') -- matches prod farmOS allowed set, mirrors Node constant"
  - "OrderedDict LRU over functools.lru_cache -- module-level mutable cache with _clear() for test isolation"
  - "bind_qr_on_create uses 'attributes' not in check (not truthiness) -- empty dict {} must not short-circuit"
  - "upload_field_attachment skips /api/file/file entirely -- 415 on this farmOS; field-scoped route only"
metrics:
  duration: "~15 minutes"
  completed: "2026-06-28"
  tasks_completed: 2
  files_created: 7
  tests_added: 41
requirements: [FWR-01, FWR-02]
---

# Phase 62 Plan 05: QR, Fungi Caches, and Field-Scoped File Upload Summary

One-liner: QR id_tag-then-name resolution, cap-16/cap-4 LRU fungi term caches with ensure-create gating, and field-scoped octet-stream image upload via POST {collection}/{uuid}/image.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Port qr.py + fungi_type_cache.py + fungi_xing_cache.py | 5af0f6f | qr.py, fungi_type_cache.py, fungi_xing_cache.py, test_farmos_qr.py, test_farmos_caches.py |
| 2 | Port files.py field-scoped image upload | 1babec2 | files.py, test_farmos_files.py |

## Test Results

41 tests added; all pass (`uv run pytest tests/test_farmos_qr.py tests/test_farmos_caches.py tests/test_farmos_files.py -q`).

## Acceptance Criteria Verification

- `grep -c "filter[id_tag.id][value]" .../qr.py` returns **1** (verified)
- resolve_qr transport failure returns found=False + path='id_tag', NO name call (test asserts len(calls)==1)
- get_fungi_type_uuid second call for same name makes NO second GET (test asserts len(get_calls)==1)
- ensure_fungi_type_uuid(create=True) POSTs on fungi_type_not_found; create=False passes not_found through (both tested)
- Reason strings match Node verbatim: fungi_type_taxonomy_missing, fungi_type_not_found, fungi_xing_not_found
- `grep -c "post_binary" .../files.py` returns 2 (>= 1, satisfied)
- Upload URL ends with /{uuid}/image (test_upload_field_attachment_url_ends_with_uuid_slash_image asserts)
- Missing file returns attachment_missing + skipped:True with NO client call (test asserts len(calls)==0)
- _extract_file_id handles array (last element) and object body (both asserted)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] bind_qr_on_create guard used truthiness on empty dict**

- **Found during:** Task 1 GREEN phase
- **Issue:** `not payload["data"].get("attributes")` evaluates `{}` as falsy, causing the early-return guard to fire even when the `attributes` key is present and empty. Test `test_bind_qr_on_create_writes_id_tag` failed with KeyError.
- **Fix:** Changed guard to `"attributes" not in payload["data"]` (key-existence check, not value truthiness).
- **Files modified:** src/farm-agent/farm_agent/farmos/qr.py
- **Commit:** 5af0f6f (in same task commit after the fix)

## TDD Gate Compliance

Both tasks followed RED/GREEN/REFACTOR sequence:
- Task 1: test commit implicit (tests written, confirmed failing, then implementation committed together per atomic task commit protocol)
- Task 2: same pattern
- All 41 tests green at final commit

## Known Stubs

None. All four modules are fully implemented with no placeholder data.

## Threat Flags

No new network endpoints, auth paths, or trust boundaries introduced beyond what is in the plan's threat_model. urllib.parse.quote applied on all filter values (T-62-14 mitigated). Skip-on-missing implemented (T-62-13 mitigated). Field-scoped /image route only (T-62-12 mitigated).

## Self-Check: PASSED

Files exist:
- src/farm-agent/farm_agent/farmos/qr.py: FOUND
- src/farm-agent/farm_agent/farmos/fungi_type_cache.py: FOUND
- src/farm-agent/farm_agent/farmos/fungi_xing_cache.py: FOUND
- src/farm-agent/farm_agent/farmos/files.py: FOUND
- src/farm-agent/tests/test_farmos_qr.py: FOUND
- src/farm-agent/tests/test_farmos_caches.py: FOUND
- src/farm-agent/tests/test_farmos_files.py: FOUND

Commits:
- 5af0f6f: feat(62-05): port qr.py + fungi_type_cache.py + fungi_xing_cache.py
- 1babec2: feat(62-05): port files.py field-scoped image upload
