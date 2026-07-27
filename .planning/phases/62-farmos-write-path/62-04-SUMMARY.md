---
phase: 62-farmos-write-path
plan: "04"
subsystem: farmos/fidelity-gate
tags: [tdd, fidelity-gate, strain-guard, regression, csv, tenant-config]
dependency_graph:
  requires: ["62-01"]
  provides: ["fidelity_gate.check_fidelity", "fidelity_gate.load_fidelity_csv", "fidelity_gate.render_fidelity_ask_back", "TenantConfig.fidelity_csv_path"]
  affects: ["farmos.commit_watchdog (Plan 11 wires gate)"]
tech_stack:
  added: []
  patterns: ["pure-gate-function", "csv-stdlib-no-external-dep", "TDD-RED-GREEN"]
key_files:
  created:
    - src/farm-agent/farm_agent/farmos/fidelity_gate.py
    - src/farm-agent/tests/test_farmos_fidelity_gate.py
    - src/farm-agent/tests/test_strain_poy_koy_regression.py
    - src/farm-agent/tests/fixtures/farmos/fidelity_csv_sample.csv
  modified:
    - src/farm-agent/farm_agent/tenancy/tenant.py
decisions:
  - "check_fidelity returns block_not_in_csv (not a hard-reject) when block absent from CSV -- CSV is non-authoritative (D-07)"
  - "render_fidelity_ask_back uses ASCII-only output with -- instead of em-dash per farmer message policy"
  - "fidelity_csv_path uses _pick layered loader with empty string default -- prod sets real path via env"
  - "POY regression test explicitly documents nearest=KOY is display-only (T-61-09 contract)"
metrics:
  duration: "~8 minutes"
  completed: "2026-06-28T22:57:46Z"
  tasks_completed: 2
  files_changed: 5
---

# Phase 62 Plan 04: CSV Fidelity Gate + POY->KOY Regression Guard Summary

Python port of the v1.11 commit-time CSV fidelity gate: pure check_fidelity() holds drafts as fidelity_cross_check_unverified with a farmer ask-back on strain disagreement, with block_not_in_csv pass-through for non-authoritative CSV absence.

## Commits

| Hash | Type | Description |
|------|------|-------------|
| 0418b6f | test | RED: failing tests for CSV fidelity gate + POY->KOY regression |
| da37f68 | feat | GREEN: fidelity_gate.py + tenant fidelity_csv_path config field |

## Tasks Completed

| # | Task | Commit | Key Files |
|---|------|--------|-----------|
| 1 (RED) | Failing tests + fixture CSV | 0418b6f | test_farmos_fidelity_gate.py, test_strain_poy_koy_regression.py, fidelity_csv_sample.csv |
| 2 (GREEN) | Gate implementation + tenant config | da37f68 | fidelity_gate.py, tenant.py |

## What Was Built

### fidelity_gate.py

Three pure functions:

- `load_fidelity_csv(path)` -- csv.DictReader; returns [] on missing/bad file (D-07 / T-62-11). No new pip packages (stdlib csv only, per critical constraint).
- `check_fidelity(draft, csv_rows)` -- pure gate returning one of three shapes:
  - `{"pass": True}` on agreement
  - `{"pass": False, "reason": "block_not_in_csv"}` on absence (pass-through, D-07)
  - `{"pass": False, "reason": "strain_mismatch", "hold_status": "fidelity_cross_check_unverified", "draft_strain": ..., "csv_strain": ..., "ask_back_msg": ...}` on disagreement (D-06)
- `render_fidelity_ask_back(block_name, draft_strain, csv_strain)` -- ASCII-only, two lines, no em-dash, names block and both strains.

### tenant.py changes

Added `fidelity_csv_path: str` to the `TenantConfig` frozen dataclass and loaded it in `load()` via `_pick(tenant_cfg, env, "FIDELITY_CSV_PATH", "")`. The empty-string default means existing deployments need no config change; prod sets the real CSV path via env. Plan 11 wires this into the commit watchdog.

### Regression guard

`test_strain_poy_koy_regression.py` contains 6 named tests asserting:
- `resolve_strain("POY", CURATED_14)["known"] is False`
- `resolve_strain("POY", CURATED_14)["code"] == "POY"` (never "KOY")
- nearest may be KOY (edit-distance 1) but is display-only (T-61-09 contract documented)

## Acceptance Criteria Verification

| Criterion | Result |
|-----------|--------|
| `grep -c "fidelity_cross_check_unverified" fidelity_gate.py` >= 1 | 5 occurrences |
| hold_status + ask_back_msg both present on mismatch | PASS (test_check_fidelity_mismatch_both_keys_present) |
| block_not_in_csv on absent block (never hard-reject) | PASS |
| `grep -c "fidelity_csv_path" tenant.py` >= 2 | 3 occurrences |
| POY known=False and code="POY" (never KOY) | PASS (6 regression tests) |
| render_fidelity_ask_back output has no em-dash | PASS |

## Test Results

```
21 passed (plan tests)
385 passed, 27 skipped (full suite -- 0 regressions)
```

## Deviations from Plan

None. Plan executed exactly as written.

- TDD RED gate confirmed (ImportError on missing module before implementation).
- TDD GREEN gate confirmed (21 tests pass after implementation).
- No new pip packages used (stdlib csv only, per critical constraint T-62-SC).
- No em-dashes in farmer-facing output (per [[feedback_no_em_dashes_in_artifacts]]).

## Known Stubs

None. fidelity_gate.py is a pure utility; it has no wired commit path yet (Plan 11 wires it into the commit watchdog as documented in the plan).

## TDD Gate Compliance

- RED gate: `test(62-04): add failing tests...` commit 0418b6f -- ImportError confirmed before implementation.
- GREEN gate: `feat(62-04): implement CSV fidelity gate...` commit da37f68 -- 21 tests pass.

## Self-Check: PASSED

- fidelity_gate.py: FOUND at src/farm-agent/farm_agent/farmos/fidelity_gate.py
- test_farmos_fidelity_gate.py: FOUND at src/farm-agent/tests/test_farmos_fidelity_gate.py
- test_strain_poy_koy_regression.py: FOUND at src/farm-agent/tests/test_strain_poy_koy_regression.py
- fidelity_csv_sample.csv: FOUND at src/farm-agent/tests/fixtures/farmos/fidelity_csv_sample.csv
- tenant.py fidelity_csv_path: CONFIRMED (3 occurrences)
- RED commit 0418b6f: CONFIRMED
- GREEN commit da37f68: CONFIRMED
