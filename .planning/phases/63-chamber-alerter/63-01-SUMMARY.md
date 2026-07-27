# Phase 63 — Plan 01 Summary

**Status:** COMPLETE
**Date:** 2026-07-25
**Branch:** `feat/phase-63-chamber-alerter`

---

## What shipped

### Task 1 — Wire import-linter into pytest and fix the contract it exposes
**Commit:** `e9d0da0` — `fix(63): repair .lint-imports source_modules and run it in pytest`

- New `src/farm-agent/tests/test_import_linter_contract.py::test_lint_imports_exits_zero`
  — runs `uv run lint-imports --config .lint-imports` as a subprocess and asserts
  exit 0 + `"1 kept, 0 broken"`.
- `.lint-imports` `source_modules` corrected to the real 8-package set: dropped
  `farm_agent.llm` (never existed), `farm_agent.farmos_client` → `farm_agent.farmos`,
  added the missing `farm_agent.gate`.
- Header comment rewritten: the Phase 56 "Do NOT add import-linter to the pytest
  run until Phase 63" note is now stale and was replaced with the activation note.
- `forbidden_modules = farm_agent.chamber` left untouched (correct as-is, D-00).

**RED observed:**
```
AssertionError: lint-imports failed (exit 1).
--- stdout ---
Module 'farm_agent.farmos_client' does not exist.
assert 1 == 0
```
This confirms the plan's claim: import-linter 2.11 hard-errors on an unresolvable
`source_modules` entry, so the seam contract had **never actually run** since Phase 56.

### Task 2 — Close the FORAY_PACKAGES grep-scope hole and make it self-auditing
**Commit:** `e7051d8` — `fix(63): scan all 8 Foray packages in the seam gate, guard against drift`

- `FORAY_PACKAGES` grown from 3 to 8 entries (added `signal_io`, `confirm`,
  `farmos`, `capture`, `gate`). `farm_agent/chamber` deliberately absent.
- New `test_foray_packages_covers_every_package_on_disk` derives the expected set
  from the filesystem, discarding `farm_agent/chamber`, and asserts both directions
  (missing + stale). Package 9 can no longer land un-scanned.
- The three pre-existing tests were not modified.

**RED observed:**
```
AssertionError: FORAY_PACKAGES does not scan these real packages:
['farm_agent/capture', 'farm_agent/confirm', 'farm_agent/farmos',
 'farm_agent/gate', 'farm_agent/signal_io'].
The seam gate is blind to them — add them to the list.
```
Exactly the five packages the plan predicted.

---

## Verification

| Check | Result |
|-------|--------|
| `uv run lint-imports --config .lint-imports` | exit 0, `Contracts: 1 kept, 0 broken` |
| `uv run pytest tests/test_foray_seam.py -v` | 4 passed (incl. both negative controls) |
| `uv run pytest tests/test_import_linter_contract.py -x` | 1 passed |
| `uv run pytest tests/ -q` | **647 passed, 36 skipped** (baseline was 645 + 36) |

Drift-guard spot-check: removing `farm_agent/gate` from the list turned
`test_foray_packages_covers_every_package_on_disk` RED as designed; entry restored.

---

## Deviations

- **Spot-check restore was heavy-handed.** The drift-guard spot-check (Task 2
  acceptance criterion 3) was restored with `git checkout` on the whole file,
  which reverted both of the task's uncommitted edits. Both were re-applied and
  re-verified (4 passed) before committing. No net effect on the shipped code.

---

## Plan assertions checked against source

Every factual claim in the plan's `<interfaces>` "Current (broken) state" block
held true against the tree:

- `.lint-imports` did list `farm_agent.farmos_client` + `farm_agent.llm` and omit
  `farm_agent.gate` — confirmed.
- import-linter 2.11 does hard-error on nonexistent `source_modules` — confirmed by
  the RED output.
- `FORAY_PACKAGES` did hold only 3 entries with the stale "not created this phase"
  comment — confirmed.
- The three existing seam tests read `FORAY_PACKAGES` and needed no body changes —
  confirmed (all 3 still pass unmodified).

Nothing the plan asserted turned out false.

---

## Produced for later plans

- `uv run lint-imports --config .lint-imports` is green and re-runnable by Plan 08
  once `chamber/` exists.
- `tests/test_import_linter_contract.py::test_lint_imports_exits_zero` — standing CI gate.
- `tests/test_foray_seam.py::FORAY_PACKAGES` — the 8-entry list. Plan 03 creates
  `farm_agent/chamber/`, which must **NOT** be added to it; the drift guard already
  discards `chamber` so no change will be needed there.
