---
phase: 56-foundation
plan: "03"
subsystem: farm-agent
tags: [foray-seam, ci-gate, fnd-05, import-boundary]
dependency_graph:
  requires: ["56-01"]
  provides: ["FND-05 Foray seam gate armed in pytest"]
  affects: ["Phase 63 — chamber/ package; any foray package that might violate the boundary"]
tech_stack:
  added: []
  patterns:
    - "grep-in-pytest seam gate (zero external dependency, subprocess grep -rE)"
    - "import-linter .lint-imports contract committed as secondary gate for Phase 63"
key_files:
  created:
    - src/farm-agent/tests/test_foray_seam.py
    - src/farm-agent/.lint-imports
  modified: []
decisions:
  - "Used grep-in-pytest (Option B) as primary Phase 56 gate — zero dependency, runs in ms"
  - "import-linter contract (.lint-imports) committed but NOT wired into pytest run — chamber/ does not exist yet, contract is inert; activate in Phase 63"
  - "Added third test (test_seam_trips_on_bare_import_form) beyond plan minimum to cover bare import form explicitly"
metrics:
  duration: "~5 minutes"
  completed: "2026-06-15"
  tasks_completed: 1
  files_changed: 2
---

# Phase 56 Plan 03: Foray Seam CI Gate Summary

Grep-based Foray boundary gate wired into pytest (FND-05): any `from farm_agent.chamber` or `import farm_agent.chamber` in a foray package fails the build; armed-gate tests prove the grep is not vacuous.

## What Was Built

**`tests/test_foray_seam.py`** — Three pytest tests:
1. `test_no_chamber_imports_in_foray` — runs `grep -rE` over `farm_agent/tenancy`, `farm_agent/persistence`, `farm_agent/extraction` for the pattern `^import farm_agent\.chamber|from farm_agent\.chamber`. Passes vacuously in Phase 56 (no chamber/ exists). Will FAIL the build the instant a violation is introduced.
2. `test_seam_trips_on_violation` — constructs a tmp dir with `from farm_agent.chamber import ChamberAlerter`, runs the same grep, asserts it matches. Proves the gate is armed.
3. `test_seam_trips_on_bare_import_form` — same but with `import farm_agent.chamber`. Covers the second form from T-56-03-02.

**`src/farm-agent/.lint-imports`** — import-linter 2.11 `forbidden` contract: all foray packages (`tenancy`, `persistence`, `extraction`, `signal_io`, `confirm`, `farmos_client`, `capture`, `llm`) forbidden from importing `farm_agent.chamber`. Committed now as Phase 63 secondary gate. Not integrated into pytest run yet (chamber/ does not exist; contract is inert).

## Divergence Note (ROADMAP token)

ROADMAP.md success criterion 4 phrases the forbidden token as `from alerter.chamber` (the old Node alerter namespace). The real Python package is `farm_agent`, so the actual enforced pattern is `from farm_agent.chamber` / `import farm_agent.chamber`. Both the test file and the `.lint-imports` contract use the correct package name. The divergence is noted in a comment in the test file.

## Verification

```
uv run pytest tests/test_foray_seam.py -v
  tests/test_foray_seam.py::test_no_chamber_imports_in_foray PASSED
  tests/test_foray_seam.py::test_seam_trips_on_violation PASSED
  tests/test_foray_seam.py::test_seam_trips_on_bare_import_form PASSED
  3 passed in 0.01s
```

Acceptance criteria confirmed:
- `grep -c "chamber" tests/test_foray_seam.py` = 19 (>= 1)
- `grep -c "forbidden" .lint-imports` = 3 (>= 1)
- Test does not import any production module (pure subprocess grep)

## Deviations from Plan

None — plan executed as written. One addition beyond the two specified tests: `test_seam_trips_on_bare_import_form` was added as a third test to separately and explicitly prove the bare `import` form is caught (T-56-03-02 mitigation). The plan's `test_seam_trips_on_violation` only covered the `from` form; the third test makes the threat coverage explicit and standalone.

## Known Stubs

None. This plan delivers a pure static gate with no stub patterns.

## Threat Flags

No new network endpoints, auth paths, or file access patterns introduced. Gate is read-only (subprocess grep, tmp dir writes, no DB).

## Self-Check: PASSED

- `src/farm-agent/tests/test_foray_seam.py` — FOUND
- `src/farm-agent/.lint-imports` — FOUND
- commit `0ba71d9` — present in git log
