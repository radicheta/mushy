---
phase: 57-signal-i-o
plan: "03"
subsystem: signal_io
tags: [routing, receive-loop, whitelist, attribution, sc5, sig-03]
dependency_graph:
  requires: ["57-01"]
  provides: [router.py, receive_loop.py]
  affects: ["57-04", "58-*"]
tech_stack:
  added: []
  patterns:
    - pure-function module (mirror tenant.py style)
    - asyncio sequential poll loop (mirror pool.py lifecycle)
    - per-envelope + per-tick try/except (loop-never-dies)
key_files:
  created:
    - src/farm-agent/farm_agent/signal_io/__init__.py
    - src/farm-agent/farm_agent/signal_io/router.py
    - src/farm-agent/farm_agent/signal_io/receive_loop.py
    - src/farm-agent/tests/test_signal_router.py
    - src/farm-agent/tests/test_signal_receive_loop.py
  modified: []
decisions:
  - "[57-03] collect_group_triggers returns {'dm'} for DM context (is_group=False), empty set for group with no triggers — mirrors receive-loop.js:154 but group with no trigger is empty not {'dm'}"
  - "[57-03] FND-02 grep gate catches 'os.environ' in docstrings — stripped the literal phrase from router.py + receive_loop.py comments to stay green"
  - "[57-03] receive_loop.py imports router as module (not individual symbols) to avoid circular import risk and ease future dispatch seam extension"
metrics:
  duration: "280s (4min 40s)"
  completed_date: "2026-06-15"
  tasks_completed: 2
  files_created: 5
  files_modified: 0
---

# Phase 57 Plan 03: Signal Router + Receive Loop Summary

**One-liner:** SIG-03 routing skeleton ported — whitelist gate, DM-vs-group classification, group-trigger collection with U+FFFC tolerance, SC#5 (unassigned) resolution, and sequential async poll loop with dispatch seam.

## What Was Built

### Task 1: `signal_io/router.py` (SIG-03, SC#5)

Pure-function module ported from `receive-loop.js:14-29, 124-156` and `capture.js:86`:

- `allowed_senders(config)` — builds whitelist set from `signal_sender`, `signal_recipient`, `signal_additional_senders`
- `is_whitelisted(source, config)` — gate check BEFORE any branch (T-57-03-01 / V4 / R7)
- `extract_source(env)` — reads `env["envelope"]["source"]`; returns `None` when absent
- `classify_envelope(env)` — dual-shape `dataMessage` read; `is_group` excludes UPDATE/QUIT (Risk #11)
- `collect_group_triggers(env, bot_phone)` — ports `collectGroupTriggers` verbatim: mention/command/quote triggers; command regex with optional `@mention` prefix and U+FFFC marker; quote accepts both `quote.author` and `quote.authorNumber` (Risk #9); DM context returns `{"dm"}`
- `resolve_farmer(source, config)` — `signal_farmer_map.get(source) or "(unassigned)"` (SC#5: unknown-but-whitelisted tagged, never dropped)
- `mask_number` re-exported from `tenant.py` (V7: never log full e164)

28 unit tests, all green.

### Task 2: `signal_io/receive_loop.py`

`ReceiveLoop` class porting `createReceiveLoop` from `receive-loop.js:47-70, 130-156`:

- `tick()`: `receive()` → sequential `for env in envelopes` (NEVER `asyncio.gather`) → whitelist gate → per-envelope `try/except dispatch` (loop-never-dies)
- Outer `try/except` around `receive()` itself — network errors log a warning, next tick proceeds (Pitfall 4)
- `start()`: creates `asyncio.Task` with `while True: tick(); sleep(poll_sec)`
- `stop()`: cancels + awaits task, swallows `CancelledError`; no-op if not started
- `dispatch` seam is the Phase-58 capture-pipeline entry point (not implemented here)

7 unit tests, all green.

## Verification

- `tests/test_signal_router.py` — 28 passed
- `tests/test_signal_receive_loop.py` — 7 passed
- Full suite — 85 passed, 10 skipped
- `grep 'gather' receive_loop.py | grep -v '^#'` — empty (no gather calls)
- FND-02 `os.environ` grep gate — green (stripped literal phrase from docstrings)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] FND-02 grep gate matched docstring text**
- **Found during:** Task 2 full suite run
- **Issue:** The `test_no_other_module_reads_os_environ` test greps source files for the literal string "os.environ". The docstrings in `router.py` and `receive_loop.py` contained the phrase "reads no os.environ" and "No os.environ reads in this module" — both matched the grep even though no actual env reads were present.
- **Fix:** Replaced the phrases with "config is the sole env-reader (FND-02)" in both files.
- **Files modified:** `router.py`, `receive_loop.py`
- **Commit:** `503dea7`

## Known Stubs

None. The dispatch seam in `receive_loop.py` is intentionally unimplemented here -- it is the Phase-58 capture-pipeline entry point by design (documented in plan scope boundary).

## Threat Surface Scan

No new network endpoints or trust boundaries beyond what the plan's threat model covers:
- T-57-03-01: whitelist gate enforced before any dispatch (mitigate -- green)
- T-57-03-03: mask_number on all log lines (mitigate -- green)
- T-57-03-04: per-envelope + per-tick try/except (mitigate -- green)
- T-57-03-02: quote-spoof guard deferred to confirm-path phase (accept -- documented)

## TDD Gate Compliance

- RED gate: `test(57-03)` commits `2430e33` and `d022b3c` (both tasks)
- GREEN gate: `feat(57-03)` commits `bb25c03` and `503dea7` (both tasks)
- REFACTOR gate: not needed (clean on GREEN)

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `2430e33` | test | add failing tests for signal_io/router.py (RED) |
| `bb25c03` | feat | implement signal_io/router.py -- whitelist, DM/group, triggers, (unassigned) |
| `d022b3c` | test | add failing tests for signal_io/receive_loop.py (RED) |
| `503dea7` | feat | implement signal_io/receive_loop.py -- sequential poll + dispatch seam |

## Self-Check: PASSED

- `src/farm-agent/farm_agent/signal_io/router.py` -- FOUND
- `src/farm-agent/farm_agent/signal_io/receive_loop.py` -- FOUND
- `src/farm-agent/tests/test_signal_router.py` -- FOUND
- `src/farm-agent/tests/test_signal_receive_loop.py` -- FOUND
- Commits `2430e33`, `bb25c03`, `d022b3c`, `503dea7` -- all present in git log
