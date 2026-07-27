---
phase: 57-signal-i-o
plan: "02"
subsystem: signal-i-o
tags: [signal-client, rate-cap, asyncio-lock, quote-primitive, group-translation, persist-hook, tdd]
dependency_graph:
  requires: [57-01]
  provides: [SignalClient.send, SignalClient.receive, SignalClient.fetch_attachment, SignalClient.accounts, SignalClient.is_valid_quote, SignalClient.ensure_groups_loaded, SignalClient.sends_this_hour]
  affects: [57-03, 57-04, 64-parity]
tech_stack:
  added: []
  patterns: [asyncio-lock-reserve-before-await, fail-open-try-except, httpx-rest-transport, quote-coercion-int-str-ts, group-lazy-cache, tdd-red-green]
key_files:
  created:
    - src/farm-agent/farm_agent/signal_io/__init__.py
    - src/farm-agent/farm_agent/signal_io/client.py
    - src/farm-agent/tests/test_signal_client.py
    - src/farm-agent/tests/test_signal_quote.py
    - src/farm-agent/tests/test_signal_ratecap.py
    - src/farm-agent/tests/test_signal_groups.py
  modified:
    - src/farm-agent/tests/test_signal_persist.py
decisions:
  - "asyncio.Lock reserve-before-await (option a): slot consumed inside lock before POST -- counts attempts not successes vs Node option. Phase-64 parity delta documented."
  - "is_valid_quote as @staticmethod on SignalClient (not a separate module) -- matches signal.js single-factory shape, minimizes parity diff"
  - "respx global patching used in tests (not MockRouter-as-transport) -- respx.mock context manager patches httpx globally"
  - "FND-02 guard: docstring text 'os.environ directly' would trip the grep in test_tenancy.py -- reworded to 'the environment directly'"
metrics:
  duration: "~35 minutes"
  completed: "2026-06-15"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 7
---

# Phase 57 Plan 02: SignalClient (transport + rate-cap + persist) Summary

Phase 57 Plan 02 ports `signal.js`'s `createSignalClient` factory to `farm_agent/signal_io/client.py` as the `SignalClient` class -- the wire-level Signal I/O choke-point. Covers SIG-01 (send/receive/fetch_attachment/accounts via httpx), SIG-02 (asyncio.Lock-guarded rate-cap + fail-open persist), and SIG-04 (intent-agnostic quote primitive).

## Tasks Completed

| Task | Type | Name | Commit | Result |
|------|------|------|--------|--------|
| 1 | auto/tdd | SignalClient transport + quote primitive (SIG-01, SIG-04) | 8080837 | GREEN -- 22 tests pass |
| 2 | auto/tdd | Rate-cap with asyncio.Lock + group-ID translation (SC#4, SC#2) | 985ce0d | GREEN -- 13 tests pass |
| 3 | auto/tdd | Fail-open durable persist hook (SIG-02, SC#1) | 31d5ade | GREEN -- 44+5skip pass |

## TDD Gate Compliance

**Task 1:**
- RED commit: `1b0e1e0` -- added failing tests for transport + quote (ModuleNotFoundError on import)
- GREEN commit: `8080837` -- client.py created; 22 tests pass

**Task 2:**
- Rate-cap and group translation tests added; passed immediately because client.py already implemented these in Task 1 (the three tasks share one `SignalClient` class, no separate stubs were needed).

**Task 3:**
- Extended test_signal_persist.py with SignalClient fail-open hook tests (Parts 3+4); all pass against existing client.py implementation.

## Decisions Made

- **Rate-cap append timing (Phase-64 parity delta):** Option (a) reserve-before-await is used: the slot is appended to `_send_history` inside the `asyncio.Lock` BEFORE the `await http.post(...)`. Node appends only on POST success (`signal.js:147`). This means the Python port counts *attempts* toward the cap, not *successes*. At 20/h this difference is inconsequential but is documented here for the Phase-64 parity author.
- **is_valid_quote as @staticmethod:** Kept inside `SignalClient` (not a separate module) to match `signal.js`'s single-factory shape and minimize parity diff surface.
- **respx global patching:** `respx.mock` context manager patches httpx globally. Tests do NOT pass the `MockRouter` as a transport argument to `httpx.AsyncClient` -- that would fail with `AttributeError: 'MockRouter' object has no attribute 'handle_async_request'`.
- **FND-02 docstring guard:** The initial docstring contained the literal string `"os.environ directly"`. The `test_no_other_module_reads_os_environ` grep in `test_tenancy.py` (FND-02 enforcement) trips on any `os.environ` occurrence including docstrings. Reworded to `"the environment directly"` (Rule 1 auto-fix).

## Verification

```
cd src/farm-agent && uv run pytest tests/test_signal_client.py tests/test_signal_quote.py tests/test_signal_groups.py tests/test_signal_ratecap.py tests/test_signal_persist.py -x
```
44 passed, 5 skipped (DB-gated, no :5434 available).

```
cd src/farm-agent && uv run pytest
```
92 passed, 10 skipped. No regression.

```
grep -n 'asyncio.Lock' src/farm-agent/farm_agent/signal_io/client.py
```
Line 84: `self._lock = asyncio.Lock()`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] FND-02 docstring false-positive**
- **Found during:** Full suite run after Task 3
- **Issue:** `client.py` docstring contained the literal string `"os.environ directly"` which triggered the FND-02 grep gate in `test_tenancy.py`
- **Fix:** Reworded docstring to `"the environment directly"` -- no logic change
- **Files modified:** `src/farm-agent/farm_agent/signal_io/client.py`
- **Commit:** 31d5ade

## Rate-Cap Parity Delta (for Phase-64 parity author)

**Python (this plan) vs Node (signal.js):**
- **Node:** `sendHistory.push(now)` at line 147, AFTER a successful POST. Failed sends do NOT consume a slot.
- **Python:** `self._send_history.append(now)` inside `async with self._lock:`, BEFORE the `await http.post(...)`. Failed sends DO consume a slot (reserve-before-await, option (a)).
- **Impact:** At 20/h cap, a burst of failures could briefly starve subsequent sends in the same hour window. In the Mossrock deployment (low-volume farm alerts) this is inconsequential.
- **Why option (a):** Simpler; option (b) (check+append-after-success) requires a second lock acquisition after the POST, or re-checking the cap inside a second lock scope, adding complexity for zero benefit at this scale.

## Threat Surface Scan

All mitigations from the plan's threat model implemented:

| Threat | Implementation |
|--------|----------------|
| T-57-02-01 DoS rate-cap | asyncio.Lock + reserve-before-await; `_current_cap()` dynamic hook |
| T-57-02-02 Quote tampering | `is_valid_quote` shape check; invalid shape → unquoted send + warn, no raise |
| T-57-02-03 PII in logs | `mask_number()` applied to all send log lines; group labels truncated to 8 chars |
| T-57-02-04 Quote warn dump | Warning logs quote shape only (ts/author/message -- author is e164, acceptable in warn) |

No new network endpoints or auth paths introduced beyond what the plan specifies.

## Self-Check: PASSED
