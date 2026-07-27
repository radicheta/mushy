---
phase: 58-capture-transcription
plan: "02"
subsystem: capture
tags: [capture, transcription, persistence, httpx, psycopg3, fail-open]
dependency_graph:
  requires: [58-01]
  provides: [transcribe_client, capture_repo]
  affects: [58-03]
tech_stack:
  added: []
  patterns: [never-throws discriminated result, injected httpx closure, psycopg3 fail-open repo]
key_files:
  created:
    - src/farm-agent/farm_agent/capture/transcribe_client.py
    - src/farm-agent/farm_agent/capture/capture_repo.py
    - src/farm-agent/tests/test_transcribe_client.py
    - src/farm-agent/tests/test_capture_repo.py
  modified: []
decisions:
  - "transcribe_client holds injected httpx.AsyncClient in closure (mirrors SignalClient); not created per-call"
  - "capture_repo passes attachment_paths as list[str] directly (text[] not Jsonb); corpus_context always None"
  - "venv needs --extra dev sync (pytest/respx in dev extras); uv run pytest works after uv sync --extra dev"
metrics:
  duration_minutes: 25
  completed: "2026-06-23"
  tasks_total: 2
  tasks_completed: 2
  files_changed: 4
---

# Phase 58 Plan 02: transcribe_client + capture_repo -- leaf units for the capture pipeline

Never-throws httpx client to whisper-transcribe and fail-open psycopg3 INSERT for signal_capture -- the two separable Foray-seam leaf units Plan 03 will compose.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | Failing tests for transcribe_client | b352367 | tests/test_transcribe_client.py |
| 1 (GREEN) | implement transcribe_client | faf1a34 | farm_agent/capture/transcribe_client.py, tests/test_transcribe_client.py |
| 2 (RED) | Failing tests for capture_repo | 9556263 | tests/test_capture_repo.py |
| 2 (GREEN) | implement capture_repo | 97af895 | farm_agent/capture/capture_repo.py |

---

## Verification

- `uv run pytest tests/test_transcribe_client.py tests/test_capture_repo.py -x`: 10 passed, 5 skipped
- `uv run pytest` (full suite): 137 passed, 15 skipped, 0 failed (was 127 before this plan)
- `grep -n 'Jsonb' capture_repo.py`: only in comment (line 13 -- NOT applied to attachment_paths)
- `corpus_context` param in `_INSERT_SQL` is always `None` (hard-coded, line 96 in implementation)

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] venv missing dev extras (pytest/respx)**
- **Found during:** Task 2 GREEN phase
- **Issue:** `uv run pytest` resolved to pyenv shim pytest (a different Python without psycopg installed), not the venv's pytest. This caused `ModuleNotFoundError: No module named 'psycopg'` on import even though the venv had psycopg installed.
- **Fix:** Ran `uv sync --extra dev` to install pytest/respx/ruff into the venv. After that `uv run pytest` uses the venv's Python correctly.
- **Files modified:** uv.lock (updated by uv sync; no manual edit)
- **Note:** This was an environment state issue, not a code bug. The same issue would have affected any test run without the dev extras installed. The Plan 01 SUMMARY reported 127 tests passed, which means either Plan 01 ran in a different environment or the sync state differed. No code changes required.

---

## Known Stubs

None. Both modules are complete implementations. No placeholder text or wired-empty values.

---

## Threat Flags

None. All threat mitigations from the plan's threat model are implemented:
- T-58-02-01 (audio_path injection): paths are server-generated; whisper enforces ALLOWED_ROOT
- T-58-02-02 (corpus_context injection): hard-coded None in params tuple (line 96)
- T-58-02-03 (DB outage DoS): never-throw try/except; WARNING log only
- T-58-02-04 (whisper timeout blocks loop): httpx `timeout=` + never-throws on TimeoutException

## Self-Check: PASSED

- `src/farm-agent/farm_agent/capture/transcribe_client.py` exists: FOUND
- `src/farm-agent/farm_agent/capture/capture_repo.py` exists: FOUND
- `src/farm-agent/tests/test_transcribe_client.py` exists: FOUND
- `src/farm-agent/tests/test_capture_repo.py` exists: FOUND
- Commit b352367 (RED transcribe_client tests): FOUND
- Commit faf1a34 (GREEN transcribe_client): FOUND
- Commit 9556263 (RED capture_repo tests): FOUND
- Commit 97af895 (GREEN capture_repo): FOUND
- Test suite: 137 passed, 15 skipped, 0 failures
- Jsonb NOT applied to attachment_paths: CONFIRMED (grep shows only comment reference)
- corpus_context hard-coded None: CONFIRMED
