---
phase: 58-capture-transcription
plan: "01"
subsystem: capture
tags: [foundation, ulid, fixtures, python-ulid]
dependency_graph:
  requires: []
  provides: [python-ulid dep, capture/__init__.py, conftest FakeCaptureRepo+fakes]
  affects: [58-02, 58-03]
tech_stack:
  added: [python-ulid>=3.1]
  patterns: [respx fixture, injected fake dict, toggle-raise repo]
key_files:
  created:
    - src/farm-agent/farm_agent/capture/__init__.py
  modified:
    - src/farm-agent/pyproject.toml
    - src/farm-agent/uv.lock
    - src/farm-agent/tests/conftest.py
decisions:
  - "python-ulid 3.1.0 added as pinned runtime dep after blocking-human legitimacy approval (T-58-SC)"
  - "A1 RESOLVED: from ulid import ULID; ULID.from_datetime(dt) is the timestamp-seeded call form"
  - "fake_transcribe_client uses Option B (injected dict) for pipeline tests; whisper_http uses respx for HTTP-layer tests"
metrics:
  duration_minutes: 10
  completed: "2026-06-23"
  tasks_total: 3
  tasks_completed: 3
  files_changed: 4
---

# Phase 58 Plan 01: Foundation -- python-ulid dep, A1 probe, capture package, conftest fakes

Wave-0 scaffolding: python-ulid pinned, ULID timestamp API probed and documented (A1), `capture/__init__.py` created as a Foray island, and three capture-suite fakes added to conftest.

## A1 RESOLVED -- python-ulid Timestamp-Seeded API

**Import path:** `from ulid import ULID`

**Timestamp-seeded call form (Plan 03 MUST use this):**
```python
from ulid import ULID
from datetime import datetime, timezone

dt = datetime.fromtimestamp(captured_at_ms / 1000, tz=timezone.utc)
capture_id = str(ULID.from_datetime(dt))
```

**Verification:** `str(ULID.from_datetime(datetime.fromtimestamp(1718900000000/1000, tz=timezone.utc)))` yields `01J0V6S18050GDEEMC0QFF43C0` (26 chars). The decoded `timestamp` field round-trips back to within 1 second of `captured_at_ms`.

**Also available:** `ULID.from_timestamp(epoch_seconds: float)` -- takes epoch seconds (not ms). The `from_datetime` form is preferred because it maps directly to `datetime.fromtimestamp(ms/1000, tz=timezone.utc)` which is already used throughout the capture pipeline.

**Package details:** python-ulid 3.1.0, PyPI, github.com/mdomke/python-ulid (Martin Domke), MIT, ~5 years active, 18 releases. Approved in T-58-SC blocking-human gate (pre-verified in execution prompt by user).

---

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Package legitimacy gate (pre-approved) | (checkpoint cleared in prompt) | -- |
| 2 | Add python-ulid + probe A1 + create capture/__init__.py | 0099365 | pyproject.toml, uv.lock, capture/__init__.py |
| 3 | Add FakeCaptureRepo, fake_transcribe_client, whisper_http to conftest | 07ccb49 | tests/conftest.py |

---

## Verification

- `grep -n 'python-ulid' src/farm-agent/pyproject.toml` returns line 11: `"python-ulid>=3.1",`
- `uv run pytest` (full suite): 127 passed, 10 skipped (DB-dependent skips are expected -- no test DB reachable at port 5434)
- Phase 56/57 tests: no regression

---

## Deviations from Plan

None -- plan executed exactly as written. Task 1 checkpoint was pre-approved by the user in the execution prompt with full verification detail (PyPI, GitHub, MIT, 3.1.0, legitimate).

---

## Known Stubs

None. This plan creates only scaffolding (dep + package marker + fakes). No data flows to UI.

---

## Threat Flags

None. T-58-SC (supply chain) was handled by the blocking-human gate in Task 1. T-58-01-01 (wrong ULID API) is resolved by the A1 probe documented above.

## Self-Check: PASSED

- `src/farm-agent/farm_agent/capture/__init__.py` exists: FOUND
- `src/farm-agent/pyproject.toml` contains python-ulid: FOUND
- `src/farm-agent/tests/conftest.py` contains FakeCaptureRepo: FOUND
- Commit 0099365 exists: FOUND
- Commit 07ccb49 exists: FOUND
- Test suite: 127 passed, 10 skipped, 0 failures
