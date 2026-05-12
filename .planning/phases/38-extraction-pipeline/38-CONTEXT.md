# Phase 38: Extraction Pipeline - Context

**Gathered:** 2026-05-11
**Status:** Ready for planning

<domain>
## Phase Boundary

A multimodal Signal message (text, audio, photo, or any combination) from a known farmer (Phase 37 routing identifies sender) produces a structured JSON **draft** of farmOS assets and logs conforming to the locked B7 schema, or triggers a targeted ask-back when confidence is too low.

**In scope:**
- Multimodal fusion of text + audio (Whisper transcript via existing Phase 25 pipeline) + photo
- Schema-aware LLM extraction (Claude Sonnet 4.6 via existing `llm-client.js`)
- JSON-mode output constrained to B1–B7 native log types — no off-schema fields
- Per-field confidence + targeted ask-back loop (≤3 turns)
- Draft persistence in Timescale (extends Phase 25 `signal_capture` schema)
- Offline eval harness against mushdatadump v1.6 — Phase 38 ship-gated on pass bar
- Block-naming extraction per B5: `{YYMMDD}_{SPECIES3}_{SEQ}`
- Lineage extraction per C4: multi-parent harvest refs from natural-language cues

**Out of scope (other phases):**
- Farmer YES/NO/EDIT confirmation loop → Phase 39 (CONF-01..05)
- farmOS API writes (asset/log creates, QR binding, photo upload) → Phase 40 (WRITE-01..05)
- Cross-stream consistency tests / replay harness → Phase 41 (HARN-01..05)
- Full SHI-on-sawdust lifecycle E2E → Phase 42 (PILOT-01..05)

</domain>

<decisions>
## Implementation Decisions

### Multimodal Fusion Rule
- **D-01:** **LLM judges continuity.** On each new inbound message from a known sender with an in-flight draft, the LLM is shown (a) the current draft and (b) the new content, and decides one of: `append` / `replace` / `start-new`. The decision and rationale are logged to the draft audit trail.
- **D-01a (planner guard):** Hard idle-gap cap of **30min** — any new message after 30min of silence forces `start-new` regardless of LLM judgment, so a hung session can't silently swallow the next event. Explicit confirm/discard from Phase 39 also forces `start-new` for the subsequent message.

### Draft Storage + State Model
- **D-02:** **Reuse Phase 25 `capture-db.js` (Timescale).** Add a new `signal_draft` table in the same DB. One draft can span multiple captures — link via FK array `source_capture_ids text[]` referencing `signal_capture.id`. Idempotent migration using the `CREATE TABLE IF NOT EXISTS` + `ADD COLUMN IF NOT EXISTS` pattern Phase 37 established.
- **D-02a:** Draft `id` is deterministic from the originating capture set (e.g. sha256 of sorted capture ids) — the LLM-continuity append decision must be replay-safe.
- **D-02b:** Status enum: `pending` → `awaiting_farmer` → (`confirmed` | `discarded` | `needs_review` | `expired`). Phase 38 owns `pending` / `awaiting_farmer` / `needs_review` / `expired`; Phase 39 transitions to `confirmed` / `discarded`; Phase 40 transitions confirmed → `committed`.
- **D-02c:** Concurrent drafts per farmer: **at most one in-flight draft per sender E.164**. New message after start-new closes the previous one as `expired`.

### Confidence + Ask-Back UX
- **D-03:** **Ask-back trigger = per-field required-set check AND LLM self-rated per-field confidence.** Each B7 log type has a required-fields list (e.g. seeding requires `species`, `block_name`, `qty`, `event_timestamp`). LLM emits per-field `confidence` in the JSON. Ask is triggered when any required field is unresolved OR any field's confidence `< 0.7` (env-configurable as `EXTRACTION_CONFIDENCE_THRESHOLD`).
- **D-04:** **Ask-back shape = full draft preview with `[?]` markers + one-line top question.** Bot's Signal reply renders the asset creates + log creates in human-readable form, with `[?]` inline on unresolved/low-confidence fields, AND a one-line top question targeting the most-blocking ambiguity. Farmer can answer either the top Q in plain text OR scan and answer multiple `[?]` fields in any order; the LLM merges on next turn.
- **D-05:** **Hard cap = 3 ask-back turns.** On cap, bot replies *"I can't lock this one — marked for manual review"* and sets draft status to `needs_review`. Round numbers in farmer-facing text (per memory `feedback_round_farmer_numbers.md`); no em-dashes in farmer-facing artifacts (per `feedback_no_em_dashes_in_artifacts.md`).

### Eval Harness Scope
- **D-06:** **Phase 38 ships an offline eval harness** at `tests/eval/extraction/` that runs the pipeline over `/mnt/mossrock/shared/mushdatadump/` (73 JPEGs + CSV ground truth). Harness scores: (1) schema-conformance (deterministic JSON-schema validator), (2) required-field exact-match against CSV, (3) ask-back appropriateness (a case where the bot asked-back on a genuinely-ambiguous field counts as PASS, not as a failure to extract).
- **D-07:** **Pass bar (Phase 38 ship-gate):** **≥90% schema-valid** AND **≥75% required-field exact-match OR appropriate ask-back**. Phase 38 doesn't ship until this bar is met against mushdatadump v1.6.

### Claude's Discretion
- Prompt structure, few-shot examples, JSON schema-validator library choice, exact wording of ask-back templates (subject to memory constraints on style — no em-dashes, rounded numbers).
- Whether to call the LLM once with all modalities in a single prompt, or to do a two-pass extract→refine — planner/researcher decide based on eval scores.
- Internal queue/worker shape — whether extraction runs inline in the alerter receive-loop or as a separate worker process.
- Exact env-var names and defaults for thresholds (`EXTRACTION_CONFIDENCE_THRESHOLD`, `DRAFT_IDLE_GAP_MIN`, `MAX_ASKBACK_TURNS`).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### FarmOS schema (LOCKED 2026-05-11 — write target)
- `/mnt/slime-kingdom/shared/farmos/.planning/notes/2026-05-11-session-chat.md` — Full lock conversation; commit `d4e5a30`. Locks C1–C5 (farm-wide conventions), B1–B7 (mushroom-specifics), P1–P5 (SHI pilot scope). Multimodal extraction pipeline is the named v1.6 validation driver (P3).
- `/mnt/slime-kingdom/shared/farmos/.planning/notes/` (strawman + adjacent docs in the farmos repo) — Authoritative for any schema field semantics.

### Phase requirements
- `.planning/REQUIREMENTS.md` §EXT — EXT-01..05 (schema-aware extraction, B5 block-naming, multimodal fusion, confidence-aware ask-back, lineage extraction)
- `.planning/REQUIREMENTS.md` §CONF — CONF-01..05 (downstream — Phase 39 reads our drafts)

### Reference dataset (eval ground truth)
- `/mnt/mossrock/shared/mushdatadump/` (NFS) — 73 JPEGs + CSV ground truth. Phase 38 ship-gate eval dataset. Also serves Phase 41 (replay harness) and Phase 42 (pilot).

### Upstream phase artifacts (reusable code + routing)
- `src/agents/alerter/src/llm-client.js` — Phase 25 Anthropic client (model=`claude-sonnet-4-6`); extend for JSON-mode extraction.
- `src/agents/alerter/src/transcribe-client.js` — Phase 25 Whisper client (`WHISPER_URL` env, elder-plops GPU, ~3GB VRAM reserved).
- `src/agents/alerter/src/capture-db.js` — Phase 25/37 capture table; extend with `signal_draft` table.
- `src/agents/alerter/src/capture.js` — Phase 25 capture write path; extraction worker subscribes here.
- `src/agents/alerter/src/receive-loop.js` — Phase 37 multi-farmer routing; sender identity already resolved before extraction.
- `.planning/phases/37-multi-farmer-routing/37-CONTEXT.md` — Sender→farmer mapping conventions; `farmos_person` column on `signal_capture`.

### Project-level guidance
- `.planning/PROJECT.md` — Mission, NORTH-STAR (no farmer bookkeeping tax)
- `.planning/ROADMAP.md` §"Phase 38" — Goal + success criteria + dependency on Phase 37

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`llm-client.js`:** Anthropic Sonnet 4.6 wrapper already wired with `ANTHROPIC_API_KEY` env, retry/degraded path, structured logging. Extend with a new `extract()` entry point that accepts `{ text, transcripts[], image_paths[], in_flight_draft }` and returns `{ continuity_decision, draft, per_field_confidence }`.
- **`transcribe-client.js`:** Whisper HTTP client at `WHISPER_URL` (default `http://host.docker.internal:8090`); transcripts already attached to `signal_capture.transcript`.
- **`capture-db.js`:** Pool-injected module with idempotent migration pattern. Adding a `signal_draft` table follows the established shape exactly (see Phase 37 D-14/D-15 additions).
- **`capture.js` + `receive-loop.js`:** New captures are persisted with sender + farmos_person already resolved (Phase 37). Extraction worker reads new captures matched to a known farmos_person.

### Established Patterns
- **Idempotent DB migration:** `CREATE TABLE IF NOT EXISTS` + `ADD COLUMN IF NOT EXISTS` at module init (capture-db.js:5–35).
- **Env-driven thresholds:** Operational knobs live in `config.js` and `.env`, not hardcoded (see memory: `feedback_alerter_env_convention_bridge_http_url`).
- **Farmer-facing message formatting:** `message.js` uses `fmtNum()` for rounded numbers; no em-dashes anywhere a farmer reads (`feedback_no_em_dashes_in_artifacts`, `feedback_round_farmer_numbers`).
- **Pool injection:** All DB modules accept an externally-managed pool — no module-local connections.

### Integration Points
- **Inbound:** New row in `signal_capture` with `farmos_person IS NOT NULL` → enqueue extraction job.
- **Persistence:** New `signal_draft` rows + status transitions on the same Timescale pool.
- **Outbound (to Phase 39):** Draft status `awaiting_farmer` with a `farmer_facing_preview` text column is the seam Phase 39 reads.
- **Outbound (to farmOS — Phase 40):** Draft `confirmed` rows are the seam Phase 40 reads.
- **Signal reply path:** Existing `signal.js` send helpers (DM + group). Phase 37's `reply_target_kind` on `signal_capture` tells us DM-vs-group for the ask-back reply.

</code_context>

<specifics>
## Specific Ideas

- **Eval as ship-gate, not eval-as-aspiration.** Phase 38 doesn't get a SUMMARY.md until the harness reports the pass bar on mushdatadump.
- **Ask-back is success, not failure.** When the bot correctly declines to guess on an ambiguous field, that's the product working — the eval counts it as PASS. Aligns with EXT-04 + NORTH-STAR (don't tax the farmer with wrong guesses).
- **Confidence threshold (0.7) is empirically tunable**, not a load-bearing constant. The planner should expose it as a config knob from day one and the eval-planner should sweep it during calibration.
- **Block-naming is parse-friendly because the farmer's paper-log already uses `{YYMMDD}_{SPECIES3}_{SEQ}`.** No translation layer needed — extraction emits the canonical form directly. When SEQ is ambiguous, ask rather than guess (EXT-02 explicitly mandates this).
- **`/gsd-ai-integration-phase` is likely the right planner entry** rather than standard `/gsd-plan-phase` — this phase IS an AI system with eval gating + guardrails + production monitoring concerns. Worth surfacing at planning time.

</specifics>

<deferred>
## Deferred Ideas

- **Vision-derived context beyond QR scan** (e.g. visible block tags in frame, contamination color detection). Phase 38 reads photo→QR + photo→LLM-as-context; deeper CV is Phase 24/v1.8 territory.
- **Cross-stream consistency tests** (same event from text-only vs text+photo vs text+voice produces same draft) — Phase 41 (Ingestion Harness).
- **Multi-farmer event collision** (two farmers send overlapping messages about the same event) — out of scope for v1.7 single-pilot scope; revisit if pilot expands.
- **Farmer-tunable thresholds via Signal command** (e.g. `/ask_threshold 0.8`) — not for v1.7; ops-side env-tuning only.
- **Auto-merge of `needs_review` drafts during weekly farmer review session** — Phase 39+ workflow concern.
- **Lineage shorthand resolution beyond simple block-number lists** (e.g. "blocks from the batch we sterilized last Tuesday") — best-effort in v1, defer the temporal-reasoning hard cases.

</deferred>

---

<plan_08_delta>
## Plan 08 Delta -- 2026-05-12

Discoveries during Plan 08 live-API extractor work on mushdatadump (IMG_3775, IMG_3800) that amend the 2026-05-11 decisions above. These do not invalidate the original locks; they refine sections that the Plan 07 eval and the multimodal paper-log fixtures exposed.

### D-08 -- B5 block-name regex relaxed to `{YYMMDD}_{A-Z}{2,4}_{SEQ}`

The text "`{SPECIES3}`" at lines 18 and 119 was inherited from an earlier strawman. Production paper logs use 2-letter species codes (`DT` for "donkey tail" / Tremella) alongside 3- and 4-letter codes (`SHI`, `CAS`, `KING`). `BLOCK_NAME_RE` is now `/^[0-9]{6}_[A-Z]{2,4}_[0-9]+$/`. Treat lines 18 / 119 as historical; the live regex spec is the schema in `src/agents/alerter/src/extraction/schemas/seeding.js`.

### D-09 -- Corpus context: paper notebook year is operator-supplied, not page-inferred

mushdatadump pages have no year written on them (memory: `project_mushdatadump_is_2025_notebook`). The extractor was hallucinating years (2002, 2026) at ~0.6 confidence. Extractor now accepts `corpusContext.default_year` injected at call time; system prompt plumbed through to bind extracted MMDD shorthand to the operator-asserted year. mushdatadump is configured `default_year: 2025`.

### D-10 -- Multi-event per page: extractor returns `drafts[]`, not `draft`

Original D-02 assumed one draft per capture: appropriate for conversational "I just inoculated 12 jars" messages. Paper-log scans contradict this: IMG_3800 is 21 individuation events on one page across DT / CAS / SHI columns. Tool schema is now `Submission = { drafts: [{draft, per_field_confidence}, ...], continuity, continuity_reason }`. The `draft` / `per_field_confidence` legacy fields are still exposed on `extractResult` (as `drafts[0]`) for back-compat during the multi-week migration.

### D-11 -- Paper-log lineage: parent-batch shorthand decoded via corpus context

Farmer-written column shorthand `0627-2` (DT column, page year=2025) decodes to canonical parent block `250627_DT_2`. Seeding schema now carries optional `parent_batch_name` matching the same B5 regex. Decode rule: when a parent ref omits species or year, the extractor uses the column header (species) + corpus default_year (year) + the page-local SEQ to construct the canonical name. Confidence on the constructed parent_batch_name is the LLM's call.

### D-12 -- Pipeline batch mode forks on `drafts.length`

`drafts.length === 1` keeps the conversational ask-back path (D-01..D-05 unchanged). `drafts.length > 1` enters batch mode (paper-log scan):

- Forces `continuity = start_new`; expires any prior in-flight draft for the sender.
- Persists N rows keyed by `(source_capture_ids, index)` via `computeDraftId(captureIds, draftIndex)`. Index 0 = legacy hash, so single-draft hashes are byte-identical.
- Runs state-machine with `maxAskbackTurns = 0`. Clean drafts still hit AWAITING_FARMER + handoff_to_phase_39. Dirty drafts skip ask-back entirely and land in NEEDS_REVIEW with `needs_review_reason = 'batch_mode_low_conf'`.
- Emits **one** `send_batch_review_summary` side effect for the whole page -- Signal DM to Don Santiago summarising N drafts (M clean, K needs review) with truncated id list. **No farmer messages in batch mode.** Rationale: 21 ask-back pings from one photo would violate NORTH-STAR (`feedback_no_farmer_bookkeeping_tax`).

D-04 (ask-back shape) and D-05 (3-turn cap) still apply to the conversational path. Batch-mode review-summary text follows D-05's style rules (round numbers, no em-dashes, address Don Santiago by name).

### D-13 -- Eval scorer audit needed before Plan 07 retroactive credit

Plan 07's "PASS" verdict on the eval-harness scaffolding was structurally honest but content-vacuous: B5 0% precision was a scorer bug (no GT supplied -> `precision = 0/N` regardless of extraction quality), not an extractor bug. Scorer now reports `regexValidRate` alongside precision/recall so a regex-vs-GT mismatch is legible. The pass-bar reading in D-07 still stands but the harness now reports usage tokens + cost per run (38-EVAL-REPORT-results.jsonl) so a "pass" actually corresponds to known-quality output, not absence of evidence.

</plan_08_delta>

*Phase: 38-extraction-pipeline*
*Context gathered: 2026-05-11*
*Plan 08 delta appended: 2026-05-12*
