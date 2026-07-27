---
phase: 60-extraction-pipeline
verified: 2026-06-26T00:00:00Z
status: human_needed
score: 4/4 must-haves verified (hermetic suite)
re_verification: false
human_verification:
  - test: "Real-Sonnet accuracy run on the live 2026-05-22 fixture"
    expected: >
      Running ANTHROPIC_API_KEY=<key> EXTRACTION_LIVE_FIRE=1 uv run pytest -q
      tests/test_extraction_live_fire.py -m live_fire -v should produce: 1 pass,
      draft type seeding_session, 5 groups, 11 children, exact child names
      260522_SHI_1..3 + 260522_KOY_4..11, per-field provenance present on each
      group field, and usage showing cache liveness (cache_creation_input_tokens
      OR cache_read_input_tokens > 0).
    why_human: >
      Requires a live ANTHROPIC_API_KEY and costs real API calls. Gated by
      EXTRACTION_LIVE_FIRE=1 env var. Deferred by design exactly like Phase 58/59
      live-fires -- the hermetic mocked-tool_use suite proves extractor WIRING,
      retry, schema, seq-minting, and multimodal assembly; the real-Sonnet run
      proves model EXTRACTION ACCURACY on the actual audio+photo fixture.
      Command: cd src/farm-agent && ANTHROPIC_API_KEY=<key> EXTRACTION_LIVE_FIRE=1
      uv run pytest -q tests/test_extraction_live_fire.py -m live_fire -v
---

# Phase 60: Extraction Pipeline Verification Report

**Phase Goal:** The Python multimodal extractor fuses text, audio transcript, and image into a
schema-valid draft via Claude tool-use, reproducing all Node extraction behaviors including
SeedingSession multi-parent shape, per-field provenance, retry logic, and B5 block-name minting.

**Requirements:** XTR-01, XTR-02, XTR-03

**Verified:** 2026-06-26
**Status:** human_needed
**Re-verification:** No -- initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC-1 | Replaying the 2026-05-22 audio+photo inoc session (mocked tool_use) produces one seeding_session draft, 5 groups, 11 children, correct 260522_SHI_1..3 / 260522_KOY_4..11 block names, per-field provenance | VERIFIED | `test_extractor_replay_may22_fixture` passes; asserts exact EXPECTED_CHILD_NAMES list + Provenanced shape on each group field |
| SC-2 | Schema-invalid LLM response triggers retry (tool_result is_error:true + correct tool_use_id); resolves on retry; 2nd failure yields needs_review dict NOT an exception | VERIFIED | `test_retry_resolves` confirms 2 calls + tool_result is_error+tool_use_id="tu_call_0"; `test_terminal_failure` confirms {ok:False, reason:"schema_invalid", raw_first, raw_retry} with no exception |
| SC-3 | BLOCK_NAME_RE uses re.fullmatch(); 260522_SHI_1_EXTRA rejected, 260522_SHI_1 passes | VERIFIED | `test_block_name_re_rejects_extra_segment` + `test_block_name_re_accepts_valid` both pass; seq_helper.py line 69 uses `re.fullmatch(BLOCK_NAME_RE, name)` |
| SC-4 | Structural diff of Python model_json_schema() vs Node SUBMISSION_JSON_SCHEMA is clean; build_tool_spec() passes SUBMISSION_JSON_SCHEMA directly | VERIFIED | `test_fnd04_parity_still_passes` green; `test_build_tool_spec_uses_submission_json_schema` asserts identity (`is` check) -- same object, not a copy |
| SC-1b (live-Sonnet accuracy) | Real claude-sonnet-4-6 API call on actual 2026-05-22 fixture produces correct shape | HUMAN-NEEDED | Deferred by design -- operator-run with EXTRACTION_LIVE_FIRE=1 |

**Score:** 4/4 hermetic must-haves verified. 1 human-needed item (deferred real-Sonnet run).

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/farm-agent/farm_agent/extraction/extractor.py` | Never-throws create_extractor factory with 2-call retry | VERIFIED | 373 lines, full implementation; with_options timeout, tool_choice forced, tu_fewshot_6 closer, ValidationError retry path |
| `src/farm-agent/farm_agent/extraction/multimodal.py` | Pillow downscale + fail-open image assembly | VERIFIED | 131 lines, full implementation; downscale_if_needed wraps in try/except, read_image_to_base64 never raises |
| `src/farm-agent/farm_agent/extraction/seq_helper.py` | B5 minting with re.fullmatch + DB lookup | VERIFIED | 203 lines, full implementation; mint_child_block_names + lookup_last_seq_for_date + extract_seqs_from_row |
| `src/farm-agent/farm_agent/extraction/prompts.py` | Node system prompt verbatim + cache_control + few-shot | VERIFIED | 60-01-SUMMARY confirms 7258 chars, cacheable_few_shot() returns 12 messages, tu_fewshot_6 present |
| `src/farm-agent/tests/extraction/test_extractor.py` | SC-1..SC-5 + call shape tests | VERIFIED | 17 tests, all pass |
| `src/farm-agent/tests/extraction/test_extraction_fixture.py` | May-22 fixture replay + FND-04 re-verify | VERIFIED | 4 tests, all pass |
| `src/farm-agent/tests/extraction/test_seq_helper.py` | BLOCK_NAME_RE fullmatch + minting + SEQ extraction | VERIFIED | 24 tests, all pass |
| `src/farm-agent/tests/extraction/test_multimodal.py` | Pillow downscale + fail-open | VERIFIED | 14 tests, all pass |
| `src/farm-agent/tests/test_extraction_live_fire.py` | Operator-gated real-Sonnet harness | VERIFIED (gated) | 1 skip (by design, double-gated ANTHROPIC_API_KEY + EXTRACTION_LIVE_FIRE) |
| `src/farm-agent/tests/fixtures/extraction/seeding-session-may22/` | 4 fixture files | VERIFIED | transcript.txt, paper-log.jpg, text-followup.txt, expected-draft.json all present |
| `src/farm-agent/farm_agent/boot.py` | create_extractor wired on shared singleton | VERIFIED | Line 91: `extractor = create_extractor(client=anthropic_client)`; line 93: passed to create_capture_pipeline as `extractor=extractor` |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `extractor.py:extract()` | `multimodal.build_content_blocks` | import + direct call | WIRED | line 40 import, line 140 call in build_initial_user_content |
| `extractor.py:extract()` | `prompts.CACHEABLE_SYSTEM_BLOCKS` | import | WIRED | line 41, used in base_req system= |
| `extractor.py:extract()` | `prompts.cacheable_few_shot()` | import + call | WIRED | line 41, called at line 283 |
| `extractor.py:extract()` | `schemas.submission.Submission.model_validate` | import | WIRED | line 42, called line 313 + 353 |
| `extractor.py:_call_with_observer` | `client.with_options(timeout=_timeout_s)` | factory closure | WIRED | line 243 -- timeout via with_options, NOT body kwarg (Pitfall 9 correct) |
| `extractor.py` retry turn | `block.id` for tool_use_id | attribute access | WIRED | line 329 `"tool_use_id": block.id` -- block.id not block.name (Pitfall 1 correct) |
| `boot.py` | `create_extractor` | import + factory | WIRED | line 45 import, line 91 call with shared anthropic_client |
| `boot.py` | `create_capture_pipeline(..., extractor=extractor)` | kwarg | WIRED | line 93; pipeline.py has `extractor: dict | None = None` at line 139 |
| `seq_helper.mint_child_block_names` | `re.fullmatch(BLOCK_NAME_RE)` | direct call | WIRED | line 69 `if re.fullmatch(BLOCK_NAME_RE, name) is None` |

---

### Data-Flow Trace (Level 4)

Not applicable for this phase -- the extractor is a factory returning a callable. Data flows from `captures[]` input into the Anthropic API call and back; no persistent rendering or UI surface exists in this phase. The pipeline extractor= seam is additive-only (Phase 61 will wire the actual invocation path from the pipeline state machine).

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full hermetic suite | `cd src/farm-agent && uv run pytest -q` | 254 passed, 20 skipped in 2.08s | PASS |
| SC-2 retry path specifically | `uv run pytest -q tests/extraction/test_extractor.py::test_retry_resolves tests/extraction/test_extractor.py::test_terminal_failure` | 2 passed | PASS |
| SC-3 BLOCK_NAME_RE fullmatch | `uv run pytest -q tests/extraction/test_seq_helper.py::test_block_name_re_rejects_extra_segment tests/extraction/test_seq_helper.py::test_block_name_re_accepts_valid` | 2 passed | PASS |
| SC-4 FND-04 parity | `uv run pytest -q tests/test_schema_parity.py tests/extraction/test_extraction_fixture.py::test_fnd04_parity_still_passes` | 5 passed | PASS |
| SC-1 May-22 fixture replay | `uv run pytest -q tests/extraction/test_extraction_fixture.py::test_extractor_replay_may22_fixture` | 1 passed | PASS |
| Live-fire harness | `uv run pytest -q tests/test_extraction_live_fire.py` | 1 skipped (gated by design) | PASS |

---

### Probe Execution

No `scripts/*/tests/probe-*.sh` probes declared for this phase. The hermetic pytest suite is the probe contract.

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| XTR-01 | 60-01, 60-03 | Multimodal extractor fuses text + audio transcript + image into a single draft via Claude tool-use; cacheable system prompt + few-shot turns | SATISFIED | prompts.py CACHEABLE_SYSTEM_BLOCKS with cache_control:ephemeral; build_content_blocks assembles text+transcript+image blocks; test_extractor_replay_may22_fixture passes |
| XTR-02 | 60-02, 60-03 | Schema-invalid model output triggers retry; multi-parent SeedingSession shape + per-field provenance reproduced | SATISFIED | 2-call retry path verified in test_retry_resolves; test_extractor_replay_may22_fixture asserts 5 groups, 11 children, Provenanced field shapes |
| XTR-03 | 60-02 | B5 block-name minting; BLOCK_NAME_RE anchored full-match; drafts persist to signal_draft | PARTIALLY SATISFIED | mint_child_block_names + re.fullmatch verified; draft persistence to signal_draft is an existing Phase 56/57 seam (not re-ported in Phase 60 -- extractor returns the draft dict; pipeline persistence is Phase 61 integration) |

---

### Code Review Fixes Verified

The 60-REVIEW.md documented 2 critical + 4 warning + 2 info findings, all marked fixed. Spot-checks confirm:

| Finding | Fix | Verified |
|---------|-----|---------|
| CR-01: lookup_last_seq_for_date returns "last_seq" not "lastSeq" | Docstring at seq_helper.py:169 documents the deviation; Phase-61 caller must use result["last_seq"] | Yes -- docstring present, AST-level annotation confirmed |
| CR-02: sum_usage returns None when all usages null | sum_usage() body has `any_data = False` flag; returns `total if any_data else None` | Yes -- test_sum_usage_all_null_returns_none passes |
| WR-01: downscale_if_needed wrapped in try/except | multimodal.py lines 54-72 wraps entire body in try/except Exception | Yes -- confirmed in source |
| WR-02: observer fires in finally block | extractor.py lines 239-255 -- resp=None, exc=None, try/except/finally pattern | Yes -- test_on_llm_call_observer_fires_on_error passes |
| WR-03: isinstance(corpus_context, dict) guard | extractor.py line 119 `if corpus_context is not None and isinstance(corpus_context, dict)` | Yes -- test_corpus_context_non_dict_is_excluded passes |
| WR-04: iscoroutinefunction instead of iscoroutine | extractor.py line 250 `if inspect.iscoroutinefunction(on_llm_call)` | Yes -- confirmed in source |
| IN-01: bare-list branch comment | seq_helper.py lines 128-132 comment present | Yes -- confirmed in source |
| IN-02: SUBMISSION_JSON_SCHEMA copy.deepcopy | submission.py line 68 `SUBMISSION_JSON_SCHEMA: dict = copy.deepcopy(Submission.model_json_schema())` | Yes -- confirmed in source |

---

### Anti-Patterns Found

Scanned phase-added files for debt markers and stubs.

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None found | -- | -- | -- | -- |

No `TBD`, `FIXME`, `XXX`, placeholder renders, or hardcoded-empty data flows to user-visible output were found in the phase-added files. The `extractor=None` default in `create_capture_pipeline` is an intentional additive seam documented in the SUMMARY as Phase 61 scope -- not a stub (no data flows to rendering from it; it is simply not yet invoked by the pipeline state machine).

---

### Human Verification Required

#### 1. Real-Sonnet Extraction Accuracy

**Test:** Set `ANTHROPIC_API_KEY=<key>` and `EXTRACTION_LIVE_FIRE=1`, then run:

```
cd src/farm-agent && uv run pytest -q tests/test_extraction_live_fire.py -m live_fire -v
```

**Expected:** 1 test passes with:
- Draft type: `seeding_session`
- 5 groups, 11 children total
- Exact child names: `260522_SHI_1`, `260522_SHI_2`, `260522_SHI_3`, `260522_KOY_4` .. `260522_KOY_11`
- Per-field provenance present on each group field (value, confidence, sources)
- Cache liveness: `usage["cache_creation_input_tokens"] > 0` OR `usage["cache_read_input_tokens"] > 0`

**Why human:** Requires a live `ANTHROPIC_API_KEY` and costs real API calls. Deferred by design, consistent with Phase 58 (Whisper live-fire) and Phase 59 (Haiku classifier live-fire) which follow the same operator-run pattern. The hermetic mocked-tool_use suite proves all wiring, retry logic, schema validation, seq-minting, and multimodal assembly. The live-fire proves the model actually extracts the correct structured data from the real audio transcript and paper-log photo.

---

### Gaps Summary

No gaps. All 4 hermetic must-haves are VERIFIED. The single outstanding item (real-Sonnet live-fire accuracy run) is an intentional operator-deferred test, not a code gap -- the harness exists, is double-gated, and skips cleanly in CI.

---

_Verified: 2026-06-26_
_Verifier: Claude (gsd-verifier)_
