---
phase: 38-extraction-pipeline
plan: "03"
subsystem: alerter/extraction
tags: [anthropic-tool-use, multimodal-fusion, prompt-caching, zod-retry, jimp]
requires:
  - extraction-schemas-zod
  - draft-json-schema-anthropic
provides:
  - extractor-entry-point
  - submission-wrapper-schema
  - multimodal-content-block-builder
  - image-downscale-jimp
  - tool-use-schema-retry-envelope
affects: [src/agents/alerter]
tech_stack_added: [jimp]
patterns_added: [forced-tool-use-with-zod-retry, cacheable-system-and-few-shot, image-downscale-1_15mp-cap]
key_files_created:
  - src/agents/alerter/src/extraction/multimodal.js
  - src/agents/alerter/src/extraction/validator.js
  - src/agents/alerter/src/extraction/prompts/system.js
  - src/agents/alerter/src/extraction/extractor.js
  - src/agents/alerter/test/extraction/multimodal.test.js
  - src/agents/alerter/test/extraction/validator.test.js
  - src/agents/alerter/test/extraction/extractor.test.js
  - src/agents/alerter/test/extraction/helpers/fake-anthropic-server.js
key_files_modified:
  - src/agents/alerter/package.json
  - src/agents/alerter/src/extraction/schemas/index.js
decisions:
  - "Validator re-applies observation state-or-notes refine inline (Plan 01 deviation): when discriminator is 'observation', validateDraft checks hasStateOrNotes after safeParse"
  - "SUBMISSION wrapper schema lives alongside Draft in schemas/index.js (not in a separate file); zodToJsonSchema with 'Submission' name passed to tools[0].input_schema"
  - "Tool name = submit_extraction; tool_choice = {type:'tool', name:'submit_extraction'} forces the model to call it (no free-form text)"
  - "Both system prompt and final few-shot user-block carry cache_control:{type:'ephemeral'} so the system+few-shot prefix is prompt-cached across calls"
  - "Image downscale uses jimp@0.22 (pure JS) at 1.15MP / 5MB ceilings; no native bindings install risk on elder-plops"
  - "One-shot Zod retry uses threaded multi-turn (assistant tool_use -> user tool_result is_error=true -> model retries). Cross-turn ask-back state machine (Plan 04/05) is stateless re-extract and built separately."
metrics:
  duration: "~22min"
  completed: "2026-05-12"
  tasks_complete: 2
  files_touched: 10
  tests_added: 27
---

# Phase 38 Plan 03: Extractor + Multimodal + Validator Summary

## One-liner

Anthropic forced-tool-use extractor with multimodal fusion (text+transcript+image in ONE call), Zod safeParse against a SUBMISSION wrapper, one-shot tool_result is_error=true retry, jimp-backed 1.15MP/5MB image downscale, and cache_control:ephemeral on system+few-shot prefix.

## What shipped

- **`src/extraction/multimodal.js`** -- `buildContentBlocks`, `readImageToBase64`, `downscaleIfNeeded`. Pure-JS jimp at 1.15MP / 5MB ceilings (RESEARCH Pitfall 3). Never throws on file IO.
- **`src/extraction/validator.js`** -- `validateDraft(input, schema)` runs Zod safeParse and re-applies the observation state-or-notes refine when the discriminator is `observation` (Plan 01 deviation). `buildToolResultRetry(toolUseId, errors)` emits the Anthropic `tool_result` block with `is_error:true` for the retry turn.
- **`src/extraction/prompts/system.js`** -- locked `SYSTEM_PROMPT` + 3 few-shot pairs (seeding text-only, observation multimodal, seeding-replace-on-correction). Final few-shot user-block carries `cache_control:{type:'ephemeral'}`; system text block also marked ephemeral. Examples grounded in mushdatadump species codes (SHI, LIM, KOY).
- **`src/extraction/extractor.js`** -- `createExtractor({apiKey, logger, model, maxTokens, client})` factory; `extract({captures, inFlightDraft})` returns `{ok, draft, continuity_decision, continuity_reason, per_field_confidence}` on success or `{ok:false, reason}` on failure. Builds one Anthropic call with cached system+few-shot prefix, forced tool_use, then Zod-parses the `submit_extraction` input. One retry max via tool_result is_error=true. ANTHROPIC_API_KEY never crosses into logger.
- **`src/extraction/schemas/index.js`** -- extended with `Submission` wrapper (`{draft, continuity enum, continuity_reason, per_field_confidence}`) + `SUBMISSION_JSON_SCHEMA`. Plan 01's `Draft` stays pure.
- **`test/extraction/helpers/fake-anthropic-server.js`** -- HTTP fake of `POST /v1/messages` mirroring `fake-whisper-server.js`. Exposes mutable `responseQueue[]` + `buildToolUseResponse()` helper. (Helper authored for future integration tests; current unit tests use the `jest.mock('@anthropic-ai/sdk')` pattern.)
- **27 new tests** added across multimodal (9), validator (6), and extractor (10) covering: content-block ordering, multimodal fusion (one call carries all modalities), schema retry-success, schema retry-twice-fail, SDK throws-never-throws, API-key-never-leaks, tool_choice forcing, input_schema wiring, cache_control:ephemeral, in-flight-draft rendering.

## Commits

| Hash    | Type | Message                                                                    |
| ------- | ---- | -------------------------------------------------------------------------- |
| d699bf9 | test | add failing tests for multimodal + validator (RED) + jimp@0.22 dep         |
| 2079bf2 | feat | multimodal + prompts + validator scaffolding (GREEN)                       |
| 09804aa | test | add SubmissionSchema barrel + failing extractor tests (RED)                |
| 3a805af | feat | extractor with multimodal fusion + tool-use retry (GREEN)                  |

## Tasks executed

| # | Name                                                          | Status   | Commits          |
|---|---------------------------------------------------------------|----------|------------------|
| 1 | multimodal.js + prompts/system.js + validator.js (RED->GREEN) | complete | d699bf9, 2079bf2 |
| 2 | fake-anthropic-server + extractor.js (RED->GREEN)             | complete | 09804aa, 3a805af |

## Deviations from Plan

None. The plan's hint about "validator MAY need to re-apply observation refine" played out exactly: `validateDraft` checks `draft.type === 'observation'` and re-runs `hasStateOrNotes` after `safeParse`. Test `validator.test.js` "observation with neither state nor notes is rejected via re-applied refine" gates this.

## Deferred Issues

**Pre-existing failure unrelated to Plan 38-03:** `test/config.test.js` Test A still fails locally because the dev shell exports `DASHBOARD_URL=http://100.96.10.66:8080/`. Same failure called out in Plan 01 + Plan 02 summaries. Full alerter suite: 337/338 with that single pre-existing failure.

**fake-anthropic-server.js not yet exercised:** Authored per plan spec as a future seam for integration-style tests (e.g. Plan 06 end-to-end). Current Plan 03 tests use `jest.mock('@anthropic-ai/sdk')` per the alerter house pattern from `llm-client.test.js`. No regression risk; helper file is dead-code only until a future plan calls `start()` on it.

## Verification

- `cd src/agents/alerter && npx jest test/extraction/` -> **69/69 pass** (28 schemas + 9 multimodal + 6 validator + 10 extractor + 16 extraction-db from Plan 02).
- `cd src/agents/alerter && npx jest` -> **337/338 pass** (1 pre-existing config.test.js failure documented above; no regressions).
- `grep -c "tool_choice" src/extraction/extractor.js` -> 2.
- `grep -c "submit_extraction" src/extraction/extractor.js` -> 2.
- `grep -nE "—" src/extraction/{extractor,multimodal,validator,prompts/system}.js` -> no matches (no em-dashes).
- `node -e "console.log(require('./src/extraction/prompts/system').FEW_SHOT.length >= 3)"` -> `true` (3 few-shot pairs, one is multimodal).
- API-key-leak test passes: extractor.test.js (R6) asserts `sk-` never appears in any logger call (warn/info/error) even on SDK error path.

## Threat Mitigations Applied

| Threat ID  | Mitigation in code |
|------------|--------------------|
| T-38-03-01 | `new Anthropic({ apiKey })` is the only place apiKey crosses; logger receives only `e.message`. R6 test spies on warn/info/error and asserts no `sk-` substring. |
| T-38-03-02 | `Submission` schema with `.strict()` + Zod safeParse on tool_use input. One tool_result is_error=true retry; second failure returns `{ok:false, reason:'schema_invalid', errors}` for caller to surface as needs_review (Plan 04 wiring). |
| T-38-03-03 | `downscaleIfNeeded` enforces 5MB / 1.15MP cap via jimp before base64; test "large image (>1.15MP) is downscaled" verifies the resized buffer falls under the pixel cap. |
| T-38-03-04 | `readImageToBase64` accepts only the path passed in by the caller (Plan 05 will pass `signal_capture.attachment_paths[]` -- server-controlled). No `..` resolution; `fs.readFile` returns ENOENT -> `{ok:false, reason}`. |
| T-38-03-05 | (accept) `continuity_reason` returned from extract; Plan 04 will persist it on `signal_draft`. Full request/response not logged here. |

## Downstream Seams

- **Plan 04 (state machine):** calls `extractor.extract({captures, inFlightDraft})` and routes by result. On `ok:false, reason:'schema_invalid'`, sets draft status to `needs_review`. Reads `continuity_decision` + `continuity_reason` for the state transitions in CONTEXT D-01.
- **Plan 05 (capture.js hook):** populates `images` from `signal_capture.attachment_paths[]` by calling `readImageToBase64` per path, then passes the resulting `{data, media_type}` array as `captures[i].images`.
- **Plan 06 (eval harness):** `fake-anthropic-server.js` is the live HTTP fake to assert wire-shape; real Anthropic calls run via `EXTRACTION_FIXTURE_DIR` against mushdatadump.

## Self-Check: PASSED

- `src/agents/alerter/src/extraction/multimodal.js` -> FOUND
- `src/agents/alerter/src/extraction/validator.js` -> FOUND
- `src/agents/alerter/src/extraction/prompts/system.js` -> FOUND
- `src/agents/alerter/src/extraction/extractor.js` -> FOUND
- `src/agents/alerter/src/extraction/schemas/index.js` -> FOUND (modified, Submission added)
- `src/agents/alerter/test/extraction/multimodal.test.js` -> FOUND
- `src/agents/alerter/test/extraction/validator.test.js` -> FOUND
- `src/agents/alerter/test/extraction/extractor.test.js` -> FOUND
- `src/agents/alerter/test/extraction/helpers/fake-anthropic-server.js` -> FOUND
- Commit d699bf9 -> FOUND
- Commit 2079bf2 -> FOUND
- Commit 09804aa -> FOUND
- Commit 3a805af -> FOUND
