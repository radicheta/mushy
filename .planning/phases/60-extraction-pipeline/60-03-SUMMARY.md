---
phase: 60-extraction-pipeline
plan: "03"
subsystem: farm-agent/extraction
tags: [extractor, retry, tool-use, boot-wiring, tdd, fnd-04]
dependency_graph:
  requires: ["60-01", "60-02"]
  provides:
    - farm_agent.extraction.extractor (create_extractor, build_initial_user_content, find_tool_use_block, pack_result, sum_usage, build_tool_spec)
    - tests/extraction/test_extractor.py (SC-1..SC-5 + call shape tests)
    - tests/extraction/test_extraction_fixture.py (May-22 fixture replay + FND-04 re-verify)
    - boot.py create_extractor wiring on shared singleton
  affects:
    - Phase 61 (Confirm Loop) -- extractor seam now available via pipeline extractor= kwarg
tech_stack:
  added: []
  patterns:
    - Never-throws factory pattern (mirror gate/classifier.py)
    - 2-call LLM retry with tool_result is_error=True + matching tool_use_id
    - tu_fewshot_6 closer as mandatory first user-turn block (Pitfall 8)
    - timeout via with_options only, never messages.create body (Pitfall 9)
    - sync/async observer callables via inspect.iscoroutine
key_files:
  created:
    - src/farm-agent/farm_agent/extraction/extractor.py
    - src/farm-agent/tests/extraction/test_extractor.py
    - src/farm-agent/tests/extraction/test_extraction_fixture.py
  modified:
    - src/farm-agent/farm_agent/boot.py (create_extractor import + wiring + extractor= kwarg to pipeline)
    - src/farm-agent/farm_agent/capture/pipeline.py (added optional extractor=None kwarg)
decisions:
  - "Used a named variable (first_validation_error) to capture the ValidationError str before the retry block to avoid Python scoping issue with except-as variable in nested try/except"
  - "FND-04 re-verify in test_extraction_fixture.py uses normalize_schema imported from test_schema_parity.py -- no duplication of the full diff logic"
  - "capture/pipeline.py extractor kwarg is additive-only (extractor=None default) -- no existing behavior changed, Phase 61 integration is deferred"
metrics:
  duration: "~20 minutes"
  completed: "2026-06-26T16:12:00Z"
  tasks_completed: 3
  files_changed: 5
---

# Phase 60 Plan 03: extractor.py + boot wiring + fixture replay + FND-04 re-verify Summary

Implemented `create_extractor` factory mirroring the Phase-59 classifier never-throws shape, with the mandatory tu_fewshot_6 tool_result closer, exact 2-call retry (initial + one retry on schema-invalid, terminal failure yields needs_review never an exception), timeout via `with_options` only, and sync/async observer support. Wired into `boot.py` on the shared `AsyncAnthropic` singleton. Fixture replay proves 1 seeding_session / 5 groups / 11 children / exact 260522_SHI_1..3 + 260522_KOY_4..11 block names / per-field provenance. FND-04 parity re-verified clean.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | Failing extractor tests (SC-1..SC-5 + call shape) | a6c50ff | tests/extraction/test_extractor.py |
| 1 (GREEN) | Implement extractor.py | 581ea47 | farm_agent/extraction/extractor.py |
| 2 | May-22 fixture replay test + FND-04 parity re-verify | 75b15ed | tests/extraction/test_extraction_fixture.py |
| 3 | Wire create_extractor into boot.py | 5104047 | boot.py, capture/pipeline.py |

## Verification Results

```
uv run pytest -q tests/extraction/test_extractor.py tests/extraction/test_extraction_fixture.py tests/test_schema_parity.py tests/test_boot.py
```
Result: 19 passed, 2 skipped (boot tests skip without test DB -- expected)

Full suite: 247 passed, 19 skipped -- no regressions.

## Success Criteria Check

- [x] create_extractor never throws; first user block is the tu_fewshot_6 closer
- [x] timeout is never a body kwarg (verified by test_call_shape_timeout_not_in_body)
- [x] 2-call retry: schema-invalid first -> one retry with tool_result is_error=True + matching tool_use_id -> resolves
- [x] second failure -> {ok:False, reason:schema_invalid, raw_first, raw_retry} (exactly 2 calls)
- [x] May-22 fixture replay: 1 seeding_session, 5 groups, 11 children, names 260522_SHI_1..3 + 260522_KOY_4..11, per-field provenance present (child names asserted, not parent attribution)
- [x] FND-04 parity gate re-verifies clean against the extractor's Submission schema (SC-4)
- [x] boot.py shares the single AsyncAnthropic singleton with the extractor

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Python scoping: ValidationError as-variable unavailable in retry block**
- **Found during:** Task 1 GREEN phase
- **Issue:** After `except ValidationError as e: ...`, the variable `e` is deleted by Python at the end of the except clause. The retry block attempted to use `str(e)` as the error content in the tool_result, causing `UnboundLocalError: cannot access local variable 'e' where it is not associated with a value`.
- **Fix:** Captured the error string before the except block ended: `first_validation_error = str(ve)` inside the except clause; used `first_validation_error` in the retry turn content.
- **Files modified:** farm_agent/extraction/extractor.py
- **Commit:** 581ea47

## TDD Gate Compliance

Task 1 followed RED -> GREEN cycle:

| Phase | Commit |
|-------|--------|
| RED (test) | a6c50ff |
| GREEN (feat) | 581ea47 |

## Known Stubs

None. The extractor is fully implemented. The `extractor=None` kwarg added to `create_capture_pipeline` is an intentional additive seam for Phase 61 -- the extractor is passed but not yet invoked from the pipeline (Phase 61 scope).

## Threat Flags

None new. All STRIDE threats in the plan's threat_model are mitigated:
- T-44-04-01: farmer text/transcript/image enter via messages[] only (not system prompt)
- T-60-03-01: extra='forbid' on all pydantic models; invalid input triggers retry then {ok:False}
- T-56-06-01: no api_key reference in extractor; injected client owns the key
- T-59-02-01: WARNING logs contain only exception/reason strings
- T-60-03-02: per-request timeout via with_options

## Self-Check: PASSED

Files exist:
- src/farm-agent/farm_agent/extraction/extractor.py: FOUND
- src/farm-agent/tests/extraction/test_extractor.py: FOUND
- src/farm-agent/tests/extraction/test_extraction_fixture.py: FOUND

Commits exist:
- a6c50ff: FOUND
- 581ea47: FOUND
- 75b15ed: FOUND
- 5104047: FOUND
