# Phase 59: Event Gate - Context

**Gathered:** 2026-06-24
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous) — all three areas accepted as recommended

<domain>
## Phase Boundary

Port the Node "event gate" to Python: a rule prefilter plus a Haiku LLM classifier that
decides which inbound Signal captures enter the extraction pipeline, reproducing the Node
gate's accept/reject behavior with **fail-open** semantics. The gate sits between Phase 58's
capture pipeline and the (Phase 60) extraction pipeline. It does NOT itself extract — it only
decides `allow_extract` / `allow_convo`.

This is a **faithful port**: the gate's behavior is fixed by the Node source under
`src/agents/alerter/src/event-gate/` and is reproduced exactly. The decisions captured here
are about Python structuring, not about changing gate behavior.

Success criteria (ROADMAP v1.12 Phase 59):
1. Replaying the 100-capture hand-classified prod corpus (Phase 44 Plan-01 fixture) through
   the Python gate yields **zero chit-chat reaching extraction** (0% false-positive on labeled negatives).
2. Event recall on the same smoke is **>=95%** (no real farm events gate-rejected).
3. A Haiku timeout/API error **fails open** (message proceeds to extraction), not closed; a WARNING is logged.

</domain>

<decisions>
## Implementation Decisions

### Area 1: Module structure & LLM client
- **Module layout:** New `farm_agent/gate/` leaf package mirroring the Node `event-gate/` directory:
  `event_gate.py` (facade `create_event_gate`), `rules.py` (rulePositive/ruleNegative),
  `classifier.py` (Haiku classifier factory), `prompts.py` (system prompt + taxonomy). Honors
  the FND-05 Foray seam; importable from the capture/extraction pipeline as a leaf unit.
- **Anthropic client lifetime:** One shared `anthropic.AsyncAnthropic` created once at boot
  (mirroring the `httpx.AsyncClient` wiring in boot.py) and injected into the gate/classifier
  factory closure. Not per-instance.
- **How to call Claude:** Add the **official `anthropic>=0.45` SDK** as a runtime dependency
  (faithful to the Node `@anthropic-ai/sdk ^0.91.1`; handles forced tool-use parsing and the
  request-options AbortSignal/timeout subtlety the Node code hit live 2026-05-23).
  NOTE: net-new runtime dependency — gets the package-legitimacy gate treatment at plan/execute
  time (the official first-party Anthropic SDK; low risk but call it out).
- **Factory return shape:** Dict `{"classify": async_fn}` mirroring `transcribe_client`
  (never-throws, returns a discriminated `{ok, ...}` result).

### Area 2: Behavioral fidelity (port-locked)
- **Model ID:** `claude-haiku-4-5-20251001` verbatim (parity; not a floating alias).
- **System prompt (~20KB / ~4.1K tokens):** committed verbatim inline as a Python string module
  (`prompts.py`) for immutability and deterministic prompt-cache (>=4096-token threshold);
  `cache_control: {type: "ephemeral"}` on the system block, as Node does.
- **Decision flow + confidence floor:** reproduce exactly —
  `rulePositive(envCtx)` → `ruleNegative(envCtx, lastBotOutbound, nowMs)` → `await haikuClassifier.classify`;
  classifier `!ok` (timeout/error) → `forced` (allow_extract=true) fail-open;
  `is_event || confidence < 0.7` → event (allow_extract=true); else → chitchat (allow_extract=false).
  Output gate enum: `skipped_rule_neg | fast_event | haiku_event | haiku_chitchat | forced`.
  The 0.7 floor is hard-coded per the D-02 spec.
- **Rule prefilter (verbatim from Node rules.js):**
  - rulePositive: any attachment (`attachmentCount>0`, kind=image_or_audio); body >200 chars (long_text);
    strain regex `\b[A-Z]{2,4}\b` (strain_code); block-name regex `\b\d{6}_[A-Z]{2,4}_\d+\b` (block_name).
  - ruleNegative: `lastBotOutbound.intent === 'attestation_kickoff'` AND within 30 min AND body <40 chars AND
    ack-pattern `^(ok|yes|got it|thanks|gracias|si|sí|👍)$` (case-insensitive full-body) → short_ack_within_30m.
- **Classifier call config:** forced tool `classify_capture` with schema
  `{is_event: bool, kind: enum(event|soft_observation|phantom_ack|greeting|ux_meta), confidence: number}`;
  max_tokens=100; timeout=2000ms (passed in request-options, NOT body); maxRetries=2.
  User message = compact JSON `{text, transcript, attachmentCount}` — never concatenated into the system prompt
  (threat T-44-04-01). API key env-only via existing `TenantConfig.anthropic_api_key`, never logged.
- **Config surface:** behavioral constants (timeout 2000ms, max_tokens 100, floor 0.7, model ID) live inline
  as module constants matching Node; reuse the existing `anthropic_api_key`. No new TenantConfig fields.

### Area 3: Validation & test strategy
- **Fixture:** copy `.planning/phases/44-event-gate-.../44-hand-classified-100.jsonl` into
  `tests/fixtures/gate/` so the Python suite is self-contained.
- **Unit tests:** deterministic — exercise the rule prefilter directly, and the classifier with a
  **mocked** Anthropic client (assert the user-message/tool-use shape, the tool-use parse, and every
  fail-open path: timeout, no_tool_use, schema_invalid). Run on the 90-row non-holdout subset.
- **Holdout (W10 = 7 soft-obs + 3 ux_meta):** withheld from the unit/few-shot subset; the full 100
  (incl. holdout) is reserved for the real-Haiku validation run.
- **Real-Haiku accuracy run:** the ROADMAP parity criteria (0% false-positive on labeled negatives,
  >=95% event recall) are enforced as tests on the deterministic subset; the **real-Haiku** 100-corpus
  accuracy run is a **marker/env-gated** validation (analogous to the Phase 58 live-fire — needs a live
  ANTHROPIC_API_KEY, costs API calls), NOT part of default CI. Deferred to operator validation.

### Claude's Discretion
- Exact internal helper names, file splits within `gate/`, and test parametrization, provided the
  locked behavior and the module/test boundaries above are honored.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `farm_agent/capture/transcribe_client.py` — the closure-factory `{ "fn": async }` never-throws pattern to mirror for the classifier.
- `farm_agent/capture/pipeline.py` — D-03/D-04/D-05 fail-open precedent (never raise, log WARNING, degrade).
- `farm_agent/tenancy/tenant.py:229` — `anthropic_api_key` already a config field (env-only, never logged).
- `farm_agent/boot.py:59-87` — FND-02 config load + `httpx.AsyncClient` injection wiring to mirror for the shared `AsyncAnthropic`.
- `tests/conftest.py` — existing fake-client / fixture patterns from Phase 58.

### Established Patterns
- Never-throws discriminated `{ok, reason}` results; PII masking (`mask_number`) on any sender-referencing log.
- DB-dependent / external tests skip-marked (the gate's real-Haiku run follows the same skip-gating).

### Integration Points
- Consumes the Phase 58 capture envelope/context (text, transcript, attachmentCount, lastBotOutbound).
- Produces the gate decision consumed by the Phase 60 extraction pipeline (`allow_extract`).
- Node reference: `src/agents/alerter/src/event-gate/{index,rules,haiku-classifier,prompts}.js`.

</code_context>

<specifics>
## Specific Ideas

- Port is byte-faithful to the Node gate; the Node `event-gate/` files are the source of truth for
  prompt text, taxonomy (D-20), 15 worked examples, rule regexes, thresholds, and the decision order.
- Carry forward the Node fix: the timeout AbortSignal goes in the SDK request-options arg, not the body
  (Node hit `400 invalid_request_error "signal: Extra inputs"` otherwise).
- Phase 44 holdout row IDs are enumerated in the Node `prompts.js` (HOLDOUT_ROW_IDS) — reuse that list.

</specifics>

<deferred>
## Deferred Ideas

- Real-Haiku full-corpus accuracy validation run (marker/env-gated) — operator-run, like the Phase 58 live-fire.
- Any gate-behavior changes (taxonomy tweaks, new rules) — out of scope; this phase only reproduces Node.

</deferred>
