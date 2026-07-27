---
phase: 60-extraction-pipeline
plan: "01"
subsystem: farm-agent/extraction
tags: [extraction, prompts, fixtures, test-infra, pillow]
dependency_graph:
  requires: []
  provides:
    - farm_agent.extraction.prompts (CACHEABLE_SYSTEM_BLOCKS, cacheable_few_shot, SYSTEM_PROMPT)
    - tests/fixtures/extraction/seeding-session-may22 (4 files)
    - tests/conftest.FakeAnthropicClientForExtractor
    - Pillow>=10.0 runtime dep
  affects:
    - plans 60-02, 60-03 (depend on prompts.py + fixture + fake)
tech_stack:
  added:
    - Pillow 12.2.0 (image downscale for extraction pipeline)
  patterns:
    - Foray island: prompts.py has no cross-package imports
    - Multi-call fake: sequence-driven responses list, distinct block.id per call
key_files:
  created:
    - src/farm-agent/farm_agent/extraction/prompts.py
    - src/farm-agent/tests/extraction/__init__.py
    - src/farm-agent/tests/fixtures/extraction/seeding-session-may22/transcript.txt
    - src/farm-agent/tests/fixtures/extraction/seeding-session-may22/paper-log.jpg
    - src/farm-agent/tests/fixtures/extraction/seeding-session-may22/text-followup.txt
    - src/farm-agent/tests/fixtures/extraction/seeding-session-may22/expected-draft.json
  modified:
    - src/farm-agent/pyproject.toml (Pillow dep)
    - src/farm-agent/tests/conftest.py (FakeAnthropicClientForExtractor)
decisions:
  - "Used copy.deepcopy in cacheable_few_shot() mirroring JS cacheableFewShot() -- Foray island rule allows stdlib"
  - "block.id uses pre-increment index (tu_call_0, tu_call_1...) so retry turns pair tool_use_id against first call's id"
  - "asyncio import in conftest.py was pre-existing (unused); left as-is per surgical-changes rule"
metrics:
  duration: "~8 minutes"
  completed: "2026-06-26T15:40:00Z"
  tasks_completed: 3
  files_changed: 8
---

# Phase 60 Plan 01: Foundation (Pillow + prompts.py + fixture + FakeAnthropicClientForExtractor) Summary

Laid the Wave 0 foundation: Pillow runtime dep added (legitimacy pre-approved), Node extraction system prompt ported verbatim into Python prompts.py, May-22 seeding-session fixture copied byte-for-byte, and FakeAnthropicClientForExtractor multi-call fake added to conftest.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Add Pillow>=10.0 to pyproject.toml + uv sync | 56d60e2 |
| 2 | Port Node system prompt + FEW_SHOT verbatim into prompts.py | 0894764 |
| 3 | Copy May-22 fixture + FakeAnthropicClientForExtractor in conftest | 676c3e0 |

## Verification Results

- `import PIL; PIL.__version__` -> 12.2.0 (installed in workspace venv)
- `SYSTEM_PROMPT` length: 7258 chars (>1000, cache threshold safe)
- `cacheable_few_shot()` returns 12 messages; `tu_fewshot_6` present
- `CACHEABLE_SYSTEM_BLOCKS[0]['cache_control']` == `{'type': 'ephemeral'}`
- `paper-log.jpg` opens at (900, 1600)
- `expected-draft.json` loads without error
- `FakeAnthropicClientForExtractor` importable from `tests.conftest`
- Test suite: 195 passed, 19 skipped (no regressions)

## Deviations from Plan

None -- plan executed exactly as written. The Pillow checkpoint was pre-approved by the user in the prompt; no stop occurred.

## Known Stubs

None. This plan ships only constants, fixture files, and a test fake -- no data flows to the UI.

## Threat Flags

None new. The Pillow supply-chain threat T-60-SC was mitigated via human-verify (pre-approved). The expected-draft.json was copied byte-for-byte (T-60-01-01 mitigated). SYSTEM_PROMPT is a static cacheable block with no farmer text (T-44-04-01 mitigated).

## Self-Check: PASSED

Files exist:
- src/farm-agent/farm_agent/extraction/prompts.py: FOUND
- src/farm-agent/tests/fixtures/extraction/seeding-session-may22/paper-log.jpg: FOUND
- src/farm-agent/tests/fixtures/extraction/seeding-session-may22/expected-draft.json: FOUND
- src/farm-agent/tests/conftest.py (FakeAnthropicClientForExtractor): FOUND

Commits exist:
- 56d60e2: FOUND
- 0894764: FOUND
- 676c3e0: FOUND
