---
phase: 60-extraction-pipeline
plan: "04"
subsystem: farm-agent/extraction
tags: [extractor, live-fire, real-sonnet, operator-gated, accuracy-harness]
dependency_graph:
  requires: ["60-01", "60-02", "60-03"]
  provides:
    - tests/test_extraction_live_fire.py (real-Sonnet accuracy harness, operator-gated)
  affects:
    - Phase 61 (Confirm Loop) -- CI gate is hermetic suite only; live-fire is operator-run
tech_stack:
  added: []
  patterns:
    - EXTRACTION_LIVE_FIRE + ANTHROPIC_API_KEY double-gate (mirrors Phase-59 GATE_LIVE_FIRE pattern)
    - pytest.mark.live_fire + skipif for marker + env gating
    - try/finally client.close() pattern for real AsyncAnthropic
    - cache liveness via usage dict cache_creation_input_tokens / cache_read_input_tokens
key_files:
  created:
    - src/farm-agent/tests/test_extraction_live_fire.py
  modified:
    - src/farm-agent/pyproject.toml (live_fire marker description updated)
decisions:
  - "Used EXTRACTION_LIVE_FIRE (not GATE_LIVE_FIRE) as env gate -- extraction harness is a separate operator opt-in from the gate classifier harness"
  - "Assert child block names only, not KOY parent attribution -- mirrors the hermetic fixture replay assertion (60-03)"
  - "usage dict (not object) access via .get() -- sum_usage() returns a plain dict, not a Pydantic model"
  - "cache liveness assertion uses usage.get() with OR -- OR cache_read passes on warm cache second run"
metrics:
  duration: "~10 minutes"
  completed: "2026-06-26T16:30:00Z"
  tasks_completed: 1
  files_changed: 2
---

# Phase 60 Plan 04: Real-Sonnet Extraction Live-Fire Harness Summary

Added the operator-gated real-Sonnet accuracy harness: a double-gated (ANTHROPIC_API_KEY + EXTRACTION_LIVE_FIRE=1) pytest live_fire test that drives create_extractor against the real claude-sonnet-4-6 model on the 2026-05-22 fixture and asserts draft shape + child block names + cache liveness.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Author marker/env-gated real-Sonnet accuracy harness | 76c2542 | tests/test_extraction_live_fire.py, pyproject.toml |

## Task 2: Deferred Operator Real-Sonnet Validation

**Status:** Awaiting operator acknowledgement (checkpoint:human-verify, gate="blocking-human")

Task 2 is an acknowledgement checkpoint, not an implementation step. The real-Sonnet run is intentionally deferred and operator-run, exactly like the Phase 58/59 live-fires. No files change in Task 2.

To run the live-fire later:
```
export ANTHROPIC_API_KEY=<key>
export EXTRACTION_LIVE_FIRE=1
cd src/farm-agent && uv run pytest -q tests/test_extraction_live_fire.py -m live_fire -v
```

Record token/cache usage + any child-name mismatch as a finding.

## Verification Results

```
uv run --extra dev pytest -q tests/test_extraction_live_fire.py -m live_fire
```
Result: 1 skipped (skipped by default -- no env gate set)

```
uv run --extra dev pytest -q
```
Result: 247 passed, 20 skipped -- no regressions (was 19 skipped; +1 is the new live-fire skip)

## Success Criteria Check

- [x] test_extraction_live_fire.py exists, parses, and is skipped by default (CI-safe)
- [x] Double-gated: @pytest.mark.live_fire AND @pytest.mark.skipif(not ANTHROPIC_API_KEY or not EXTRACTION_LIVE_FIRE)
- [x] When run: asserts draft shape (5 groups / 11 children), exact child names (260522_SHI_1..3 + 260522_KOY_4..11), per-field provenance, cache liveness
- [x] Child names asserted, NOT KOY parent attribution
- [x] pyproject marker doc updated to reference EXTRACTION_LIVE_FIRE
- [x] Suite green: 247 passed, 20 skipped
- [ ] Task 2: Operator acknowledgement (deferred -- awaiting checkpoint response)

## Deviations from Plan

None -- plan executed exactly as written.

## Known Stubs

None.

## Threat Flags

None new. All STRIDE threats mitigated:
- T-60-04-01: api_key from env only; never hard-coded or logged; client closed in finally
- T-60-04-02: double-gated (live_fire marker + skipif on both ANTHROPIC_API_KEY and EXTRACTION_LIVE_FIRE); CI-safe

## Self-Check: PASSED

Files exist:
- src/farm-agent/tests/test_extraction_live_fire.py: FOUND
- src/farm-agent/pyproject.toml: updated

Commits exist:
- 76c2542: FOUND
