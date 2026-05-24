---
phase: 49-real-session-eval-corpus-may-22-ship-gate-reprocess
plan: 02
subsystem: alerter/test/eval/ingestion (named-regression gate)
tags: [eval-corpus, regression-guard, named-sessions, mock-extractor, ci-gate]
requires:
  - 49-01 schema migration + sessions-loader + first named fixture
  - Phase 47 createExtractor + SeedingSession schema
  - Phase 47-05 makeMockAnthropicClient pattern (raw tool_use envelope)
  - Phase 38 Plan-09 hand labels (reused for May-12 ground-truth)
provides:
  - sessions.test.js named-regression CI gate (it.each over manifest.regression_guard:true)
  - Second named-regression fixture: 2026-05-12_inoc_santi (5 groups, 12 children, event_date 2026-04-25)
  - Per-fixture mock-extraction.json (raw Anthropic tool_use response shape)
  - EVAL_RUN_LIVE=1 branch wired (no-op in this plan; Plan 04 ship-gate scope)
affects:
  - Closes INOC-07 to two-of-three named sessions (third lands in Plan 04)
tech_stack:
  added: []
  patterns:
    - "Raw @anthropic-ai/sdk tool_use response envelope as mock-extraction.json (mirrors Phase 47-05 seeding-session-may22.test.js)"
    - "Real createExtractor + injected mock client (exercises validator + retry path; higher-fidelity than the existing eval/ingestion mock-extractor.js wrapper)"
    - "Key-fields equality projection (excludes confidence + sources arrays which drift across mock vs live runs)"
key_files:
  created:
    - src/agents/alerter/test/eval/ingestion/sessions.test.js
    - src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-05-12_inoc_santi/ground-truth.json
    - src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-05-12_inoc_santi/MANIFEST.md
    - src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-05-12_inoc_santi/audio.aac (symlink)
    - src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-05-12_inoc_santi/paper-log.jpg (symlink)
    - src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-05-12_inoc_santi/mock-extraction.json
    - src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-05-22_inoc_santi/mock-extraction.json
  modified: []
decisions:
  - "mock-extraction.json holds the RAW @anthropic-ai/sdk tool_use response (Phase 47-05 makeMockAnthropicClient shape), NOT the extractor return shape. Reason: lets the test exercise the real createExtractor() code path -- validator, retry on schema failure, packResult -- by injecting only the mock client. A bug in any of those surfaces in CI."
  - "Test does NOT use pipeline-adapter.runFixtureThroughPipeline. Reason: pipeline-adapter is wired for the per-corpus eval shape (extractor.extract({text, imageBlocks, fixtureName})) which does not match the real extractor signature (extractor.extract({captures, inFlightDraft})). Calling the real extractor directly is the higher-fidelity gate for the named-regression purpose."
  - "Equality assertion projects drafts to {type, event_date, groups[].{parent.value, species.value, qty.value, child_block_names.value}} only. Reason: confidence + sources arrays legitimately drift across mock vs live runs and different model versions; only structural fields participate in the regression bar."
  - "May-12 ground-truth uses 'NO_PARENT' sentinel (not null) for the DT and outdoor-SHI groups where audio names no parent. Reason: schemas/seeding-session.js ParentRef is z.string().min(1); null fails Provenanced validation. NO_PARENT is the documented schema sentinel."
metrics:
  duration_minutes: ~25
  completed_date: 2026-05-23
---

# Phase 49 Plan 02: Named-regression CI gate Summary

Ships the named-regression CI gate (`sessions.test.js`) that fails hard
on any regression to the May-22 or May-12 extraction shapes. Closes
INOC-07 to two-of-three named sessions; the third lands in Plan 04
along with the EVAL_RUN_LIVE=1 ship-gate runbook.

## What was built

### 1. sessions.test.js -- named-regression CI gate

`it.each(NAMED)` iterates entries from `loadSessionsCorpus()` filtered to
`manifest.regression_guard === true`. Each named session test:

1. Loads `mock-extraction.json` from the fixture dir (the raw
   `@anthropic-ai/sdk` tool_use response).
2. Builds a mock Anthropic client whose `messages.create` returns that
   response verbatim.
3. Instantiates the **real** `createExtractor({ apiKey, client })` and
   calls `extract({ captures, inFlightDraft: null })`. This runs through:
   - `buildContentBlocks` (multimodal composition)
   - `client.messages.create` (mock returns the canned tool_use envelope)
   - `findToolUseBlock` + `validateDraft(..., Submission)` (Zod schema)
   - `packResult` (single-draft back-compat surface)
4. Asserts `result.ok === true`, mock client called exactly once (no
   retry path), and the projected key-fields tuple matches the
   ground-truth projection.

Mode selection:

| Env                           | Behavior                                                                                    |
| ----------------------------- | ------------------------------------------------------------------------------------------- |
| default (no `EVAL_RUN_LIVE`)  | Mock-mode; hermetic; <1s wall time; both named fixtures pass.                               |
| `EVAL_RUN_LIVE=1` (this plan) | Logs deferral note; the it.each loop still runs in mock-mode (Plan 04 wires the live path). |
| `EVAL_RUN_LIVE=1` (Plan 04)   | Real Anthropic client + real Whisper transcription against `audioPath` + `photoPath`.       |

Named-vs-corpus split is hard: the gate filters to `regression_guard:true`
and asserts each match strictly. There is no `.skip`, no `.warn` soft
path. Any failure here ships as CI red. Future unnamed-corpus sessions
(>= 90% schema-conformance bar) are deferred to Plan 04 along with the
third named session pick.

### 2. 2026-05-12 named-regression fixture

```
src/agents/alerter/test/eval/ingestion/fixtures/sessions/
  2026-05-12_inoc_santi/
    audio.aac           -> symlink to /mnt/mossrock/shared/mushdatadump-prod/2026-05-12_inoc_santi/om01IyuHnLBohp1r_F_m.aac
    paper-log.jpg       -> symlink to /mnt/mossrock/shared/mushdatadump-prod/2026-05-12_inoc_santi/YkBwglxBTAFiQE5JbRwr.jpg
    ground-truth.json
    MANIFEST.md
    mock-extraction.json
```

Ground-truth shape (5 groups, 12 children, event_date `2026-04-25`):

| Parent           | Species | Qty | Children                          |
| ---------------- | ------- | --- | --------------------------------- |
| `260118_SHI_25`  | SHI     | 3   | `260425_SHI_1..3`                 |
| `260118_KOY_7`   | KOY     | 2   | `260425_KOY_4..5`                 |
| `260323_WIN_3`   | WIN     | 3   | `260425_WIN_6..8`                 |
| `NO_PARENT`      | DT      | 3   | `260425_DT_9..11`                 |
| `NO_PARENT`      | SHI     | 1   | `260425_SHI_12`                   |

Source: Phase 38 Plan-09 replay-output.txt (`.planning/phases/38-extraction-pipeline/`
+ `/mnt/mossrock/shared/mushdatadump-prod/2026-05-12_inoc_santi/replay-output.txt`).
The replay was per-bag (12 individual seeding drafts from the audio); the
seeding_session shape collapses bags sharing a parent + species into one
group with `qty=N` and `child_block_names.value=[<N names>]`. Translation
documented in `MANIFEST.md` "Phase 38 Plan-09 ground-truth reuse" section.

### 3. mock-extraction.json (per fixture)

Holds the raw `@anthropic-ai/sdk` tool_use response shape:

```jsonc
{
  "content": [
    {
      "type": "tool_use",
      "id": "toolu_mock_49_02_...",
      "name": "submit_extraction",
      "input": {
        "drafts": [
          {
            "draft": { /* full seeding_session per Phase 47 schema */ },
            "per_field_confidence": { "event_date": 0.99 }
          }
        ],
        "continuity": "start_new",
        "continuity_reason": "..."
      }
    }
  ],
  "usage": {
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0
  },
  "stop_reason": "tool_use"
}
```

Mirrors Phase 47-05's `makeMockAnthropicClient` shape exactly. The
embedded `draft` matches `ground-truth.json` minus the `meta` block plus
the `confidence` field on every Provenanced value (required by
schemas/provenance.js -- ground-truth.json omits it since equality
assertions key off `.value` only).

May-22 mock-extraction.json: 5 groups, 11 children, event_date `2026-05-22`.
May-12 mock-extraction.json: 5 groups, 12 children, event_date `2026-04-25`.

## Verification (from plan)

- `npx jest --config test/eval/ingestion/jest.config.js test/eval/ingestion/sessions.test.js` -- 3 passed (2 named + 1 LIVE-FIRE deferral note)
- `ls fixtures/sessions/` -- 2026-05-12_inoc_santi, 2026-05-22_inoc_santi
- `grep -c regression_guard.*true fixtures/sessions/*/MANIFEST.md` -- 1 per file (2 total)
- `jq '.content[0].input.drafts[0].draft.groups | length' .../mock-extraction.json` -- 5 (May-22), 5 (May-12)
- Full `eval-ingestion` jest project -- 48 passed, 5 skipped, 0 failed

## Phase 38 Plan-09 reuse notes (deviations + translation)

The Phase 38 hand labels were per-bag (one seeding draft per inoculated
bag) rather than session-shaped. Translation steps:

1. Group bags by `(parent_batch_name, species_code)` tuple.
2. Set `qty = count of bags in group`.
3. Sort children by SEQ within group; emit as `child_block_names.value[]`.
4. Sources `audio` + `paper_log_photo` set per the replay attribution
   (audio narration named parents for the first three groups; the DT and
   outdoor-SHI groups had no parent in the audio, so `parent.value =
   'NO_PARENT'`, `parent.sources = ['audio']`).
5. WIN coding restored from the Plan-09 species-vocab fix (the original
   audio-replay coded WIN as CAS; Plan 09 Task 4 added winecap->WIN to
   the species-vocab dict). Ground-truth uses the corrected coding.

## mock-extraction.json contract documentation

For Plan 04 + future named-regression fixture authors:

1. Create the fixture dir under `fixtures/sessions/<YYYY-MM-DD>_<context>/`.
2. Symlink the source audio + paper-log photo from the prod corpus (do
   not copy raw bytes; see Plan 01 SUMMARY for the rationale).
3. Author `ground-truth.json` as a literal seeding_session draft per the
   Phase 47 SeedingSession schema MINUS the `confidence` field on
   Provenanced values (the equality projector strips them anyway). Add
   `meta.regression_guard: true` + `meta.notes` for paper-trail.
4. Author `MANIFEST.md` with a fenced ```json``` block carrying
   `{regression_guard, capture_date, event_date, source_path, notes}`.
5. Author `mock-extraction.json` as the raw `@anthropic-ai/sdk` tool_use
   envelope. Each Provenanced value MUST include `confidence` (the real
   schema validator will reject without it). Easiest path: start from a
   sibling fixture's mock-extraction.json and edit the `input.drafts[0].draft`
   shape; the wrapper envelope stays identical.

## EVAL_RUN_LIVE=1 path -- deferred to Plan 04

The live-fire branch is intentionally not exercised in this plan. The
test file documents the invocation contract via the
`'LIVE-FIRE: documents the EVAL_RUN_LIVE=1 invocation path'` test which
logs the deferral note and returns. Plan 04 will:

1. Replace the no-op early-return with real Whisper transcription against
   `session.audioPath`.
2. Build real image blocks via `pipeline.loadImageBlocks([session.photoPath])`.
3. Instantiate `createExtractor({ apiKey: process.env.ANTHROPIC_API_KEY })`
   (no injected client).
4. Call `extract({ captures: [{captureId, text, transcript, images}] })`
   and assert equality on the same key-fields projection.

Cost estimate per live-fire pass (per Phase 47-05 calibration): ~$0.10
per fixture x 2 fixtures = ~$0.20 per ship-gate run, runnable on
operator command.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] mock-extraction.json drafts needed `confidence` on every Provenanced field**
- **Found during:** Task 2 first jest run (RED -> validator returned schema_invalid).
- **Issue:** Initial mock-extraction.json mirrored ground-truth.json (omitted `confidence`). The ground-truth is hand-labeled and never schema-validated; the mock response IS schema-validated by `validateDraft(toolUse.input, Submission)` inside the real extractor. `schemas/provenance.js` Provenanced(...) declares `confidence: z.number().min(0).max(1)` as required.
- **Fix:** Added `confidence` (0.85 .. 0.95 spread) to every parent / species / qty / child_block_names entry in both mock-extraction.json files via a jq one-liner.
- **Commit:** `288bd8d`

**2. [Rule 1 - Bug] May-12 ground-truth + mock used `parent.value: null` for groups with no audio-named parent**
- **Found during:** Task 1 ground-truth authoring + Task 2 schema validation.
- **Issue:** Initial ground-truth/mock-extraction had `parent.value = null` for the DT and outdoor-SHI groups (where the audio names no parent). `schemas/seeding-session.js` declares ParentRef as `z.string().min(1)` with `NO_PARENT` as the documented "extractor cannot infer" sentinel.
- **Fix:** Replaced both null values with `'NO_PARENT'` in May-12 ground-truth.json + mock-extraction.json + updated MANIFEST.md prose to reference the sentinel + schema constraint.
- **Files modified:** ground-truth.json (Task 1 + Task 2), MANIFEST.md (Task 1 + Task 2), mock-extraction.json (Task 2).
- **Commit:** `288bd8d` (the May-12 mock-extraction.json + the NO_PARENT touch-up landed together with the test wire-up; the originally-Task-1-only files needed the same fix to flow through Task 2's gate).

**3. [Rule 3 - Blocking decision] Test wires the real extractor with a mock Anthropic client instead of using `pipeline-adapter.runFixtureThroughPipeline` + `createMockExtractor`**
- **Found during:** Task 2 read_first step.
- **Issue:** The plan must_haves say "runs pipeline-adapter.run() against its audio+photo using the mock-extractor by default", but pipeline-adapter is wired for the per-corpus eval shape (`extractor.extract({text, imageBlocks, fixtureName})`) which does NOT match the real extractor signature (`extractor.extract({captures, inFlightDraft})`). Using pipeline-adapter would require either rewriting the real extractor signature (out of scope, breaks Phase 47-05 + Phase 38 callers) or wrapping the real extractor in a translation layer (adds an unmocked seam).
- **Fix:** Took the higher-fidelity path: mock-extraction.json holds the RAW tool_use response (Phase 47-05 `makeMockAnthropicClient` shape), and the test injects a mock client into the real `createExtractor`. This exercises the actual extractor.extract() code path (validator, retry, packResult). The EVAL_RUN_LIVE=1 Plan-04 path will be the symmetric "real client, no mock" inversion -- same code path, different client.
- **Trade-off:** Diverges from the plan's literal `pipeline-adapter.run()` wording, but matches the stronger plan intent ("Plan 04 ship-gate is the proof") and mirrors the canonical Phase 47-05 hermetic pattern.

### Authentication Gates

None.

### Threat Flags

None new beyond the plan's T-49-02-01 (mock drift vs live extractor):
the mock-extraction.json IS the operator-curated golden response;
operator-curated drift surfaces in Plan 04's live-fire run by definition.

## Known Stubs

None. Both named-regression fixtures fully wired; the LIVE-FIRE
early-return is intentional Plan-04 scope, not a stub.

## Self-Check: PASSED

Files verified to exist:
- FOUND: src/agents/alerter/test/eval/ingestion/sessions.test.js
- FOUND: src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-05-12_inoc_santi/ground-truth.json
- FOUND: src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-05-12_inoc_santi/MANIFEST.md
- FOUND: src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-05-12_inoc_santi/audio.aac (symlink)
- FOUND: src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-05-12_inoc_santi/paper-log.jpg (symlink)
- FOUND: src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-05-12_inoc_santi/mock-extraction.json
- FOUND: src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-05-22_inoc_santi/mock-extraction.json

Commits verified:
- FOUND: ea199b2 (Task 1: 2026-05-12 named-regression fixture)
- FOUND: 288bd8d (Task 2: sessions.test.js + mock-extraction.json + NO_PARENT fix)
