# Phase 60: Extraction Pipeline - Context

**Gathered:** 2026-06-26
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous) — 3 areas; all recommended except Area 2 (Pillow+downscale chosen) and Area 3 (reproduce Node 2-call retry chosen)

<domain>
## Phase Boundary

Port the Node multimodal extraction pipeline to Python: fuse text + audio transcript + image
into a schema-valid draft via Claude (Anthropic) tool-use, reproducing all Node extraction
behaviors — SeedingSession multi-parent shape, per-field provenance, retry logic, and B5
block-name minting. Faithful port; the Node source under `src/agents/alerter/src/extraction/`
is the source of truth.

**Crucial pre-existing asset:** the pydantic schemas are ALREADY ported (Phase 56 FND-04) and
the parity test passes — `Submission`, the `Draft` union, `SeedingSession`, `Provenanced[T]`,
and `BLOCK_NAME_RE = r"^[0-9]{6}_[A-Z]{2,4}_[0-9]+$"` all live under
`src/farm-agent/farm_agent/extraction/schemas/` with `extras='forbid'`. Phase 60 does NOT
re-port the schema; it wires the extractor CALL + multimodal + retry + seq-minting on top of
it, using the Phase-59 gate classifier as the blueprint.

Success criteria (ROADMAP v1.12 Phase 60):
1. Replaying the 2026-05-22 audio+photo inoc session produces one `seeding_session` draft with
   5 groups, 11 children, correct `260522_SHI_1..3` / `260522_KOY_4..11` block names, and
   per-field provenance metadata.
2. A schema-invalid LLM response triggers the retry path (tool_result `is_error: true` +
   correct `tool_use_id`) and resolves on the retry; the terminal failure produces a
   `needs_review` draft, not an exception. **(Retry count: see Area 3 — reproduce Node's 2
   total LLM calls; ROADMAP wording corrected accordingly.)**
3. `BLOCK_NAME_RE` uses `re.fullmatch()`; `260522_SHI_1_EXTRA` is rejected, `260522_SHI_1` passes.
4. Structural diff of the Python `model_json_schema()` vs the Node `SUBMISSION_JSON_SCHEMA` is
   clean (FND-04 gate re-verified against the real extractor call).

</domain>

<decisions>
## Implementation Decisions

### Area 1: Extractor structure, model & LLM reuse
- **Module:** new `farm_agent/extraction/extractor.py` with a factory
  `create_extractor(client, model="claude-sonnet-4-6", max_tokens=16384, on_llm_call=None)
  -> {"extract": async_fn}`, mirroring the Phase-59 gate's `create_haiku_classifier` shape
  (never-throws, returns a discriminated `{ok, ...}` result). Reuse the shared
  `anthropic.AsyncAnthropic` singleton injected at boot.py.
- **LLM plumbing:** keep gate and extractor as SEPARATE factories for now (different model,
  timeout, system prompt). Do NOT unify a generic llm_client helper yet — revisit in a later
  phase if the pattern repeats a third time.
- **Model ID:** `claude-sonnet-4-6` verbatim (Node's extractor model; NOT the gate's haiku).
- **max_tokens:** 16384 (Node's Plan-09 bump for multi-event pages; do not regress to 2048).
- **Tool:** forced `submit_extraction` (tool_choice={type:'tool', name:'submit_extraction'}),
  validated via pydantic `Submission.model_validate(tool_use.input)`.

### Area 2: Multimodal image handling
- **Input:** new `farm_agent/extraction/multimodal.py` accepts image FILE PATHS (from the
  capture pipeline) and reads + base64-encodes them inline as
  `{type:'image', source:{type:'base64', media_type, data}}` blocks (mirror Node multimodal.js).
- **Downscaling:** ADD **Pillow** as a runtime dependency and port Node's downscale (when an
  image exceeds ~5MB or ~1.15MP). NOTE: Pillow is a net-new runtime dep — gets the
  package-legitimacy checkpoint at execute time (like anthropic / python-ulid). It is a
  ubiquitous, well-maintained library; flag-and-approve.
- **Missing/unreadable image:** FAIL-OPEN — skip that image block, log a WARNING, continue the
  extraction with the remaining text + transcript (+ other images). Never abort (D-03/D-04).
- **media_type:** detect image/jpeg vs image/png from content/extension; default jpeg.

### Area 3: Retry, provenance, SEQ & testing
- **Retry attempts (CONFLICT RESOLVED — reproduce Node):** Node does a MAX of 2 LLM calls:
  initial `messages.create`, validate tool-use via pydantic; on validation failure send a
  follow-up turn with a `tool_result` block (`is_error: true` + the matching `tool_use_id` +
  the error list) and retry ONCE; on the second failure return
  `{ok: False, reason: "schema_invalid", errors, raw_first, raw_retry}` — never throws — and
  the pipeline produces a `needs_review` draft (not an exception). The Python port reproduces
  this 2-call behavior exactly (parity-gate safe). The ROADMAP SC wording ("the third failure")
  is corrected to match Node's 2-call shape — this is NOT an intentional delta; it's a wording fix.
- **Provenance:** the system prompt enumerates the source taxonomy
  (audio / paper_log_photo / bag_label_photo / text / model_inference) and instructs the LLM to
  set each field's `sources[]` from the modalities the value came from — verbatim from Node.
  Provenance is inline per value `{value, confidence:[0,1], sources:[...]}` (Phase-47 Gray Area 2),
  already enforced by the existing `Provenanced[T]` pydantic generic.
- **SEQ:** new `farm_agent/extraction/seq_helper.py` ports Node's PURE helpers —
  `mint_child_block_names({event_date_yymmdd, species_code, start_seq, qty})` (yields qty
  consecutive names, each validated against `BLOCK_NAME_RE` via `re.fullmatch`) and
  `lookup_last_seq_for_date(pool, event_date)` (MAX SEQ across drafts on that date, per-session
  scope, walking both legacy `seeding.block_name` and `seeding_session.groups[].child_block_names`).
  The extractor only EMITS the `needs_input='starting_seq'` sentinel when SEQ is ambiguous; the
  interactive farmer ask-back (`handle_starting_seq_reply`) is DEFERRED to Phase 61 (Confirm Loop).
- **Prompts:** commit the Node system prompt + few-shot examples verbatim inline in
  `farm_agent/extraction/prompts.py` with `cache_control: {type: "ephemeral"}` on the system
  blocks (mirror gate/prompts.py).
- **Testing:** copy the 2026-05-22 fixture (transcript.txt + paper-log.jpg + text-followup.txt +
  expected-draft.json) to `tests/fixtures/extraction/seeding-session-may22/`. Hermetic unit test
  wraps the expected output in a MOCKED tool_use envelope (FakeAnthropicClient extended for the
  Messages API) and asserts: 1 seeding_session, 5 groups, 11 children, the exact block names,
  per-field provenance present, and the retry path (is_error tool_result → resolves; terminal →
  needs_review). Re-run the FND-04 parity test against the real extractor's Submission schema.
  The real-Sonnet accuracy run on the live fixture is marker/env-gated and DEFERRED (operator-run),
  like the Phase 58/59 live-fires.

### Claude's Discretion
- Internal helper names, file splits within `extraction/`, exact downscale thresholds within
  Node's documented bounds, and test parametrization — provided the locked behavior + schema +
  module boundaries above hold.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `farm_agent/gate/classifier.py` (Phase 59) — the never-throws `create_x(client) -> {"fn": async}`
  factory + forced tool-use + `with_options(timeout=...)` + pydantic `model_validate` + fail-open
  blueprint to mirror for the extractor.
- `farm_agent/extraction/schemas/` (Phase 56 FND-04) — Submission / Draft union / SeedingSession /
  Provenanced[T] / `BLOCK_NAME_RE` already ported; `test_schema_parity.py` passes. DO NOT re-port.
- `farm_agent/boot.py` — shared `AsyncAnthropic(max_retries=2)` singleton to inject into the extractor factory.
- `tests/conftest.py` — `FakeAnthropicClient` (extend for the Messages API tool_use envelope + retry).

### Established Patterns
- Never-throws discriminated `{ok, reason}` results; fail-open + WARNING on LLM error; PII masking on logs.
- `cache_control: ephemeral` on a large verbatim system-prompt block (gate/prompts.py precedent).
- Marker/env-gated deferral of the real-model accuracy run (Phase 58/59 live-fire precedent).

### Integration Points
- Consumes the capture envelope (text + transcript + attachment image paths) from Phase 58.
- Produces a `Submission`/`seeding_session` draft persisted to `signal_draft`; the
  `extraction_gate=allow_extract` decision from Phase 59 gates whether extraction runs.
- The needs_input='starting_seq' sentinel is consumed by Phase 61's confirm loop.
- Node reference: `src/agents/alerter/src/extraction/{pipeline,extractor,multimodal}.js`,
  `prompts/system.js`, `schemas/{index,provenance,seeding-session,seeding}.js`, `seq-helper.js`.

</code_context>

<specifics>
## Specific Ideas

- 2026-05-22 fixture (Phase 47 INOC-01): 5 groups, 11 children — SHI x1+1+1 (260522_SHI_1..3) +
  KOY x4+4 (260522_KOY_4..11); SEQ is per-session running counter spanning all groups, NOT per-strain.
- The fixture's `child_block_names` list is the locked regression guard (KOY parent decoding is
  intentionally ambiguous; assert the child names, not the parent attribution).
- Carry the Node trap: timeout in request-options (`client.with_options(timeout=...)`), NOT a
  messages.create body kwarg.
- Idle-gap continuity (hard 30-min start_new) and append/replace/start_new continuity logic exist
  in Node pipeline.js — port the extractor's emission of the continuity decision; the pipeline
  persistence/state-machine integration should match Node but the interactive parts (ask-back,
  confirm prompt) are Phase 61.

</specifics>

<deferred>
## Deferred Ideas

- Real-Sonnet accuracy run on the live 2026-05-22 fixture (marker/env-gated) — operator-run, like 58/59.
- The interactive `handle_starting_seq_reply` farmer ask-back + confirm-prompt wiring — Phase 61 (Confirm Loop).
- Unifying gate + extractor LLM plumbing into a shared helper — revisit later if the pattern repeats.
- Any extraction-behavior changes beyond reproducing Node — out of scope.

</deferred>
