---
phase: 38-extraction-pipeline
extracted: 2026-05-13
status: shipped (closed 2026-05-12 evening; v1.7 milestone)
---

# Phase 38 Learnings -- Extraction Pipeline

## Decisions made

- **D-01 / D-01a:** LLM judges continuity (append / replace / start-new); hard 30min idle-gap cap forces start-new regardless. Prevents a hung session silently swallowing the next event.
- **D-02 / D-02a:** Reuse Phase 25 capture-db; new `signal_draft` table; deterministic id = sha256(sorted source capture ids). Replay-safe by construction.
- **D-02b:** Status enum split across phases (Phase 38 owns pending/awaiting_farmer/needs_review/expired; Phase 39 owns confirmed/discarded; Phase 40 owns committed). Clean ownership boundary.
- **D-02c:** Partial unique index `WHERE status IN ('pending','awaiting_farmer')` -- at-most-one-in-flight per sender at the DB layer, not the app layer.
- **D-03 / D-05:** Ask-back triggers on either unresolved required field OR per-field confidence < 0.7; hard cap = 3 turns -> `needs_review`.
- **D-06 / D-07:** Ship-gate is the offline eval harness against mushdatadump v1.6. Pass bar: >=90% schema-valid AND >=75% required-field-exact-match OR appropriate-ask-back.
- **D-08 (Plan 08 delta):** B5 regex relaxed to `[A-Z]{2,4}` after live data showed 2-letter species codes (DT) in production. The strawman "{SPECIES3}" was wrong.
- **D-09 (Plan 08 delta):** Corpus context is operator-supplied, not page-inferred. Notebook pages have no year written; extractor hallucinated 2002/2026 at ~0.6 conf. `corpusContext.default_year` plumbed into system prompt.
- **D-10 (Plan 08 delta):** Extractor returns `drafts[]`, not `draft`. Paper-log scans contain N events per page (IMG_3800 had 21).
- **D-12 (Plan 08 delta):** `drafts.length > 1` enters batch mode -- forces start_new, `maxAskbackTurns=0`, single operator-DM summary instead of N farmer pings. Avoids violating NORTH-STAR with 21 ask-back pings from one photo.

## Lessons learned

- **Plan 03 shipped two API-shape bugs that 125/125 mocked unit tests missed.** (1) `zod-to-json-schema` named-output is `{$ref, definitions}` but Anthropic requires top-level `type=object`. (2) Few-shot `tool_use` blocks need matching `tool_result` blocks in the next user turn or HTTP 400. Both were invisible until Plan 07 hit the live API. **Action filed:** live-API smoke in CI/pre-deploy as v1.8 candidate.
- **First Plan 09 run FAILED at 36.5% schema conformance** despite Plan 07 "PASS". Five real bugs surfaced in the cycle: whisper GPU drift, fake-green `/health` deep-probe, image-wire bug (a04a6bc), maxTokens 2048 -> 16384, species-vocab gap (winecap -> WIN), harness-pipeline parity (`loadImageBlocks` un-exported), whisper hallucination tail (VAD filter missing). Plan 09 run 2 hit 95.8% after fixes.
- **Plan 07 PASS was content-vacuous on B5 precision** (D-13): scorer reported `precision = 0/N` with no ground truth supplied; absence of evidence read as failure. Scorer now reports `regexValidRate` alongside precision so a missing-GT case is legible.
- **The "real-data ship-gate" rule was forged here.** Phase 38 was closed twice: first on curated-only PASS, retracted same hour when real inoc session went 0/4 through the live alerter (whisper 500 + schema_invalid). Lesson pinned to memory as `feedback_real_data_before_ship_gate_pass.md`.
- **Whisper "OK" healthcheck was lying.** Process up, GPU memory lost, transcription returning 500s. Shallow healthcheck masked a real outage. Fixed with deep probe.
- **Paid-API result-overwrite cost a 24-draft extraction twice in one session.** Fixed-output paths on paid scripts are a banned anti-pattern; lesson pinned to memory as `feedback_persist_paid_results_default.md`.

## Patterns worth reusing

- **Plan-Plus-Smoke before paid batch.** Plan 09 sequence: $0.51 smoke (10 fixtures) -> green -> $4.75 full batch. Failure mode caught early instead of $10+ wasted on the full corpus. Memory: `feedback_smoke_before_expensive_batch.md`.
- **Per-call unique JSONL output paths + append-only.** Two paid extraction overwrites in one session burned 24 drafts. Standard now: `results/<run-id>.jsonl`, never `results.jsonl`.
- **Named sibling files for the paper trail.** Plan 09 left four EVAL-REPORT files: smoke / run1-FAIL / run2-PASS / partial. A future reader can `ls` and see the lineage. Memory: `feedback_keep_paper_trail_of_intermediates.md`.
- **Discriminated-result return shape `{ok, ...} | {ok:false, reason}`** for outbound IO with never-throw envelope. Used in `llm-client`, `extractor`, `validator`, all DB writes. Logger tag `[component] degraded: ...` on failures.
- **Idempotent migration at module init:** `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS` + `ADD COLUMN IF NOT EXISTS`. Wrapped in best-effort try/catch at boot; alerter starts even if migration fails.
- **Factory + `_internal` test seam:** every module exports its public factory plus `_internal: { ... }` for direct unit tests of helpers.
- **Cost-tracking telemetry in eval scoring:** Plan 09 results.jsonl now records `input_tokens / output_tokens / cache_read / cache_write / estimated_spend_usd` per call. Makes the "is this passing or just expensive?" question answerable.

## Surprises

- **Prompt caching cut spend ~5x.** Plan 09 run 1 (no cache): $5.65 / 36.5% PASS. Plan 09 run 2 (cache hits 533k tokens read): $4.75 / 95.8% PASS at *lower cost*. Surprising that the cache-write penalty (138k tokens) is dwarfed by repeated cache reads on the same 73-fixture corpus.
- **B5 regex was wrong in the spec for ~1 year and nobody noticed** until production data was scanned. The strawman `{SPECIES3}` came from a hypothetical 3-letter naming convention; actual practice uses 2-4 letters. Don Santiago corrected it on first paper-log scan.
- **The notebook has no year written on pages.** Operator confirmed `mushdatadump = 2025 notebook`. The model dutifully hallucinated 2002 or 2026 at ~0.6 conf. Corpus context is operator-asserted, not page-inferred.
- **One paper-log page = 21 events** broke the original "one capture = one draft" assumption (D-02). Forced the D-10 / D-12 batch-mode redesign mid-phase.
- **Whisper "fake-green" healthcheck.** Process-level health is not service-level health. GPU memory had drifted; transcription returned 500 while `/health` returned 200.

## Open threads

- Live-API smoke in CI / pre-deploy ($1-3/run, catches Plan 03-shape bugs early). Filed as v1.8 backlog candidate.
- Plan 38-08 (production-log advisory smoke) intentionally superseded by Plan 09; ROADMAP still shows `[ ]`. Mark as superseded.
- Plan 09 ran exactly one real prod session (`2026-05-12_inoc_santi`). The denominator for "real-prod fixtures" is still 1; future phases should grow this corpus.
- Confidence-threshold calibration sweep (D-06 punted to eval-time) was never run; 0.7 is the empirical default carried forward.

## Commits referenced

- `a04a6bc` -- image-wire bug fix mid-Plan-09 cycle
- `b238222` -- Plan 03 API-shape fixes (inlineTopLevelRef + few-shot tool_result blocks)
- `0c54662` / `829e411` -- Plan 07 scaffolding + eval driver

Plan 09 paid spend: $10.91 total ($5.65 FAIL run 1 + $0.51 smoke + $4.75 PASS run 2).
