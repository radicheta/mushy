---
phase: 58-capture-transcription
reviewed: 2026-06-23T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - src/farm-agent/farm_agent/capture/pipeline.py
  - src/farm-agent/farm_agent/capture/capture_repo.py
  - src/farm-agent/farm_agent/capture/transcribe_client.py
  - src/farm-agent/farm_agent/capture/capture_history.py
  - src/farm-agent/farm_agent/capture/retention.py
  - src/farm-agent/farm_agent/capture/__init__.py
  - src/farm-agent/farm_agent/boot.py
  - src/farm-agent/scripts/live_fire_58.py
findings:
  critical: 0
  warning: 3
  info: 2
  total: 5
status: fixed
fixed_at: 2026-06-23T00:00:00Z
fixed_findings: WR-01, WR-02, WR-03, IN-01, IN-02
---

# Phase 58: Code Review Report

**Reviewed:** 2026-06-23
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Eight files reviewed covering the capture pipeline factory, psycopg3 persistence repo,
httpx transcription client, capture history queries, retention loop, package init, boot
wiring, and live-fire harness. The core invariants -- D-03 never-throws, D-04 fail-open
transcription, D-05 disk-existence gate, D-06 no farmer acks, V7 PII masking, V12 no
client filename -- are all implemented correctly and consistently. The async HTTP pattern
satisfies D-02/SC#2. The psycopg3 parameterized INSERT and the interval arithmetic in
`mark_expired_older_than` are safe.

Three warnings were found: a silent `degraded` mis-report when the DB insert itself
fails, a ordering contract mismatch in `capture_history` that will mislead Phase 59+,
and a weak ULID check in the live-fire harness. No critical security vulnerabilities
were found.

---

## Warnings

### WR-01: DB insert failure not reflected in CaptureResult `degraded` field

**File:** `src/farm-agent/farm_agent/capture/pipeline.py:280`

**Issue:** `insert_capture` returns `{ok:True}` or `{ok:False, reason}` but the return
value is silently discarded. If the DB write fails, `degraded` remains `False` (or
whatever step 2/3 left it), and the returned `CaptureResult` will claim a clean capture.
Phase 59+ receives a capture_id for a row that does not exist in `signal_capture`. The
failure is logged inside `capture_repo` but the pipeline has no way to signal it to the
downstream consumer via the `degraded` flag.

This does not drop the message (D-03 holds), but it corrupts the `degraded` semantic:
Phase 59+ cannot distinguish "capture persisted with soft degradation" from "capture
was never written to the DB at all."

**Fix:** Capture the return value and set `degraded = True` if `ok` is False:

```python
persist_result = await _repo.insert_capture(pool, row)
if not persist_result.get("ok"):
    _log.warning(
        "[capture] insert_capture failed (D-04 fail-open): sender=%s reason=%s",
        mask_number(source),
        persist_result.get("reason"),
    )
    degraded = True
```

Update `result["degraded"]` after this block (it is already set from `degraded`).
Apply the same pattern to `record_reply_capture` (line 365) if `record_reply_capture`
ever gains a return value; for now its `None` return means the gap is lower stakes
but the same logic applies for consistency.

---

### WR-02: `capture_history.select_recent_by_sender` returns DESC but module docstring promises ASC

**File:** `src/farm-agent/farm_agent/capture/capture_history.py:13` (module docstring) vs `capture_history.py:38` (SQL)

**Issue:** The module-level docstring (line 13) states:

> "Return list[dict] rows in ASC order by timestamp."

The SQL for `select_recent_by_sender` uses `ORDER BY captured_at DESC` (line 38). Only
`select_recent_outbound_by_recipient` uses `ASC`. The function-level docstring (line 72)
correctly says "ordered captured_at DESC" -- but the module docstring is what a Phase 59+
author reads first to understand the contract.

A Phase 59+ prompt-builder that concatenates capture history under the assumption it
arrives oldest-first will produce an inverted context window (most-recent message first),
degrading LLM extraction quality in proportion to conversation length.

**Fix:** Correct the module docstring:

```python
Both functions:
  - Convert since_ms (epoch-ms int) to UTC datetime for the query.
  - Use async with pool.connection() + %s placeholders (psycopg3 pattern).
  - select_recent_by_sender: returns rows in DESC order (most-recent first).
  - select_recent_outbound_by_recipient: returns rows in ASC order (oldest-first).
  - Are fail-open: any exception returns [] with a WARNING (NEVER raises).
```

If the intent was ASC for both (to match the outbound query and match Node source
ordering), change the SQL: `ORDER BY captured_at ASC`. Verify against
`capture-history.js:selectRecentBySender` to confirm the Node ordering and make the
Python port match.

---

### WR-03: `_is_ulid()` accepts non-Crockford characters -- harness assertion is too loose

**File:** `src/farm-agent/scripts/live_fire_58.py:52`

**Issue:** `_is_ulid()` checks `isinstance(s, str) and len(s) == 26 and s.isalnum()`.
The Crockford base32 alphabet used by ULIDs excludes lowercase letters and the characters
I, L, O, U. A 26-character string containing any of those characters would be falsely
reported as a PASS by the harness, masking a misconfigured ULID generator (e.g., a UUID
with hyphens stripped, or an incorrect `python_ulid` API call).

This does not affect runtime behavior (the harness is read-only), but it means the SC#1
ULID assertion can pass on a row whose `id` is not actually a ULID.

**Fix:**

```python
import re

_ULID_RE = re.compile(r'^[0-9A-HJKMNP-TV-Z]{26}$')  # Crockford base32, uppercase only

def _is_ulid(s: object) -> bool:
    """Return True if s is a valid 26-char Crockford base32 ULID string."""
    return isinstance(s, str) and bool(_ULID_RE.match(s))
```

---

## Info

### IN-01: Foray island claim in `__init__.py` is inaccurate

**File:** `src/farm-agent/farm_agent/capture/__init__.py:4-5`

**Issue:** The package docstring states:

> "Foray island: this package has no imports from farm_agent.signal_io,
> farm_agent.persistence, or any chamber-specific module."

This is false. `pipeline.py` imports three names from `farm_agent.signal_io.router`:

```python
from farm_agent.signal_io.router import _read_dm, mask_number, resolve_farmer
```

The import is intentional -- the CONTEXT.md D-08 says "keep units separable" and `boot.py`
is explicitly allowed to cross boundaries, but `pipeline.py` is not `boot.py`. When the
Foray extraction team reads the `__init__.py` island claim, they will find a hidden
cross-package coupling in the pipeline module that contradicts it.

**Fix:** Either update the docstring to accurately describe the coupling, or move
`_read_dm`, `mask_number`, and `resolve_farmer` into a shared utility module (e.g.,
`farm_agent.signal_io.primitives`) that the capture package is explicitly allowed to
import, making the dependency explicit in the architecture rather than hidden behind
a false island claim.

---

### IN-02: Outer `except` in `retention_loop` is dead code

**File:** `src/farm-agent/farm_agent/capture/retention.py:57`

**Issue:** The `except Exception` block inside `retention_loop` (lines 57-58) will never
execute because `mark_expired_older_than` already catches and swallows all exceptions
internally (it is declared never-raises). The outer handler:

```python
except Exception as e:  # noqa: BLE001 -- retention failure is non-critical
    logger.warning("[retention] mark_expired_older_than failed: %s", e)
```

cannot be reached. This is harmless, but the dead `except` implies a misunderstanding of
`mark_expired_older_than`'s fail-open contract, and will quietly stay dead if the
`mark_expired_older_than` signature is ever changed to be raising.

**Fix:** Remove the outer try/except, since the callee is already fail-open. Or add a
comment acknowledging that the outer catch is defense-in-depth in case the callee
contract changes:

```python
# Defense-in-depth: mark_expired_older_than is already fail-open, but catch here
# in case the callee contract changes.
```

---

_Reviewed: 2026-06-23_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

**Finding counts: 0 Critical / 3 Warnings / 2 Info (5 total)**
