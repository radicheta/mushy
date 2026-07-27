---
phase: 60-extraction-pipeline
plan: "02"
subsystem: extraction
tags: [multimodal, seq_helper, pillow, b5-minting, tdd]
dependency_graph:
  requires: ["60-01"]
  provides: ["multimodal.py", "seq_helper.py"]
  affects: ["60-03"]
tech_stack:
  added: ["Pillow>=10.0 (already in pyproject.toml)"]
  patterns: ["fail-open async", "re.fullmatch anchored validation", "Pillow RGBA->RGB convert", "per-session SEQ counter"]
key_files:
  created:
    - src/farm-agent/farm_agent/extraction/multimodal.py
    - src/farm-agent/farm_agent/extraction/seq_helper.py
    - src/farm-agent/tests/extraction/test_multimodal.py
    - src/farm-agent/tests/extraction/test_seq_helper.py
  modified: []
decisions:
  - "downscale assertion: pixel count check not byte size (fixture is compressed; re-encode at q=85 produces larger bytes for already-compressed input)"
  - "extract_seqs_from_row: handles both Provenanced shape {value:[...]} and bare list for child_block_names"
  - "lookup_last_seq_for_date uses psycopg3 async pool.connection() / cursor pattern (not pool.execute)"
metrics:
  duration: "~15 minutes"
  completed: "2026-06-26"
  tasks_completed: 2
  files_created: 4
---

# Phase 60 Plan 02: multimodal.py + seq_helper.py Summary

Port two pure leaf extraction modules from Node.js: `multimodal.py` (Pillow downscale + fail-open image assembly) and `seq_helper.py` (B5 block-name minting with anchored re.fullmatch + per-session SEQ lookup).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Port multimodal.py | 186c64a | multimodal.py, test_multimodal.py |
| 2 | Port seq_helper.py | a9af514 | seq_helper.py, test_seq_helper.py |

## What Was Built

### multimodal.py

- `mime_from_path(p)`: extension-based MIME detection (.jpg/.jpeg -> image/jpeg, .png -> image/png, fallback application/octet-stream)
- `downscale_if_needed(buf, media_type)`: enforces 1.15MP + 5MB ceiling; RGBA/LA/P modes converted to RGB before JPEG save (PIL cannot save RGBA as JPEG)
- `read_image_to_base64(image_path, log)`: async, fail-open — any exception returns `{ok: False, reason}`, never raises; uses post-downscale media_type (not original)
- `build_content_blocks(text, transcript, images)`: assembles Anthropic content block list

### seq_helper.py

- `yyyymmdd_to_yymmdd("2026-05-22")` -> `"260522"`; raises ValueError on bad input
- `mint_child_block_names(yymmdd, species, start_seq, qty)`: uses `re.fullmatch(BLOCK_NAME_RE)` — NOT `re.match` — so `260522_SHI_1_EXTRA` is rejected (T-60-02-01)
- `seq_of(block_name)`: extracts trailing int; returns None for NEEDS_SEQ sentinel
- `extract_seqs_from_row(draft_json)`: walks both legacy `seeding.block_name` and `seeding_session.groups[].child_block_names` (Provenanced shape `{value:[...]}` + bare list); skip-on-error per group (T-60-02-04)
- `lookup_last_seq_for_date(pool, event_date, log)`: async psycopg3, fail-open

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Downscale test assertion: pixel count not byte size**
- **Found during:** Task 1 GREEN phase
- **Issue:** Plan spec said "strictly smaller byte buffer" but the paper-log.jpg fixture is a highly compressed JPEG (82KB for 1.44MP). Re-encoding at JPEG quality=85 after downscale produces 117KB — larger in bytes but fewer pixels. The real invariant is that pixel count is reduced to <= MAX_PIXELS.
- **Fix:** Changed assertion to `out_img.size[0] * out_img.size[1] <= MAX_PIXELS` and `< 900 * 1600` (original dimensions)
- **Files modified:** tests/extraction/test_multimodal.py
- **Commit:** 186c64a

## TDD Gate Compliance

Both tasks followed RED -> GREEN cycle:

| Phase | Task 1 commit | Task 2 commit |
|-------|--------------|--------------|
| RED (test) | 7b96dec | f2d2e62 |
| GREEN (feat) | 186c64a | a9af514 |

## Verification

```
cd src/farm-agent && uv run pytest -q tests/extraction/test_multimodal.py tests/extraction/test_seq_helper.py
```
Result: 37 passed (14 multimodal + 23 seq_helper)

Full suite: 232 passed, 19 skipped — no regressions.

## Known Stubs

None. Both modules are fully implemented with no placeholder paths.

## Threat Flags

None. No new network endpoints, auth paths, or schema changes introduced.

## Self-Check: PASSED

- [x] multimodal.py exists at src/farm-agent/farm_agent/extraction/multimodal.py
- [x] seq_helper.py exists at src/farm-agent/farm_agent/extraction/seq_helper.py
- [x] test_multimodal.py exists at src/farm-agent/tests/extraction/test_multimodal.py
- [x] test_seq_helper.py exists at src/farm-agent/tests/extraction/test_seq_helper.py
- [x] RED commits: 7b96dec, f2d2e62
- [x] GREEN commits: 186c64a, a9af514
- [x] All 37 new tests pass; full suite 232 passed, 19 skipped
