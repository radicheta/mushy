---
phase: 59-event-gate
plan: "04"
subsystem: farm-agent/gate
tags: [event-gate, live-fire, real-haiku, accuracy-validation, operator-run]
dependency_graph:
  requires:
    - 59-01 (anthropic dep, FakeAnthropicClient, corpus fixture)
    - 59-02 (create_haiku_classifier)
    - 59-03 (create_event_gate)
  provides:
    - tests/test_gate_live_fire.py (marker/env-gated real-Haiku accuracy harness)
    - live_fire pytest marker (registered in pyproject.toml)
  affects:
    - Plan 03 corpus-replay (complementary -- this plan covers the holdout rows the deterministic suite excludes)
tech_stack:
  added: []
  patterns:
    - @pytest.mark.live_fire + @pytest.mark.skipif double gate (mirrors Phase 58 live-fire pattern)
    - Direct classifier call for cache-liveness (gate facade does not propagate usage)
    - Operator-run deferred validation (non-CI-blocking)
key_files:
  created:
    - src/farm-agent/tests/test_gate_live_fire.py
  modified:
    - src/farm-agent/pyproject.toml
decisions:
  - "cache-liveness check goes through create_haiku_classifier directly (not via create_event_gate) because the gate facade does not propagate 'usage' from the classifier result"
  - "full 100-row corpus (no holdout filter) -- the holdout rows are the entire point of the live-fire run; the Plan-03 deterministic suite already covers the 90-row non-holdout subset"
  - "double skipif gate (ANTHROPIC_API_KEY AND GATE_LIVE_FIRE=1) guards against accidental paid runs in CI"
  - "Task 2 operator run deferred -- phase verification gates on the Plan-03 deterministic CI suite, not this harness (matches Phase 58 live-fire precedent)"
metrics:
  duration: "~5 minutes"
  completed: "2026-06-24"
  tasks_completed: 1
  tasks_deferred: 1
  files_created: 1
  files_modified: 1
---

# Phase 59 Plan 04: Real-Haiku live-fire accuracy harness + deferred operator validation

**One-liner:** Built the marker/env-gated `test_gate_live_fire.py` harness that replays all 100 corpus rows through the real Haiku 4.5 classifier (including holdout) asserting SC-1 (0% false-positive) + SC-2 (>=95% recall) + prompt-cache liveness; operator run is deferred pending a live ANTHROPIC_API_KEY.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Build live-fire harness + register marker | 305da60 | tests/test_gate_live_fire.py, pyproject.toml |

## Task 2: Deferred Operator Validation

**Status:** DEFERRED -- requires live ANTHROPIC_API_KEY and operator opt-in.

**Not a CI gate.** Phase 59 verification is the deterministic Plan-03 suite (193 passed, 18 skipped). This harness is operator-run validation only, matching the Phase 58 live-fire pattern.

**To run when ready:**
```bash
export ANTHROPIC_API_KEY=<live key>
export GATE_LIVE_FIRE=1
cd src/farm-agent && uv run pytest -q tests/test_gate_live_fire.py -v -m live_fire
```

**Expected outcome:** cache_creation_input_tokens > 0 (prompt-cache active), 0 false-positives on labeled skip rows, recall >= 95% on all 100 rows (including 10 holdout rows). If recall < 95% or any labeled-negative slips through, record the failing capture_ids as a classifier accuracy finding.

**Cost note:** ~100 Haiku API calls with ~21KB cached system prompt each. Record usage token totals for the milestone cost ledger.

## Key Implementation Details

**Double env gate (T-59-04-02 compliance):**
```python
@pytest.mark.live_fire
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY") or not os.environ.get("GATE_LIVE_FIRE"),
    reason="live-fire: requires ANTHROPIC_API_KEY + GATE_LIVE_FIRE=1",
)
```
CI never sets `GATE_LIVE_FIRE`, so the test is always skipped there regardless of `ANTHROPIC_API_KEY` presence.

**Cache-liveness via classifier, not gate:**
The classifier success shape returns `{"ok": True, ..., "usage": resp.usage}` where `resp.usage` carries `cache_creation_input_tokens` and `cache_read_input_tokens`. The gate facade does not propagate `usage` (gate returns `{gate, allow_extract, allow_convo}`), so the cache-liveness check calls `create_haiku_classifier(client=client)` directly on the first corpus row, then checks `usage.cache_creation_input_tokens > 0 or usage.cache_read_input_tokens > 0`.

**Full-100 corpus (NO holdout filter):**
The deterministic Plan-03 suite filters out the 10 `HOLDOUT_ROW_IDS` rows to prevent circular mocking. This live-fire harness intentionally includes all 100 rows -- the holdout rows are the point of the real run.

**SC-1/SC-2 replay goes through `create_event_gate`:**
The full replay uses `create_event_gate(create_haiku_classifier(client=client))` so the gate decision order (rule_positive -> rule_negative -> classifier -> confidence floor) is exercised end-to-end.

## Verification Results

```
# Default CI (no GATE_LIVE_FIRE):
cd src/farm-agent && uv run pytest -q tests/test_gate_live_fire.py -v
1 skipped in 0.84s  -- correctly skipped

# Marker registration:
uv run pytest -q --markers | grep live_fire
@pytest.mark.live_fire: real-API operator-run validation; skipped unless ANTHROPIC_API_KEY + GATE_LIVE_FIRE=1

# Full suite (no regressions):
uv run pytest -q
193 passed, 18 skipped  (was 17 skipped before this plan; +1 = live_fire test)
```

## Deviations from Plan

None -- plan executed exactly as written. `uv sync --extra dev` was run to install dev dependencies in the fresh worktree venv (same recurring deviation as Plan 03; no source changes).

## Threat Surface Scan

No new threat surface beyond the plan's threat model:
- T-59-04-01 (API key disclosure): key read from `os.environ["ANTHROPIC_API_KEY"]` only, never hard-coded or logged. The `client` object owns it internally.
- T-59-04-02 (accidental paid run): double gate (ANTHROPIC_API_KEY AND GATE_LIVE_FIRE=1) enforced by `@pytest.mark.skipif`. CI never sets `GATE_LIVE_FIRE`.
- T-59-04-03 (corpus PII to Anthropic): operator-initiated only; same farmer-text corpus already used for gate classification in production.

## Self-Check: PASSED

Files exist:
- src/farm-agent/tests/test_gate_live_fire.py: FOUND
- src/farm-agent/pyproject.toml (modified): FOUND

Commits:
- 305da60: FOUND (feat(59-04): add live-fire harness + register live_fire marker)
