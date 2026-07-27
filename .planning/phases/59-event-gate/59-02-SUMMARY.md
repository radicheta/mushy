---
phase: 59-event-gate
plan: "02"
subsystem: farm-agent/gate
tags: [rules, classifier, haiku, tdd, foray-island, event-gate, pydantic]
dependency_graph:
  requires:
    - 59-01 (anthropic dep, gate package marker, FakeAnthropicClient fixture, prompts.py)
  provides:
    - farm_agent.gate.rules (rule_positive, rule_negative, STRAIN_RE, BLOCK_RE, ACK_RE)
    - farm_agent.gate.classifier (create_haiku_classifier, Classification, TOOL_DEF, build_classifier_input, find_tool_use_block)
    - tests/test_gate_rules.py (25 tests, all branches + 3 fidelity traps)
    - tests/test_gate_classifier.py (11 tests, success + 3 fail-open paths + call-shape assertions)
  affects:
    - Plan 03 (event_gate.py facade imports rules + classifier as leaf units)
tech_stack:
  added: []
  patterns:
    - Pure-function module with compiled regexes (mirrors pipeline.py lines 50-113)
    - Never-throws closure factory (mirrors transcribe_client.py exactly)
    - Pydantic model_validate replacing Node zod.safeParse
    - with_options(timeout=_timeout_s) for per-request timeout (Pitfall 1 guard)
key_files:
  created:
    - src/farm-agent/farm_agent/gate/rules.py
    - src/farm-agent/farm_agent/gate/classifier.py
    - src/farm-agent/tests/test_gate_rules.py
    - src/farm-agent/tests/test_gate_classifier.py
  modified: []
decisions:
  - "rule_negative uses >= 40 (not > 40) for body-length cutoff -- verbatim from Node >= operator (Pitfall 3)"
  - "ACK_RE includes explicit $ anchor so re.match does not produce phantom acks on 'ok then...' (Pitfall 4)"
  - "timeout passed only via client.with_options(timeout=_timeout_s), never in messages.create() body kwargs (Pitfall 1)"
  - "schema_invalid test uses confidence=1.5 (definite pydantic v2 le=1.0 violation, not a coercible type)"
  - "TDD: RED commits precede GREEN commits for both tasks (gate compliance verified in git log)"
metrics:
  duration: "~12 minutes"
  completed: "2026-06-24"
  tasks_completed: 2
  files_created: 4
  files_modified: 0
---

# Phase 59 Plan 02: Port rules.py + classifier.py with deterministic unit tests

**One-liner:** Ported Node rules.js and haiku-classifier.js verbatim to Python leaf units (rules.py pure prefilter, classifier.py never-throws Haiku factory) with 36 deterministic unit tests covering all branches and the three Node fidelity traps.

## Tasks Completed

| Task | Name | Commit (RED) | Commit (GREEN) | Files |
|------|------|-------------|----------------|-------|
| 1 | Port rules.py + test_gate_rules.py | 61d174a | 5b57d6c | rules.py, test_gate_rules.py |
| 2 | Port classifier.py + test_gate_classifier.py | a133718 | 803efc0 | classifier.py, test_gate_classifier.py |

## Key Implementation Details

**rules.py -- three fidelity traps guarded:**
1. Pitfall 3 (`>= 40`): `if len(body) >= 40: return {"hit": False}` -- a 40-char body does NOT trigger the negative rule. Test `test_rule_negative_40char_body_does_not_fire` asserts this.
2. Pitfall 4 (ACK_RE `$` anchor): `ACK_RE = re.compile(r"^(ok|yes|got it|thanks|gracias|si|si|)$", re.IGNORECASE)` -- the explicit `$` prevents `re.match` from matching `"ok then let me explain"`. Test `test_rule_negative_phantom_ack_does_not_fire` asserts this.
3. Pitfall 8 (Z-suffix `sent_at`): `sent_at.replace("Z", "+00:00")` before `fromisoformat()` is zero-cost insurance on all Python 3.x versions. Test `test_rule_negative_sent_at_z_suffix` asserts this.

**classifier.py -- timeout routing:**
`with_options(timeout=_timeout_s).messages.create(...)` -- timeout is a transport-level option, not a JSON body field. Passing it inside `messages.create()` kwargs would cause `400 BadRequestError: "timeout: Extra inputs are not permitted"` (the same live bug Node hit 2026-05-23 with `AbortSignal` in the request body). The `test_call_shape_no_timeout_in_body` test asserts `"timeout" not in kwargs` on the recorded call.

**classifier.py -- schema_invalid test coverage:**
`tool_input={"is_event": True, "kind": "greeting", "confidence": 1.5}` -- `confidence=1.5` definitively violates `Field(le=1.0)` in pydantic v2 and cannot be coerced. A string like `"notabool"` was intentionally avoided because pydantic v2 may coerce some non-bool strings.

**PII guard (T-59-02-01):**
`test_schema_invalid_warning_does_not_log_env_ctx` injects `"FARMER_PII_TEXT_SENTINEL"` as farmer text and asserts it does not appear in any log record. The classifier WARNING logs only the exception/reason.

## Verification Results

```
# Plan verification commands (all green):
cd src/farm-agent && uv run pytest -q tests/test_gate_rules.py tests/test_gate_classifier.py -x
36 passed in 0.47s

# Fidelity checks:
grep -n 'with_options' src/farm-agent/farm_agent/gate/classifier.py
# -> line 146: resp = await client.with_options(timeout=_timeout_s).messages.create(

grep -n '>= 40' src/farm-agent/farm_agent/gate/rules.py
# -> line 105: if len(body) >= 40:

# Full suite (no regressions):
uv run pytest -q
184 passed, 17 skipped
```

## TDD Gate Compliance

| Gate | Commit | Message prefix |
|------|--------|----------------|
| RED (rules) | 61d174a | `test(59-02): add failing test for rule_positive / rule_negative` |
| GREEN (rules) | 5b57d6c | `feat(59-02): port rules.py -- rule_positive / rule_negative` |
| RED (classifier) | a133718 | `test(59-02): add failing test for create_haiku_classifier` |
| GREEN (classifier) | 803efc0 | `feat(59-02): port classifier.py -- create_haiku_classifier` |

Both RED gates confirmed failing (ImportError on missing module) before GREEN commits.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test fixture timestamps were off by ~10 minutes**
- **Found during:** Task 1, first green run
- **Issue:** `_SENT_AT_29MIN_AGO`, `_SENT_AT_30MIN_AGO`, `_SENT_AT_31MIN_AGO` in test helpers were calculated relative to the wrong epoch. `_NOW_MS = 1_700_000_000_000` maps to `2023-11-14T22:13:20Z`, not `2023-11-14T22:23:20Z` as assumed. The 31-min test fired `hit: True` instead of `False`.
- **Fix:** Recomputed the three constants from the correct base datetime. `_SENT_AT_29MIN_AGO = "2023-11-14T21:44:20+00:00"`, `_SENT_AT_30MIN_AGO = "2023-11-14T21:43:20+00:00"`, `_SENT_AT_31MIN_AGO = "2023-11-14T21:42:20+00:00"`.
- **Files modified:** `tests/test_gate_rules.py`
- **Commit:** 5b57d6c (fixed inline before committing implementation)

## Threat Surface Scan

No new threat surface beyond the plan's threat model:
- T-44-04-01 (prompt injection): `build_classifier_input` returns farmer text as a separate compact-JSON user message block; `CACHEABLE_SYSTEM_BLOCKS` is never string-interpolated with `env_ctx`. Asserted in `test_call_shape_system_block_passed`.
- T-59-02-01 (PII in logs): `test_schema_invalid_warning_does_not_log_env_ctx` asserts WARNING does not log farmer text. No `env_ctx["text"]` appears in any log path.
- T-59-02-02 (API key): `classifier.py` never references `api_key`; the injected client already owns it.

## Self-Check: PASSED

Files exist:
- src/farm-agent/farm_agent/gate/rules.py: FOUND
- src/farm-agent/farm_agent/gate/classifier.py: FOUND
- src/farm-agent/tests/test_gate_rules.py: FOUND
- src/farm-agent/tests/test_gate_classifier.py: FOUND

Commits:
- 61d174a: FOUND (test(59-02): add failing test for rule_positive / rule_negative)
- 5b57d6c: FOUND (feat(59-02): port rules.py -- rule_positive / rule_negative from Node rules.js)
- a133718: FOUND (test(59-02): add failing test for create_haiku_classifier)
- 803efc0: FOUND (feat(59-02): port classifier.py -- create_haiku_classifier never-throws factory)
