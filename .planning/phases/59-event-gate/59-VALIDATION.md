---
phase: 59
slug: event-gate
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-24
---

# Phase 59 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (via uv) |
| **Config file** | src/farm-agent/pyproject.toml |
| **Quick run command** | `cd src/farm-agent && uv run pytest -q tests/test_gate_*.py` |
| **Full suite command** | `cd src/farm-agent && uv run pytest -q` |
| **Estimated runtime** | ~3 seconds (mocked classifier; no real API) |

---

## Sampling Rate

- **After every task commit:** Run the quick command for the touched gate test file.
- **After every plan wave:** Run the full suite.
- **Before verification:** Full suite must be green.
- **Max feedback latency:** ~5 seconds.

---

## Per-Task Verification Map

> Refined by the planner per plan. Baseline expectations:

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 59-XX | rules | 2 | GATE-01 | T-44-04-01 | rule prefilter never raises; PII masked in logs | unit | `uv run pytest -q tests/test_gate_rules.py` | ❌ W0 | ⬜ pending |
| 59-XX | classifier | 2 | GATE-01 | T-44-04-01 | mocked-classifier fail-open on timeout/no_tool_use/schema_invalid; user JSON never in system prompt | unit | `uv run pytest -q tests/test_gate_classifier.py` | ❌ W0 | ⬜ pending |
| 59-XX | facade+corpus | 3 | GATE-01 | — | 0% false-positive on labeled negatives + ≥95% recall on the 90-row subset (deterministic, smart per-row mock) | unit | `uv run pytest -q tests/test_gate_event_gate.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

> All Wave 0 items are delivered by Plan 01 (wave 1). `wave_0_complete: true`.

- [ ] `tests/fixtures/gate/44-hand-classified-100.jsonl` — committed corpus fixture (copied from Phase 44). [Plan 01 Task 2]
- [ ] `tests/conftest.py` — shared `FakeAnthropicClient` (MagicMock-based) + gate fixtures. [Plan 01 Task 3]
- [ ] `anthropic>=0.45` added to pyproject.toml (Wave 0 dependency, package-legitimacy gate at execute time). [Plan 01 Tasks 1+2]

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real-Haiku accuracy on the full 100-corpus (incl. 10 holdout): 0% false-positive on labeled negatives + ≥95% event recall | GATE-01 | Needs a live ANTHROPIC_API_KEY and costs real API calls; deferred like the Phase 58 live-fire | marker/env-gated test (`tests/test_gate_live_fire.py`, Plan 04) runs the full corpus through the real classifier; assert the two parity metrics |

*The deterministic subset proves the gate WIRING + rule-coverage + fail-open; the real-Haiku run proves classifier ACCURACY and is operator-run.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (fixture, fake client, anthropic dep)
- [x] No watch-mode flags
- [x] Feedback latency < 5s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-06-24
