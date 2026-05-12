# Requirements: v1.7 Multimodal Signal → FarmOS Events

**Milestone goal:** Ship the multimodal extraction pipeline (photo + voice + text → LLM → farmOS event writes) that exercises and validates the 2026-05-11 schema lock, ending with one SHI-on-sawdust block driven end-to-end through farmOS by Signal alone.

**Schema source-of-truth** (locked 2026-05-11, farmos repo `d4e5a30`):
- `/mnt/slime-kingdom/shared/farmos/.planning/notes/2026-05-09-fungi-schema-strawman.md`
- `/mnt/slime-kingdom/shared/farmos/.planning/notes/2026-05-11-session-chat.md`

**Hard rule (NORTH-STAR + SEED-002):** every farmOS write goes through farmer YES/NO/EDIT confirm. No auto-commit path in v1.7.

---

## Active Requirements

### PRE — Signal pre-gate (hard prereq for everything downstream)

- [ ] **PRE-01**: signal-cli is re-registered as primary (deviceId=1) on the bot account, unblocking the receive 400 limitation that's been blocking Signal-driven UAT since Phase 25. Recipe in memory `project_signal_cli_primary_reregister_path`; spike PASS recorded 2026-04-27 (`project_phase25_pregate_spike_state`).
- [ ] **PRE-02**: alerter + bridge identity-trust survives the re-registration (verified via test message round-trip from at least two farmers).

### ROUTE — Multi-farmer routing (load-bearing, was 999.20)

- [x] **ROUTE-01
**: Bot replies to `envelope.source` (the message sender), not a fixed recipient — DM-to-DM is correct for every farmer.
- [x] **ROUTE-02
**: Bot participates in the "Mushroom Farm" group thread — distinguishes DM context from group context; in groups, only responds to explicit commands and @mentions (default: no spam).
- [x] **ROUTE-03
**: Per-farmer identity binding — incoming messages are tagged with the farmer's farmOS person record (resolved through Signal phone number → farmOS people directory lookup). Unknown numbers tagged `(unassigned)` per B6 sentinel pattern; never silently dropped.

### EXT — Schema-aware LLM extraction

- [x] **EXT-01**: Extraction returns JSON-mode output constrained to the locked schema (`fungi` assets: sterilization batch / block / harvest batch / bag; logs: seeding / activity / input / observation / harvest per B7). No off-schema fields.
- [x] **EXT-02**: Block-naming extraction emits `{YYMMDD}_{SPECIES3}_{SEQ}` per B5 when the farmer's paper-log convention applies (e.g. "260511_SHI_4"). When the convention is ambiguous, the bot asks for the SEQ rather than guessing.
- [x] **EXT-03**: Multimodal fusion — when a message bundles text + audio + photo, the bot combines all three signals into one draft event (not three separate ones). Audio transcripts (Whisper, Phase 25 pipeline) feed extraction alongside text; photos contribute QR scans + optional vision-derived context (e.g. visible block tags).
- [x] **EXT-04**: Confidence-aware behavior — when extraction confidence below threshold OR required field unresolved, bot ASKS the farmer (Signal reply with a targeted question) instead of guessing. Conversation state survives across multiple farmer turns until draft is complete.
- [x] **EXT-05**: Lineage extraction — multi-parent log refs per C4 (e.g. harvest batch from N source blocks) are extracted from natural-language lineage cues ("from blocks 3, 4, and 5").

### CONF — Farmer-in-the-loop confirmation

- [ ] **CONF-01**: After every successful extraction, bot replies with a structured draft summary (asset creates + log creates, human-readable) and "Reply YES to commit, NO to discard, EDIT <text> to amend".
- [ ] **CONF-02**: Commit happens only on YES; the write is idempotent (a duplicate YES does not double-write).
- [ ] **CONF-03**: NO discards the draft cleanly; transcript and original message remain in the Signal capture store (Phase 25 path) for audit. Bot acknowledges discard.
- [ ] **CONF-04**: EDIT routes the farmer's correction back through the LLM as additional context on the same conversation, producing a revised draft. Loop allowed N≥3 times before the bot escalates to "I can't get this right — try splitting the message."
- [ ] **CONF-05**: Pending drafts have a timeout (e.g. 30 min) after which the bot pings once, then auto-discards with a "draft expired" note. Stale drafts never auto-commit.

### FOS — FarmOS write path

- [ ] **FOS-01**: farmOS API client with auth (token-based; mushy holds its own `farmos_agent` creds), retries (idempotent on transient failures), and idempotency keys (per-draft UUID prevents duplicate writes on network flap).
- [ ] **FOS-02**: Asset creation for the four `fungi` types per B1–B4 — sterilization batch (anonymous, `BATCH-` prefix, no QR), block (parent = batch, species set, `farm_id_tag` QR-bound at inoc), harvest batch (multi-parent = source blocks, single-strain), bag (parent = harvest batch, QR-bound at bagging).
- [ ] **FOS-03**: Log creation per B7 mapping — `seeding` (inoc), `activity name=sterilize|sterilize_failed|water|relocate|cold_shock|archive_spent|contam`, `input` (recipe lots), `observation` (state checks, pin emergence, photos), `harvest` (picks and bagging). Native types only per C5.
- [ ] **FOS-04**: QR `farm_id_tag` binding writes through `farmos_asset_link` resolution (scan → asset). Bot handles both "QR not yet bound" (new asset → create + bind) and "QR already bound" (read existing asset → append log).
- [ ] **FOS-05**: Photos attached to the originating Signal message are uploaded as file entities on the corresponding `observation` or `harvest` log (per the Phase 22 contract — bridge already serves frames).
- [ ] **FOS-06**: Write path is observable — every committed write emits a structured log entry (Mission Control telemetry topic or bridge log) including draft UUID, farmer, asset/log IDs, and farmOS response. Operator can audit "what did the bot write today" from one query.

### INGEST — Multi-source ingestion (P3 validation)

- [ ] **INGEST-01**: Synthetic ingest harness — a fixture corpus of crafted Signal-message inputs (text/audio/image), each with expected extracted output. Drives unit + integration tests; runs in CI.
- [ ] **INGEST-02**: Historical paper-log replay — at least one batch of existing paper inoc logs (photographed) flows through the same pipeline. Expected outputs hand-labeled by the operator/farmer. Comparison report: extracted vs labeled, per-field error rate.
- [ ] **INGEST-03**: Audio recording replay — existing field recordings (operator/farmer narrating inoc sessions, observations) flow through Whisper + extraction. Same expected-vs-actual report.
- [ ] **INGEST-04**: Across all three streams, the pipeline produces the **same** schema writes for the same underlying event (e.g. a paper-log photo of inoc session N and the audio recording of the same session both yield identical `seeding` log content).

### PILOT — SHI-on-sawdust end-to-end (P4/P5 validation)

- [ ] **PILOT-01**: Sterilization batch created via Signal (anonymous count, `BATCH-` prefix, no QR). Verifies B1 + extraction + confirm + write.
- [ ] **PILOT-02**: Inoculation — sterilization batch → 1 block at inoc. New `fungi` asset created, species=SHI, substrate=sawdust on field, `farm_id_tag` QR-bound. `seeding` log writes lineage (block parent = batch). Verifies B2 + C3 + C4.
- [ ] **PILOT-03**: Colonizing → cold_shock → fruiting transitions captured via `observation` and `activity` logs from natural Signal messages over the lifecycle. Current-stage derivation (C1) returns the right stage at every checkpoint.
- [ ] **PILOT-04**: Bagging — harvest batch created from the block (`harvest` log multi-parent ref) + N bag assets created with QR bind at bagging. Verifies B3 + B4 + QR-bind-via-natural-message.
- [ ] **PILOT-05**: Archive_spent — block archived via `activity name=archive_spent`. Lineage walk (bag → harvest batch → block → sterilization batch) returns clean per C4.
- [ ] **PILOT-06**: End-to-end pilot run completed on the dev stack (`:18080`) per P2, with all writes visible in farmOS, all transitions queryable, and the operator able to reconstruct the lifecycle entirely from farmOS logs without referring back to Signal.

---

## Future Requirements (deferred, possibly v1.8+)

- Vision-based extraction (contamination spots, pin emergence, growth stage) — blocked on 999.26 camera coverage.
- High-confidence auto-commit (no farmer confirm) for narrow patterns — earned after v1.7 produces ≥4 weeks of clean confirm data.
- Multi-chamber rollout (FC-2/FC-3) — depends on 999.6.
- Farmer-app "Captured events" review surface (SEED-003 composable) — slot if cheap, otherwise v1.8.
- farmOS admin actions (Phase 19) — still Zoy/farm-team gated.
- Group-thread richer behavior (proactive nudges, multi-farmer collaboration on the same draft) — minimum-viable group support only in v1.7.

## Out of Scope (explicit exclusions)

- **ML vision pipelines.** v1.7 uses LLM only; vision is text-extraction-via-OCR-when-needed, not image classifiers.
- **farmOS UI work.** All farmOS schema-side UI (admin actions, custom views, mobile workflows) is Zoy's domain.
- **Schema changes.** v1.7 ships against the locked schema. Any schema drift goes through Zoy first.
- **Non-mushroom domains.** Animal / tomato / forestry assets are out — the schema is farm-wide but v1.7 only exercises the mushroom slice (B1–B7).
- **Backfilling historical farmOS data.** Pipeline writes new events going forward; no retroactive bulk-import of pre-v1.7 paper logs into farmOS (the historical-log INGEST stream is for *validation*, not data migration).

---

## Traceability

| REQ-ID | Phase | Status |
|---|---|---|
| PRE-01 | Phase 36 | Pending |
| PRE-02 | Phase 36 | Pending |
| ROUTE-01 | Phase 37 | Pending |
| ROUTE-02 | Phase 37 | Pending |
| ROUTE-03 | Phase 37 | Pending |
| EXT-01 | Phase 38 | Complete |
| EXT-02 | Phase 38 | Complete |
| EXT-03 | Phase 38 | Complete |
| EXT-04 | Phase 38 | Complete |
| EXT-05 | Phase 38 | Complete |
| CONF-01 | Phase 39 | Pending |
| CONF-02 | Phase 39 | Pending |
| CONF-03 | Phase 39 | Pending |
| CONF-04 | Phase 39 | Pending |
| CONF-05 | Phase 39 | Pending |
| FOS-01 | Phase 40 | Pending |
| FOS-02 | Phase 40 | Pending |
| FOS-03 | Phase 40 | Pending |
| FOS-04 | Phase 40 | Pending |
| FOS-05 | Phase 40 | Pending |
| FOS-06 | Phase 40 | Pending |
| INGEST-01 | Phase 41 | Pending |
| INGEST-02 | Phase 41 | Pending |
| INGEST-03 | Phase 41 | Pending |
| INGEST-04 | Phase 41 | Pending |
| PILOT-01 | Phase 42 | Pending |
| PILOT-02 | Phase 42 | Pending |
| PILOT-03 | Phase 42 | Pending |
| PILOT-04 | Phase 42 | Pending |
| PILOT-05 | Phase 42 | Pending |
| PILOT-06 | Phase 42 | Pending |
