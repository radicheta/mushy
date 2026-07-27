---
phase: 59-event-gate
plan: "01"
subsystem: farm-agent/gate
tags: [anthropic, event-gate, prompts, test-infrastructure, foray-island]
dependency_graph:
  requires: []
  provides:
    - anthropic>=0.45 runtime dep (pinned in uv.lock)
    - farm_agent.gate package marker (Foray island)
    - farm_agent.gate.prompts (SYSTEM_PROMPT, CACHEABLE_SYSTEM_BLOCKS, HOLDOUT_ROW_IDS)
    - tests/fixtures/gate/44-hand-classified-100.jsonl corpus
    - FakeAnthropicClient + fake_anthropic_client fixture in conftest
  affects:
    - Plans 02 and 03 (consume gate package, prompts constants, and FakeAnthropicClient)
tech_stack:
  added:
    - anthropic==0.112.0 (>=0.45 pinned)
  patterns:
    - Foray island package (no chamber imports)
    - MagicMock-based fake client (mirrors FakeCaptureRepo pattern)
    - Verbatim prompt copy (cache threshold preservation)
key_files:
  created:
    - src/farm-agent/farm_agent/gate/__init__.py
    - src/farm-agent/farm_agent/gate/prompts.py
    - src/farm-agent/tests/fixtures/gate/44-hand-classified-100.jsonl
  modified:
    - src/farm-agent/pyproject.toml
    - src/farm-agent/uv.lock
    - src/farm-agent/tests/conftest.py
decisions:
  - "anthropic package approved as official first-party SDK (github.com/anthropics/anthropic-sdk-python) -- added after blocking-human legitimacy gate"
  - "gate/__init__.py is a bare package marker for Plan 01; create_event_gate re-export added in Plan 03"
  - "HOLDOUT_ROW_IDS is a flat list of 10 ULIDs only (no comment snippets from Node source) so len()==10 and holdout filter works correctly"
  - "SYSTEM_PROMPT copied verbatim at 21765 chars (Node source 22001 chars) -- above 20000 char conservative cache threshold"
metrics:
  duration: "~8 minutes"
  completed: "2026-06-24"
  tasks_completed: 3
  files_created: 3
  files_modified: 3
---

# Phase 59 Plan 01: Foundation -- anthropic dep, gate package, verbatim prompts, corpus fixture, FakeAnthropicClient

**One-liner:** Added `anthropic>=0.45` (0.112.0) behind a pre-approved supply-chain gate, created `gate/` Foray-island package with verbatim 21765-char SYSTEM_PROMPT clearing the Haiku 4.5 cache threshold, and wired a MagicMock-based `FakeAnthropicClient` into conftest for Plans 02/03.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Package legitimacy gate -- anthropic | (pre-approved) | -- |
| 2 | Add dep, gate package, prompts.py, corpus fixture | f97f40b | pyproject.toml, uv.lock, gate/__init__.py, gate/prompts.py, tests/fixtures/gate/44-hand-classified-100.jsonl |
| 3 | FakeAnthropicClient + fixture in conftest | 0acb65e | tests/conftest.py |

## Key Implementation Details

**SYSTEM_PROMPT cache threshold:** The verbatim copy is 21765 chars (Node source is 22001 chars; Python docstring overhead accounts for the minor delta). This clears the >20000 char conservative proxy for the >=4096-token Haiku 4.5 cache threshold. RESEARCH Pitfall 2 (dropping below threshold silently disables caching) is guarded.

**HOLDOUT_ROW_IDS:** The Node source interleaves 10 ULIDs with 10 comment snippets (20 array entries). The Python port is a flat list of the 10 ULID strings only, so `len(HOLDOUT_ROW_IDS) == 10` and the Plan-03 holdout filter `capture_id not in HOLDOUT_ROW_IDS` works correctly.

**FakeAnthropicClient shape:**
- `with_options(**kwargs)` returns `self` (mirrors `client.with_options(timeout=...)`)
- `messages` property returns `self` (so `client.messages.create(...)` chains)
- `async create(**kwargs)` records kwargs in `self.calls`, raises `raise_exc` if set, returns `content=[]` when `return_no_tool_use=True`, otherwise returns MagicMock with `content=[block]` where `block.type/name/input` are attributes (RESEARCH Pitfall 5 -- never dict keys)
- Default `tool_input = {"is_event": True, "kind": "event", "confidence": 0.95}`

**Foray island compliance:** `gate/__init__.py` and `gate/prompts.py` import nothing from `farm_agent.signal_io`, `farm_agent.capture`, `farm_agent.persistence`, or any chamber-coupled subpackage. `prompts.py` has no imports at all.

## Verification Results

```
foundation ok -- SYSTEM_PROMPT len=21765, holdout=10 entries, fixture=100 rows
148 passed, 17 skipped (full suite -- no Phase 56/57/58 regression)
```

## Deviations from Plan

None -- plan executed exactly as written. Task 1 (blocking-human legitimacy gate) was pre-approved by the orchestrator with PyPI/GitHub verification confirming `anthropic` as the official first-party Anthropic SDK.

## Threat Surface Scan

No new threat surface introduced beyond what the plan's threat model covers:
- T-59-SC: supply-chain gate executed (anthropic dep added only after human legitimacy approval)
- T-44-04-01: SYSTEM_PROMPT is inert constants (no logic, no string interpolation)
- T-59-01-01: corpus fixture contains only hand-classified public-shape data with masked senders from Phase 44 source; no new secrets

## Self-Check: PASSED

Files exist:
- src/farm-agent/farm_agent/gate/__init__.py: FOUND
- src/farm-agent/farm_agent/gate/prompts.py: FOUND
- src/farm-agent/tests/fixtures/gate/44-hand-classified-100.jsonl: FOUND
- src/farm-agent/pyproject.toml (modified): FOUND

Commits:
- f97f40b: FOUND (feat(59-01): add anthropic dep, gate package, prompts.py verbatim, corpus fixture)
- 0acb65e: FOUND (feat(59-01): add FakeAnthropicClient + fake_anthropic_client fixture to conftest)
