# Phase 44: Event-gate + Durable `signal_outbound` (tenant-aware) - Context

**Gathered:** 2026-05-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Stop burning paid Sonnet on chit-chat and stop the alerter from being amnesiac about its own outbound messages. Two bundled deliverables under OSS-Foray Option α (first tenant-aware milestone):

1. **Hybrid event-gate** at `src/agents/alerter/src/capture.js:147` — rule fast-paths (POSITIVE: image/audio/strain-code/block-name/long-text; NEGATIVE: short ack within 30m of `attestation_kickoff`) + **Haiku 4.5 pre-classifier** on the gray zone. Gates BOTH the extractor (`capture.js:147`) and the conversational compose (`capture.js:168`). Convo-silence behavior is config-knobbed; default = silent.
2. **Durable `signal_outbound` table** with `tenant_id text NOT NULL` indexed from day one. Every one of the 14 `signalClient.send` call sites (per `2026-05-17-signal-outbound-schema-audit.md` §2) writes one row via a wrapped client — single persistence hook in `signal.js`. Phase 37's `fmtHistory` reads `signal_outbound` and surfaces `lastBotOutbound` to the LLM prompt, closing finding 1b proper (and superseding the v1.7.x `llm_reply` band-aid from the amnesia note).
3. **Tenant config tree begins:** `tenants/mossrock/` holds (a) `SIGNAL_FARMER_MAP`, (b) strain vocab (14 active codes), (c) secrets (`ANTHROPIC_API_KEY` + Signal sender/recipient/group), (d) farmOS endpoint (`FARMOS_URL/USERNAME/PASSWORD/INTEGRATION`).

**Out of scope** (per Foray decision + this discussion):
- ALTERing existing tables (`signal_capture`, `signal_draft`, `signal_draft_event`) for tenant_id — deferred to v2.0 carve-out (clean `SELECT WHERE tenant_id != 'mossrock'` + backfill from sender→tenant mapping).
- Phase 45 NORTH-STAR ack-on-commit_failed + replay — kept separate; ships after Phase 44 so Phase 45 can consume the live `signal_outbound` table.
- Multi-bag harvest model, structured `recipe_lot`, seeding lineage bridge — all v1.7-era Phase 43 deferrals; unchanged.
- Universal outbound-context capture beyond the 14 enumerated sites — if a new send site is added later that bypasses the wrapper, that's a CI gate concern (lint/grep), not a Phase 44 deliverable.

</domain>

<decisions>
## Implementation Decisions

### Q1 — Gate model: HYBRID (rules + Haiku 4.5) from day one

- **D-01:** Ship the full hybrid stack in Phase 44, not the conservative "rules-only first, audit a week" sequencing from the 2026-05-17 note §10.
  - **Rationale (operator override of the note's recommendation):** the operator chose to commit to Haiku surface from day one rather than pay a follow-up phase to add it later. Trades short-term scope for not deferring the gray-zone gap.
  - **Implication:** Plan-04 (Haiku classifier) is in-scope for Phase 44, not conditional on a one-week audit.
- **D-02:** Gate decision flow (after `capture.js:147`):
  1. Rule fast-path POSITIVE (image/audio/strain-code regex `/\b[A-Z]{2,4}\b/` / block-name regex `/\b\d{6}_[A-Z]{2,4}_\d+\b/` / text length > 200) → `fast_event`, enqueue both extractor + convo.
  2. Rule fast-path NEGATIVE (`lastBotOutbound.intent === 'attestation_kickoff'` within 30m AND reply text < 40 chars AND matches `/^(ok|yes|got it|thanks|gracias|si|sí|👍)$/i`) → `skipped_rule_neg`, skip extractor; convo-gate per D-05.
  3. Otherwise (gray zone) → single Haiku 4.5 tool call `classify_capture {is_event, kind, confidence}`. If `is_event === true` OR `confidence < 0.7` → `haiku_event`, enqueue. Else → `haiku_chitchat`, skip extractor.
- **D-03:** **Bias toward extraction on any failure.** Haiku error/timeout/quota → fall through to Sonnet (treat as `forced`). Missed events are NORTH-STAR violations; over-extraction is recoverable. Per `[[feedback_no_silent_failure_after_farmer_confirm]]` posture.
- **D-04:** Audit column `signal_capture.extraction_gate VARCHAR(32)` with enum `{skipped_rule_neg, fast_event, haiku_event, haiku_chitchat, forced}`. Per `[[feedback_keep_paper_trail_of_intermediates]]`. ALTER TABLE ADD COLUMN IF NOT EXISTS, populated at `capture.js:147` before the dispatch.

### Q2 — Convo gating: BOTH paths, behavior config-knobbed (default = silent)

- **D-05:** Gate decision applies to BOTH `capture.js:147` (extractor) AND `capture.js:168` (convo compose) — i.e. when gate says not_event, the conversational reply is ALSO suppressed.
  - **Rationale (operator):** "build flexibly, focus on cheap, err on silent" + `[[feedback_no_farmer_bookkeeping_tax]]` + `[[feedback_no_silent_failure_after_farmer_confirm]]` explicitly carves a NORTH-STAR floor (post-YES is sacred — but gate fires BEFORE any confirm flow, on cold inbound only, so this is not a NORTH-STAR collision).
- **D-06:** Convo-silence behavior is config-knobbed via `EVENT_GATE_CONVO_MODE` env with three values:
  - `silent` (**default**) — gate decision shared with convo path; chit-chat → bot stays silent. Cheapest, matches operator preference.
  - `negative_only` — only the NEGATIVE rule fast-path silences convo; gray-zone gray-zone keeps convo open. Use if farmer reports the bot "ignoring" them.
  - `off` — convo path runs on every whitelisted message (today's behavior). Escape hatch.
- **D-07:** When convo silences, no farmer-visible message is sent. This is NOT a `commit_failed`-class silent-failure (no farmer YES preceded it) — `[[feedback_no_silent_failure_after_farmer_confirm]]` does not apply. Confirm by re-reading that memory before planning.

### Q3 — Tenant-id retrofit: DEFER to v2.0

- **D-08:** Only `signal_outbound` (new in v1.8) gets `tenant_id text NOT NULL` + index from day one. Existing tables (`signal_capture`, `signal_draft`, `signal_draft_event`) are untouched in Phase 44.
- **D-09:** v2.0 carve-out plan stays as documented in `2026-05-17-tenant-id-retrofit-map.md` §(b): ALTER + backfill from sender→tenant mapping during extraction. Locked.

### Q4 — Phase 45 bundle: KEEP SEPARATE

- **D-10:** Phase 45 (NORTH-STAR ack + silent-failure replay) ships AFTER Phase 44. Phase 45 will consume the live `signal_outbound` table for ack persistence. Phase 44 does NOT touch state-machine terminal states or replay logistics.

### Q4 (tenants/mossrock/) — FULL MIGRATION SET

- **D-11:** `tenants/mossrock/` v1.8 contents — all four buckets locked:
  - `tenants/mossrock/config.yaml` (committed): `SIGNAL_FARMER_MAP` (phone→slug map per `[[farmer_phone_map]]`), `SIGNAL_RECIPIENT`, `SIGNAL_GROUP_ID`, `FARMOS_URL`, `FARMOS_USERNAME`, `FARMOS_INTEGRATION` flag.
  - `tenants/mossrock/strains.yaml` (committed): 14 active strain codes (`SHI SH2 KOY MAI MALI KOS DT CAS CAZ WIN ALM MOR BP LIMA` per `[[mossrock_active_strain_codes]]`). Extractor regex + prompt read from here.
  - `tenants/mossrock/secrets.env` (**gitignored**, deployed via existing secret path): `ANTHROPIC_API_KEY`, `FARMOS_PASSWORD`, `SIGNAL_SENDER`. CI injects from GitHub secrets.
  - Boot chain: `tenants/<TENANT_ID>/<key>` → env var → default. `TENANT_ID` defaults to `mossrock`. Planner: this chain MUST be the only env-read path going forward; no direct `process.env.X` reads outside `config.js`.

### Signal_outbound table shape (per audit + Foray α-lock)

- **D-12:** New table `signal_outbound` per `2026-05-17-signal-outbound-schema-audit.md` §5. Columns:
  ```sql
  CREATE TABLE IF NOT EXISTS signal_outbound (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       text NOT NULL,
    sent_at         timestamptz NOT NULL DEFAULT now(),
    recipient_e164  text NOT NULL,
    intent          text NOT NULL,        -- enum: see D-13
    body            text NOT NULL,
    attachments     jsonb,
    source_module   text NOT NULL,        -- e.g. 'capture.js', 'index.js'
    source_line     integer,              -- best-effort, may be null
    related_capture_id uuid,              -- FK to signal_capture when applicable
    related_draft_id   uuid               -- FK to signal_draft when applicable
  );
  CREATE INDEX IF NOT EXISTS idx_signal_outbound_tenant_sent ON signal_outbound(tenant_id, sent_at DESC);
  CREATE INDEX IF NOT EXISTS idx_signal_outbound_recipient_sent ON signal_outbound(recipient_e164, sent_at DESC);
  CREATE INDEX IF NOT EXISTS idx_signal_outbound_intent ON signal_outbound(intent);
  ```
  Regular Postgres table (not a hypertable) — same posture as `signal_capture` per project comment "per-farmer volume too low for hypertable."
- **D-13:** Intent enum (extensible string; not a DB-level CHECK constraint — keep agile): `convo_reply` | `attestation_kickoff` | `commit_ack` (Phase 45 will use) | `ask_back` | `experiment_ack` | `experiment_reject` | `experiment_cancel` | `experiment_complete` | `rh_alert` | `command_echo` | `confirm_prompt` | `extraction_preview`. Each of the 14 call sites maps to one intent; mapping table goes in planning RUNBOOK.
- **D-14:** **Single persistence hook.** Wrap `signalClient.send` in `src/agents/alerter/src/signal.js` so the persistence write happens ONCE, not 14 times. All 14 call sites already call through this wrapper; the hook lives inline post-send. Per audit §5 mitigation: "double bookkeeping if half the sends miss the wrapper — mitigation: single wrapper."
- **D-15:** Caller-side change: each call site passes `intent` as a second arg (or via opts object). Planner: pick the ergonomics. The 14 sites are enumerated in `2026-05-17-signal-outbound-schema-audit.md` §2.
- **D-16:** Confirm + extraction outbound modules (`confirm/outbound-confirm.js:33`, `extraction/outbound.js:55`) ALSO go through the wrapped `signalClient.send` — their per-draft event logs (`signal_draft_event`) remain for state-machine audit purposes, but `signal_outbound` is the single source of truth for "what did the bot say." No partial duplication accepted.

### Phase 37 integration (closes finding 1b proper)

- **D-17:** `fmtHistory` in `src/agents/alerter/src/llm-client.js:33-40` reads from `signal_outbound` (new) in addition to `signal_capture`, merging by timestamp. The v1.7.x band-aid (read `signal_capture.llm_reply`) is SUPERSEDED — the `llm_reply` column stays in the schema for now (audit trail) but `fmtHistory` no longer reads it; instead it reads the convo_reply rows in `signal_outbound`.
- **D-18:** `capture-history.js` adds a sibling query `selectRecentOutboundByRecipient(recipient, sinceMs)` that returns `signal_outbound` rows. `fmtHistory` merges + sorts the two streams by timestamp before formatting. Truncation: 400 char cap on outbound lines (vs current 200 inbound) — bot replies are longer.
- **D-19:** `lastBotOutbound` (the freshest `signal_outbound` row for the recipient) is exposed as a distinct field in `buildUserBlock` so the LLM prompt can reference "the last thing you said" explicitly. Used by the NEGATIVE rule fast-path (D-02 step 2) AND surfaced to Sonnet/Haiku for context.

### Ship-gate — 100-capture hand-classified smoke (Plan-01)

- **D-20:** Smoke set sourcing per `2026-05-17-prod-corpus-survey.md` §5: pull live from Timescale `signal_capture` on elder-plops (`WHERE captured_at >= '2026-05-10' LIMIT 500`), hand-stratify to 100 preserving the 2026-05-17 distribution (36 hard-event / 28 confirm / 8 phantom-ack / 8 UX-meta / 12 soft-obs / 8 greetings). Include the 3 frozen-corpus captures as seeds. Tag each row with `tenant=mossrock`.
- **D-21:** Output file: `.planning/phases/44-event-gate-durable-signal-outbound-tenant-aware/44-hand-classified-100.jsonl`. Append-only JSONL with `tenant_id, capture_id, class, expected_gate_action, notes`. Per `[[feedback_keep_paper_trail_of_intermediates]]` + `[[feedback_persist_paid_results_default]]`.
- **D-22:** Ship-gate metrics:
  - **Zero** farmer-facing preview pings on the 24 must-skip rows (8 phantom-ack + 8 greetings + 8 UX-meta).
  - **≥95%** event recall on the 48 must-extract rows (36 hard-event + 12 soft-obs).
  - The 28 confirm-verb rows must bypass the gate entirely via Phase 39 short-circuit at `receive-loop.js:220-264` — they should not even reach `capture.js:147`. Smoke also asserts this.
- **D-23:** Hand-classification is operator/Don Santiago work — cannot be automated per `[[feedback_real_data_before_ship_gate_pass]]`. Planner: include a Plan-01 task that drops the SQL pull file in the phase dir + a Plan-01 sub-task that BLOCKS on operator hand-labeling before any gate code ships.

### Claude's Discretion

- File layout under `src/agents/alerter/src/`: `event-gate/index.js` + `event-gate/rules.js` + `event-gate/haiku-classifier.js` (per audit §7 plan sketch) — or flatter if planner prefers. Convention: match existing `extraction/` and `confirm/` module layouts.
- `signal_outbound` DAO location: `src/agents/alerter/src/outbound-db.js` (parallel to `capture-db.js`, `extraction-db.js`, `confirm-db.js`).
- Boot-chain config loader: refactor `src/agents/alerter/src/config.js` to read `tenants/<id>/` files; details (YAML parser, layering library, etc.) are planner's call. Suggestion: lightweight YAML + plain `process.env` fallback; avoid adding a heavy config framework.
- Haiku timeout/retry policy: planner picks. Default suggestion: 2s timeout, no retry (fall through to Sonnet per D-03).
- `EVENT_GATE_CONVO_MODE` default location: `tenants/mossrock/config.yaml` (tenant-scoped, easy to flip per farm later). Defaults to `silent`.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 44 design notes (read FIRST)
- `.planning/notes/2026-05-17-is-this-an-event-gate.md` — finding 7 design; §3 sample distribution, §4 cost table, §5 hybrid gate sketch, §7 plan sketch.
- `.planning/notes/2026-05-17-llm-outbound-amnesia.md` — finding 1b; §2.B fmtHistory bug locus, §2.C outbound site inventory, §3 option comparison. **NOTE:** the note's recommendation (Option a*) is SUPERSEDED by Phase 44's Option (b) per D-17.
- `.planning/notes/2026-05-17-oss-foray-decision.md` — strategic Foray α-lock; tenant_id-from-day-one constraint.
- `.planning/notes/2026-05-17-signal-outbound-schema-audit.md` — §2 14-site inventory (authoritative), §5 implications, §3-4 DDL trails to mirror.
- `.planning/notes/2026-05-17-prod-corpus-survey.md` — Plan-01 smoke sourcing (live Timescale pull + stratification recipe).
- `.planning/notes/2026-05-17-tenant-id-retrofit-map.md` — §(a) NEW-IN-V1.8 contract, §(c) config-tree migration list.
- `.planning/ROADMAP.md` §"Phase 44" — GATE-01/02, OUTBOUND-01/02, TENANT-01 requirements (propose to lock during plan-phase).

### Memory references
- `[[2026-05-17-findings-discussion-decisions]]` — v1.8 bundle decision (7 + 1b(b)).
- `[[2026-05-17-oss-foray-alpha-lock]]` — Foray α posture (every PR tenant-extraction-able).
- `[[mossrock_active_strain_codes]]` — the 14 codes for `tenants/mossrock/strains.yaml`.
- `[[farmer_phone_map]]` — f1/f2/f3 → phone mapping source for SIGNAL_FARMER_MAP.
- `[[feedback_smoke_before_expensive_batch]]` — 100-capture smoke before Haiku live-fires.
- `[[feedback_real_data_before_ship_gate_pass]]` — Plan-01 fixtures from live Timescale, not curated only.
- `[[feedback_keep_paper_trail_of_intermediates]]` — `extraction_gate` audit column.
- `[[feedback_persist_paid_results_default]]` — Haiku call output persistence policy.
- `[[feedback_no_silent_failure_after_farmer_confirm]]` — confirm convo-gate does NOT silence post-YES paths.
- `[[feedback_no_farmer_bookkeeping_tax]]` — supports default-silent convo gate.

### Files this phase will modify (greppable list)
- `src/agents/alerter/src/capture.js:147` (extractor gate insertion) + `:168` (convo gate hook).
- `src/agents/alerter/src/signal.js` (wrap `send`, persistence fan-out to outbound-db).
- `src/agents/alerter/src/llm-client.js:33-40` (`fmtHistory` reads merged streams; 400-char cap on outbound).
- `src/agents/alerter/src/capture-history.js:8-13` (add `selectRecentOutboundByRecipient`).
- `src/agents/alerter/src/capture-db.js` (ALTER ADD COLUMN IF NOT EXISTS `extraction_gate VARCHAR(32)`).
- `src/agents/alerter/src/config.js` (boot chain: `tenants/<id>/` → env → default).
- 14 send-site files per audit §2 — each passes `intent` arg (or planner picks API). Sites:
  - `receive-loop.js:73, 85, 91, 102, 106, 112, 189, 211`
  - `index.js:180, 183, 185`
  - `capture.js:192`
  - `confirm/outbound-confirm.js:33`
  - `extraction/outbound.js:55`

### Files this phase will create
- `src/agents/alerter/src/event-gate/index.js` + `rules.js` + `haiku-classifier.js` (file layout planner discretion).
- `src/agents/alerter/src/outbound-db.js` (`signal_outbound` DDL + `insertOutbound` + `selectRecentByRecipient`).
- `tenants/mossrock/config.yaml`, `tenants/mossrock/strains.yaml`, `tenants/mossrock/secrets.env` (gitignored), plus `.gitignore` update.
- `tenants/example/config.yaml` (placeholders for Foray v0.1 default tenant).
- Tests:
  - `src/agents/alerter/test/event-gate/rules.test.js`
  - `src/agents/alerter/test/event-gate/haiku-classifier.test.js` (mocked Anthropic responder)
  - `src/agents/alerter/test/event-gate/integration.test.js` (full capture-pipeline-with-gate)
  - `src/agents/alerter/test/outbound-db.test.js`
  - `src/agents/alerter/test/llm-client.outbound-merge.test.js` (fmtHistory streams merge ordering)
- Smoke fixture: `.planning/phases/44-event-gate-durable-signal-outbound-tenant-aware/44-hand-classified-100.jsonl` + sourcing SQL file.

### Existing patterns to preserve
- `capture-db.js:32-34` ALTER TABLE ADD COLUMN IF NOT EXISTS pattern → use for `extraction_gate` column.
- `confirm-db.js`, `extraction-db.js` DAO module layout → mirror in `outbound-db.js`.
- `test/farmos/mock-client.js`-style mocking → mirror in event-gate Haiku mock.
- `signal.js` wrapper pattern — already centralizes the 14 sends; do not add a parallel client.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `signal.js` already wraps `signalClient.send` as the choke point for all 14 sites (per audit §5). Persistence hook lives ONCE here. No new abstraction needed.
- `capture-history.js` already does sender-scoped time-window queries; mirror its shape for the outbound-side query (D-18).
- `fmtHistory` (`llm-client.js:33-40`) already truncates per-line at 200 chars; extending to a per-stream cap (400 outbound, 200 inbound) is a one-line conditional.
- Anthropic SDK helpers from existing Phase 38 extractor mocks reuse for Haiku classifier tests.
- `capture.js:200` UPDATE pattern (write llm_reply post-send) is the template for the outbound-db insert — but lives in `signal.js` wrapper, not here.

### Established Patterns
- All schema DDL files are idempotent (`CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN IF NOT EXISTS`). `outbound-db.js` follows this.
- `config.js` is the single env-read point today; refactor preserves the single-point-of-truth posture, just adds a layered loader in front of `process.env`.
- Phase 39 confirm short-circuit at `receive-loop.js:220-264` runs BEFORE `capture.handle`, so confirm verbs never reach the gate (audit §3 + D-22 third bullet). Planner: do not add a redundant confirm-bypass inside the gate.
- `capture-db.js` includes a "per-farmer volume too low for hypertable" comment — same volume class applies to `signal_outbound`. Do NOT make it a hypertable.

### Integration Points
- `capture.js:147` is THE gate insertion point — every existing capture path runs through it (sender whitelist passes → command short-circuit pass-through → confirm short-circuit pass-through → capture pipeline → :147). The gate sits at the bottom of this funnel.
- `capture.js:168` is THE convo entry — `llmClient.compose(...)`. Convo-silence wraps this call in `if (gateDecision.allow_convo) { ... }`.
- `fmtHistory` is called inside `llmClient.compose` — the merge must happen here, not inside `capture-history.js`, so the SQL pulls stay narrow. Planner: pick the merge layer; D-18 suggests doing it in `capture-history` but planner may prefer at the llm-client layer.

</code_context>

<specifics>
## Specific Ideas

- **`lastBotOutbound` semantics.** Per D-19, this is the freshest `signal_outbound` row for the recipient — irrespective of intent. The NEGATIVE rule fast-path filters on `intent === 'attestation_kickoff'`; everything else just exposes the field.
- **Haiku model id.** Use `claude-haiku-4-5-20251001` exactly (per environment system note + `[[claude-api]]` posture). Cached system prompt for the classifier: ≥1024 tokens to enable caching (Haiku has lower threshold than Sonnet; verify before relying on it).
- **Convo-gate default = silent** maps to `EVENT_GATE_CONVO_MODE=silent` in `tenants/mossrock/config.yaml`. Operator can flip to `negative_only` or `off` without redeploy if it overshoots.
- **Plan-01 smoke must precede Plan-04 (Haiku live-fire)** per `[[feedback_smoke_before_expensive_batch]]`. Planner: order the plans so the 100-capture corpus exists before Haiku ever runs on real data.
- **Phase 45's signal_outbound row.** Phase 45 will write rows with `intent = 'commit_ack'`. Phase 44 reserves that intent string but does NOT emit it.
- **Audit-friendly:** keep `signal_capture.llm_reply` column populated (capture.js:200 UPDATE stays) even though `fmtHistory` no longer reads it. Cheap insurance; v2.0 can drop the column then.
- **Wrapper signature ergonomics.** A possible shape: `signalClient.send(recipient, body, { intent, attachments?, relatedCaptureId?, relatedDraftId? })`. Planner picks final shape; 14 sites are small enough to update in one pass.

</specifics>

<deferred>
## Deferred Ideas

- **Tenant-id retrofit on `signal_capture`/`signal_draft`/`signal_draft_event`** — v2.0 carve-out per Foray decision. Locked.
- **Phase 45 NORTH-STAR ack + replay drafts `b8a1e586` and `1fb28e70`** — ships after Phase 44 per D-10. Will write `commit_ack` rows into the new `signal_outbound` table.
- **Drop `signal_capture.llm_reply` column** — v2.0 cleanup; `fmtHistory` no longer reads it but kept for audit (per `[[feedback_keep_paper_trail_of_intermediates]]` and rollback safety).
- **CI grep-gate against raw `signalClient.send(` outside `signal.js`** — recommended in amnesia note §8 to prevent future regression. Planner: include if cheap, else file as v1.9.
- **Multi-tenant `tenants/<other-farm>/` skeleton** — wait for Foray v2.0 carve-out. v1.8 ships `tenants/mossrock/` + `tenants/example/` only.
- **WhatsApp Business API tenant** — v2.0+ open question per Foray decision §"Open questions deferred to v2.0 planning."
- **Telemetry counter on Haiku classifier hits / cost dashboard** — v1.9 candidate; Phase 44 audit column (`extraction_gate`) is sufficient instrumentation for the ship-gate.
- **Resolve `EVENT_GATE_CONVO_MODE=negative_only` as default** if operator finds `silent` overshoots — config-knob flip, no code change.

</deferred>

---

*Phase: 44-event-gate-durable-signal-outbound-tenant-aware*
*Context gathered: 2026-05-21*
