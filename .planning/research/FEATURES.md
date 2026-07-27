# Feature Research: v1.12 Farm-Agent Python Port

**Domain:** Big-bang Node-to-Python rewrite of a live multimodal farm-event extraction agent
**Researched:** 2026-06-14
**Confidence:** HIGH (direct codebase read; no inference required — source is on disk)

---

## Context: This Is a Port, Not a New Product

Features here are the *behaviors the existing Node stack performs* that the Python stack must reproduce, plus the parity/validation capability needed to prove the rewrite before cutover. The framing is:

- **Table Stakes** = must work at cutover or the Python stack cannot replace Node
- **Differentiators** = opportunistic improvements locked into scope (Phase-50 quote bugs, Foray seams)
- **Anti-Features** = things the team might be tempted to port or improve that should be deferred

"Users" for this port are the three farmers (Santi / Vikki / Selina) whose live Signal messages drive the pipeline, and the operator who cuts over.

---

## Feature Categories

Seven behavioral categories map to module boundaries and build phases:

1. Signal I/O
2. Chamber Alerting (watchdog/state machine)
3. Capture Pipeline (inbound message ingestion)
4. Event Gate
5. Extraction Pipeline (multimodal LLM)
6. Confirm Loop (farmer YES/NO/EDIT state machine)
7. farmOS Write Path (commit watchdog + idempotent upserts)
8. Parity / Validation (golden-corpus replay, output diffing)
9. Observability / Tenancy (cross-cutting)

---

## Table Stakes (Cutover Blockers)

Features that must exist and be proven correct before the Node process is stopped.

### 1. Signal I/O

| Feature | Why Cutover Blocks Without It | Complexity | Notes |
|---------|-------------------------------|------------|-------|
| send() to DM (e164) and group (groupId) | All farmer-facing output | LOW | signal-cli /v2/send REST; groupId translation internal_id→id-b64 via /v1/groups |
| receive() poll loop (long-poll /v1/receive) | All inbound message ingestion | LOW | timeout param; fail-open per tick |
| Attachment fetch (/v1/attachments/{id}) | Audio + image capture | LOW | returns bytes; caller writes to disk |
| Per-send rate cap (max sends/hour) | Prevents farmer spam if alerter misbehaves | LOW | sliding window, runtime-overridable |
| quote threading (send with quote={timestamp,author,message}) | Phase-50 fix — quote replies render as native threads | MEDIUM | signal-cli 0.14.2 locked shape; timestamp can be numeric string; fail-open (send without quote on invalid) |
| Outbound persistence to signal_outbound (Timescale) | Audit + future quote-resolve lookups | LOW | fail-open: insert failure must not block send() |
| Multi-farmer routing: reply to envelope.source | Correct DM delivery per farmer | LOW | envelope.source is the sender's E164 |
| Group-vs-DM context discrimination | Bot must not spam group with extraction replies | MEDIUM | triggers: @mention, command keyword, or bot-authored quote |
| Envelope source routing (signalFarmerMap: phone→slug) | Farmer identity on capture rows | LOW | Map loaded from tenant config / env at boot |
| Hourly send cap bypass for heartbeat | Heartbeat must fire even under load | LOW | bypassCap flag |

### 2. Chamber Alerting (State Machine)

| Feature | Why Cutover Blocks Without It | Complexity | Notes |
|---------|-------------------------------|------------|-------|
| RH out-of-band alert (OOB_WINDOW, cooldown) | Primary alerting function | MEDIUM | State: OK/PENDING/FIRING/SNOOZED; per-type perType map |
| Pi-offline / chamber-dark alert (fc1LastMsgTs + 3-OR triggers) | Live farm safety alert | MEDIUM | bridge aggregates fc1 publisher freshness; D-02 wiring lesson from Phase 46 |
| Sensor staleness alert (sht30/scd41 freshness watchdogs) | Sensor failure detection | MEDIUM | Per-sensor lastSeenMs initialized to bootTime (never null) |
| Humidifier-stuck alert | Equipment protection | MEDIUM | ON for >N minutes |
| Cooldown per alert type (WARN vs CRITICAL) | Prevents alert flooding | LOW | criticalCooldownMin vs cooldownMin from config |
| Snooze / mute (snooze command parser, snoozedUntil state) | Farmer flow control | LOW | parse "mute 2h", "snooze 30m" from DM or @mention in group |
| Daily heartbeat (scheduled by hour, with chamber summary) | Operator health attestation | LOW | getSummary() = rh, temp, co2, humidifier, cycles; bypassCap |
| Periodic tick (30s) for offline/stuck detector liveness | Watchdog fires even in silence | LOW | setInterval equivalent |
| Tier C runtime overrides (alerter_globals from bridge WS) | Operator can tune thresholds live | LOW | max_sends_per_hour, heartbeat_hour; resolved at call time |
| Alert formatting: fmtNum, fmtDuration, fmtRelative, hhmm | Farmer-readable message text | LOW | hhmm() currently uses UTC ignoring TZ (known bug; ALERTER_TZ_TORONTO); preserve bug or fix it as opportunistic |

### 3. Capture Pipeline

| Feature | Why Cutover Blocks Without It | Complexity | Notes |
|---------|-------------------------------|------------|-------|
| Inbound envelope handling (dataMessage + attachments) | All capture flows through this | LOW | Both envelope wrapper shapes (env.envelope.dataMessage AND env.dataMessage) |
| Attachment download + disk write (ULID-named, dated path) | Audio/image persistence | LOW | buildPath: YYYY-MM-DD/HH-MM-SS-{ulid}.{ext} |
| Audio content-type detection + Whisper transcription | Multimodal fusion input | MEDIUM | transcribeClient.transcribe(); AUDIO_TYPES set |
| Image content-type detection + path tracking | Multimodal fusion input | LOW | IMAGE_TYPES set; paths passed to extractor |
| signal_capture row insert (best-effort fail-open) | Audit + capture history for extraction | LOW | ULID PK; capturedAtMs, farmerSlug, text, transcript, imagePaths |
| Farmer slug resolution (phone→slug via signalFarmerMap) | Per-capture farmer identity | LOW | Unknown senders → '(unassigned)' sentinel per B6 |
| Capture history lookup (last N captures per farmer) | Provides context to extractor (inFlightDraft) | LOW | captureHistory.getRecent(farmerId, n) |
| Sensor snapshot fetch (bridge HTTP /api/snapshot) | Chamber context for extraction | LOW | Optional; fail-open on timeout |
| Capture retention job (cron, prune old rows) | DB housekeeping | LOW | node-cron equivalent; TZ-safe (see PITFALLS: node-cron 4.x non-UTC TZ bug) |

### 4. Event Gate

| Feature | Why Cutover Blocks Without It | Complexity | Notes |
|---------|-------------------------------|------------|-------|
| Haiku 4.5 classifier (forced tool_use, 2s timeout, fail-open) | Guards extraction pipeline from non-events | MEDIUM | Returns {ok, is_event, kind, confidence}; on failure: fallthrough='forced' (extraction proceeds) |
| Rule-based pre-filter (commands, snooze, short text) | Fast-path bypass of LLM call | LOW | Pure function rules; injected for testability |
| Convo mode gate (eventGateConvoMode: silent / negative_only / off) | Controls when llmClient.compose runs | LOW | Config-driven; convo reply is the old Phase-25 LLM reply path |

### 5. Extraction Pipeline

| Feature | Why Cutover Blocks Without It | Complexity | Notes |
|---------|-------------------------------|------------|-------|
| Multimodal content block builder (text + transcript + images) | Fuses all signal sources into one Anthropic call | MEDIUM | buildContentBlocks; image blocks are base64-encoded inline |
| Cacheable system prompt + few-shot (6 turns, last tu_fewshot_6) | Extraction quality + prompt cache hits | HIGH | CACHEABLE_SYSTEM_BLOCKS; few-shot must end with tool_result closing tu_fewshot_6 |
| Forced tool_use (submit_extraction, Zod schema) | Schema-enforced JSON output | HIGH | Submission schema: {drafts[], continuity, continuity_reason}; inlineTopLevelRef fix for $ref |
| Zod/schema retry (is_error tool_result on first parse failure) | Handles model schema violations | MEDIUM | One retry max; second failure returns schema_invalid |
| Multi-draft output (drafts[]) + continuity decision | Handles multi-event pages | HIGH | Pack result exposes both multi-draft and legacy single-draft view |
| Per-field provenance ({value, confidence, sources[]}) | Ask-back targeting | MEDIUM | Provenanced() Zod wrapper; SOURCE_ENUM |
| SeedingSession shape (groups[], B5 block-name minting, NEEDS_SEQ sentinel) | Canonical inoc session | HIGH | Multi-parent inoc is the dominant farm shape; SEQ per session |
| corpus_context injection (year hint for backfill) | Prevents year hallucination on 2025 paper logs | LOW | Optional dict injected into user content block |
| inFlightDraft injection (continuity context) | Multi-capture session state | LOW | JSON-serialized prior draft in user content block |
| farmerCorrection injection (EDIT loop) | Re-extraction with farmer feedback | MEDIUM | Appended as text block after inFlightDraft |
| onLlmCall observer hook (backfill response persistence) | Enables responses.jsonl for paid-LLM cost tracking | LOW | Fire-and-forget; observer errors must not propagate |
| signal_draft persistence (extraction-db, ULID/hex ID) | Draft state across ticks | MEDIUM | Status machine: pending → awaiting_farmer → confirmed / discarded / expired |
| Extraction outbound dispatcher (ask-back + preview send) | Farmer receives draft to confirm | MEDIUM | Routes to envelope.source (DM) or group per reply_target_kind |

### 6. Confirm Loop

| Feature | Why Cutover Blocks Without It | Complexity | Notes |
|---------|-------------------------------|------------|-------|
| Confirm FSM: AWAITING_FARMER / CONFIRMED / DISCARDED / EXPIRED / NEEDS_REVIEW | Core lifecycle | MEDIUM | Pure transition function; side_effect names dispatched by outboundConfirm |
| YES handler (idempotent re-YES ack) | Prevents double-commit on duplicate message | MEDIUM | tryMarkOutcomeAckSent CAS claim |
| NO handler (discard + ack) | Farmer discard path | LOW | signal_draft status → discarded |
| EDIT handler (re-extraction with farmerCorrection, max 3 turns) | Iterative correction | MEDIUM | Runs extractor again with correction; edit_cap → NEEDS_REVIEW |
| Strain confirm-before-mint (strain-pending sub-state) | Unknown fungi_type batched ask-back before farmOS write | HIGH | 14-code curated set; exact-match; createMissingFungiType:false |
| Nudge (30m ping if awaiting) | Prompts farmer to respond | LOW | nudge_sent_at CAS; send once only |
| Expiry watchdog (auto-discard after timeout) | Stale drafts never auto-commit | LOW | cron-style periodic check |
| Compact session preview (group table, human-readable) | Farmer compares to notebook | MEDIUM | preview-builder.js; seeding session shape renders group table |
| quote threading on confirm sends | Farmer sees reply-chain in Signal | MEDIUM | Phase-50 fix; resolves signal_msg_ts lookup from signal_outbound to get quote context |
| Signal draft event audit table (signal_draft_event) | Per-transition audit log | LOW | Append-only; transition type + timestamp |
| Outbound confirm persistence (signal_outbound rows per ack send) | Outbound audit | LOW | intent classification: confirm_ack, discard_ack, nudge, etc. |

### 7. farmOS Write Path

| Feature | Why Cutover Blocks Without It | Complexity | Notes |
|---------|-------------------------------|------------|-------|
| farmOS HTTP client (token auth, retries, exponential backoff) | All farmOS writes | MEDIUM | backoffMs config; retryMax; auth via username+password → OAuth token |
| Commit router (activity / harvest / input / observation / seeding / seeding-session) | Routes draft type to correct commit function | MEDIUM | commitRouter.commit(draft, ctx) dispatch |
| Asset create (fungi: block, batch, bag, group) | farmOS entity creation | HIGH | Per B1-B4; name, type, fungi_type, parent rels |
| Log create (seeding, activity, input, observation, harvest) | farmOS event recording | HIGH | Per B7; native log types only (C5) |
| Upsert-by-stable-identity (merge) | Idempotent re-runs; no duplicate assets | HIGH | mergeAssetFields: array-ref set-union, scalar singleton conflict, notes split-dedup-join; IdentityMutationError on name/type change |
| fungi_type cache (term lookup, create if missing) | Avoids repeated /taxonomy_term lookups | LOW | fungi-type-cache.js; createMissingFungiType:false in backfill mode |
| fungi_xing cache (cross-ref term lookup) | Same | LOW | fungi-xing-cache.js |
| Strain resolver (variant normalization: POY→KOY, LIM→LIMA, etc.) | Correct strain attribution | HIGH | Silent misattribution was the v1.11 POY-as-KOY defect; curated 14-code set |
| Field-scoped image upload (/api/asset/{type}/{uuid}/image) | Photo attachment to farmOS logs | HIGH | NOT /api/file/file (rejects jpg); creates+links in one call per [[farmos_image_upload_needs_field_scoped_route]] |
| Commit watchdog (periodic drain of confirmed drafts) | Async commit pipeline | MEDIUM | tick: releaseStaleLocks → findConfirmed → acquireLock → commit → markCommitted / requeueRetry / markFailed |
| Origin guard (draft.origin field) | Prevents backfill confirmed-drafts leaking to prod watchdog | HIGH | v1.13 candidate but essential in any env where dev and prod share timescale; check project_v113_watchdog_origin_guard_candidate |
| Audit logger (per-commit structured log) | Operator "what did the bot write today" query | LOW | farmosUrl + draft UUID + farmer + asset/log IDs + farmOS response |
| Commit outcome ack (send_commit_outcome_ack to farmer) | Farmer receives commit confirmation | MEDIUM | Phase-45 ACK-04; tryMarkOutcomeAckSent CAS for idempotency |

### 8. Parity / Validation (Critical Category)

The parity gate is what makes big-bang cutover safe. This is the primary deliverable unique to v1.12 (the Node stack has no equivalent).

| Feature | Why Required | Complexity | Notes |
|---------|--------------|------------|-------|
| Golden corpus fixture set | Deterministic replay inputs | MEDIUM | Minimum: the 10-page Phase-55B audit set + the May-22 inoc session; expand to full 73-page set for GA |
| Node extraction baseline capture (responses.jsonl) | Ground-truth for Python comparison | LOW | Already ships via onLlmCall observer; just need to run Node against corpus and save outputs |
| Python extractor corpus replay | Runs Python extractor against same inputs | MEDIUM | Same onLlmCall observer pattern; outputs go to separate jsonl |
| Per-draft field-level diff (Node vs Python) | Catches silent schema drift | HIGH | Compare {drafts[].draft, continuity, capture_kind}; per-field match rate; flag mismatches |
| Signal message round-trip smoke (send + receive) | Proves I/O layer works | LOW | Send from bot, receive from a test account; verify body + quote threading |
| Confirm FSM parity (event sequences) | Proves state transitions match | MEDIUM | Property-based or table-driven: same event sequence → same side_effects on both implementations |
| farmOS write parity (dry-run mode) | Proves commit shapes are identical before any real writes | MEDIUM | Python commit functions emit JSON payloads; diff against Node's saved payloads from dev farmOS |
| Shared-Timescale prod-leak guard | Shadow runs must not feed prod watchdog | HIGH | Use throwaway pg :5433 OR set draft.origin='validation' and gate watchdog per [[project_backfill_confirmed_drafts_leak_to_prod_via_live_watchdog]] |
| Cutover checklist (smoke gate) | Defines "ready to flip" | LOW | Signal round-trip OK; extraction parity >95% field match; confirm FSM identical; farmOS write shapes identical |

### 9. Observability / Tenancy

| Feature | Why Required | Complexity | Notes |
|---------|--------------|------------|-------|
| Tenant config loader (tenants/{id}/config.yaml) | Foray-ready config isolation | LOW | Path-traversal check; graceful degrade on missing file |
| SIGNAL_FARMER_MAP (phone→slug) from tenant YAML or env | Farmer identity | LOW | Both shapes: YAML object and comma-separated string env |
| Structured boot log (sender, recipient, defaultTarget, farmer-map count, TZ) | Operator confidence at startup | LOW | farmer-map count is the tell for alerter config mode [[project_alerter_config_env_not_tenant_yaml_live]] |
| Signal send rate accounting (sendsThisHour()) | Operator observability | LOW | |
| Best-effort DB init (all initDb calls fail-open) | Alerting survives transient PG outage | LOW | |
| Graceful crash handlers (unhandledRejection / SIGTERM) | Container restart hygiene | LOW | |
| Foray-ready module seams (separable units: signal, extraction, confirm, farmos) | SEED-010 carve-out near-free | MEDIUM | Each category above should be importable independently with injected deps |

---

## Differentiators (Opportunistic, In Scope for v1.12)

Improvements over the Node stack that are locked into the port scope. These are not strictly required for parity but are the stated reason for the port.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Phase-50 wire-level quote rendering (fix) | Signal native quote threading actually works | MEDIUM | Node bug: quote.timestamp sometimes passed as string; Python port gets it right from day 1; already validated signal-cli 0.14.2 shape |
| Foray-ready module seams | Python stack structured for SEED-010 Apache-2.0 extraction later | MEDIUM | Clean __init__.py boundaries; dependency injection everywhere; no global state |
| TZ-correct time rendering in farmer messages | Fix the Toronto-stuck TZ bug [[project_alerter_tz_toronto_legacy]] | LOW | Easy opportunistic fix: use ZoneInfo('America/Montevideo'); hhmm() renders local time |
| Parity validation harness (new capability) | Makes future ports/refactors safe | HIGH | Node has no equivalent; Python port ships the corpus-replay diff infra |

---

## Anti-Features (Do Not Port or Extend)

| Anti-Feature | Why Not | What to Do Instead |
|--------------|---------|-------------------|
| QR scan binding flow (qr.js, farmOS QR asset lookup) | Schema locked but not exercised by farmers; adds complexity | Leave as stub / skip port until a real session exercises it |
| Strict 1:1 behavioral parity on known bugs | Some Node bugs should not be preserved | Enumerate known divergences (TZ, quote string-vs-number) in parity spec; those diffs are expected |
| farmOS-agent reimplementation | src/farmos-agent/ is already Python -- reference it | Reference the existing farmos_client.py for auth patterns |
| Dual-stack (run Node + Python in parallel with traffic split) | 30s commit-watchdog drain window creates dual-commit risk | Big-bang only: validate offline, single cutover |
| v1.13 auto-commit narrowing | Depends on v1.11 confirm corpus; not scoped | Carry to v1.13 |
| 55B follow-ons (receipt dup false-positive, D-03 image-on-session) | Minor; deferred unless trivially folded | Carry unless encountered naturally during port |
| ML vision / contamination detection | Separate pipeline milestone | Not in alerter scope |
| Multi-chamber FC-2 / fc_core / Mission Control | Stay Node/ROS | Only alerter/ slice ports |

---

## Feature Dependencies

```
Signal I/O
    └──required-by──> Capture Pipeline
                          └──required-by──> Event Gate
                                                └──required-by──> Extraction Pipeline
                                                                      └──required-by──> Confirm Loop
                                                                                            └──required-by──> farmOS Write Path

Chamber Alerting
    └──depends-on──> Signal I/O (send)
    └──depends-on──> Bridge WebSocket client (bridge-client.js equivalent)

Parity / Validation
    └──requires──> Extraction Pipeline (Python impl)
    └──requires──> Node baseline corpus captures (responses.jsonl)
    └──requires──> farmOS Write Path (dry-run mode)

Tenancy / Observability
    └──cross-cuts──> All categories (inject tenantId, logger, clock everywhere)
```

### Dependency Notes

- **Extraction Pipeline requires Signal I/O**: ask-back replies and preview sends route through signalClient.send()
- **Confirm Loop requires Extraction Pipeline**: consumes signal_draft rows created by extraction
- **farmOS Write Path requires Confirm Loop**: commit-watchdog drains only `confirmed` status rows
- **Parity gate must complete before cutover**: no Node → Python flip until parity gate passes
- **Origin guard must exist before any shadow/validation run that touches shared Timescale**: otherwise confirmed-draft rows from validation pollute prod commit-watchdog [[project_backfill_confirmed_drafts_leak_to_prod_via_live_watchdog]]

---

## Build Order Recommendation

Based on dependencies and risk, the natural phase sequence is:

**Phase 1 — Foundation**: Python package skeleton, config loader, Timescale pool, DB schema init (all initDb equivalents), tenant config loader. No behavior yet -- just the wiring harness.

**Phase 2 -- Signal I/O**: send (DM + group, rate cap, quote, outbound persistence), receive loop, attachment fetch. First farmer-visible behavior. Includes Phase-50 quote fix.

**Phase 3 -- Chamber Alerting**: state machine (pure Python), bridge WebSocket client, heartbeat scheduler, snooze parser. Alerting is the highest-uptime function -- getting it green early reduces prod risk.

**Phase 4 -- Capture Pipeline**: envelope handling, attachment write, Whisper transcription, capture-db, farmer-map resolution, event gate (Haiku classifier + rules).

**Phase 5 -- Extraction Pipeline**: multimodal content builder, system prompt + few-shot port, Zod→Pydantic schema translation, extractor, multi-draft pack, signal_draft persistence, outbound dispatcher.

**Phase 6 -- Confirm Loop**: FSM, confirm-db, watchdog, edit handler, strain ask-back, preview builder, quote threading on ack sends.

**Phase 7 -- farmOS Write Path**: farmOS client (auth + retry), commit router (all log types), asset upsert + merge, fungi_type/xing caches, strain resolver, field-scoped image upload, commit watchdog, audit logger, origin guard.

**Phase 8 -- Parity Gate**: Node baseline corpus capture → Python corpus replay → field-level diff → pass/fail gate → cutover checklist execution.

---

## MVP Definition (Cutover-Ready)

### Must be green before cutover

- [ ] Signal I/O: send + receive + quote threading + outbound persistence
- [ ] Chamber alerting: RH / pi-offline / chamber-dark / sensor-staleness / snooze / heartbeat
- [ ] Capture pipeline: audio + image + text ingest, transcription, capture-db
- [ ] Event gate: Haiku classifier + rules
- [ ] Extraction: multimodal fusion, Sonnet schema extraction, signal_draft persistence
- [ ] Confirm loop: YES/NO/EDIT/expiry/strain-ask-back + farmer previews
- [ ] farmOS write: all log types, asset upsert-by-stable-identity, strain resolver, image upload, commit watchdog
- [ ] Origin guard (prevents prod-leak in any shared-Timescale topology)
- [ ] Parity gate: >=95% field-level match on golden corpus; Signal round-trip smoke; confirm FSM identical; farmOS payload shapes identical

### Add after cutover (v1.12.x)

- [ ] TZ fix (hhmm() → local time) -- trivial but not a cutover blocker
- [ ] Foray module extraction (SEED-010) -- separate milestone, seams just need to be clean

### Defer (v1.13+)

- [ ] Auto-commit narrowing (v1.13 depends on v1.11 confirm corpus)
- [ ] 55B follow-ons (receipt dup false-positive, D-03 image-on-session)

---

## High-Risk Silent Regression Areas

These are behaviors that tests will not catch without explicit golden-corpus or shadow-mode comparison:

### 1. LLM Prompt / Schema Drift (CRITICAL)

The Python port must translate the Anthropic SDK call shape, the cacheable system prompt (CACHEABLE_SYSTEM_BLOCKS), all 6 few-shot turns, and the Zod tool schema into Python equivalents. Any change to:
- few-shot turn count or order
- tu_fewshot_6 closing tool_result
- inlineTopLevelRef (the $ref flattening for Anthropic's input_schema requirement)
- Submission schema field names / enum values

...will cause silent extraction failures (schema_invalid on retry, drafts:[] on success) that look like a recoverable degradation but actually produce no output. The parity gate must run extraction against the same corpus under both stacks.

### 2. Idempotency Keys and Commit Identity (CRITICAL)

The upsert-by-stable-identity logic (stable_identity field on signal_draft rows, used to probe farmOS for existing assets before create-vs-patch decision) must produce identical stable_identity values for the same logical event. A Python port that generates different stable_identity strings will silently create duplicate farmOS assets instead of updating existing ones. Test with actual dev farmOS; compare asset counts before/after re-runs.

### 3. Quote Threading (HIGH)

The Phase-50 fix involves: (a) persisting signal_msg_ts (bigint, Signal-native ms-ts from /v2/send response) to signal_outbound, (b) resolving quote.timestamp → related signal_outbound row → related_draft_id at send time, (c) building the quote={timestamp, author, message} payload correctly. In Node, quote.timestamp was sometimes passed as a numeric string; signal-cli silently rejects non-numeric or accepts -- the exact behavior depends on signal-cli version. Python port must: coerce to Number (int), pass as int in JSON, test with signal-cli 0.14.2. Regression: farmer reply-chains appear as standalone messages instead of threads.

### 4. Timezone / Formatting (MEDIUM)

hhmm() in Node uses toISOString() which is UTC, ignoring the configured TZ (known bug: [[project_alerter_tz_toronto_legacy]]). The Python port should fix this (use ZoneInfo), but the parity spec must document this as an intentional divergence so the diff tool does not flag it as a regression. fmtNum, fmtDuration, fmtRelative must produce byte-identical output for the same inputs (farmers rely on the exact format).

### 5. Watchdog Timing and Origin Guard (HIGH)

The commit-watchdog drains `status='confirmed'` rows every 30s. In a shared-Timescale environment, any validation run that writes confirmed rows without an origin guard will be consumed by the prod watchdog within 30s, writing to real farmOS. The Python port must ship origin guard before any validation run that touches shared Timescale. This is the prod-leak hazard documented in [[project_backfill_confirmed_drafts_leak_to_prod_via_live_watchdog]].

### 6. Strain Resolution (HIGH)

The POY-as-KOY silent misattribution was the v1.11 fidelity defect. The strain-resolver (variant normalization, curated 14-code set, exact-match against farmOS terms) must be ported exactly. The parity gate should include at least one corpus fixture that exercises a variant (POY, LIM, SHI abbreviations) and verify the resolved strain matches Node output.

### 7. Fail-Open vs Fail-Closed Semantics (MEDIUM)

The Node stack is carefully fail-open in all DB paths: every initDb, insertCapture, insertOutbound, insertDraft failure is caught and logged as warn; the alerter continues. A Python port that raises exceptions from these paths and propagates them will silently kill the alerter. All DB operations must use try/except with logging and return {ok, reason} equivalents.

---

## Parity / Validation: Detailed Approach

### What to Build

**Step 1: Node baseline corpus capture**
Run the existing Node extractor against the golden corpus (the 10-page Phase-55B audit set + May-22 inoc session + any additional pages selected for strain/type coverage). The `onLlmCall` observer already ships in the Node extractor; point it to a `node-baseline/responses.jsonl` file. Capture: captureId, drafts[], continuity, capture_kind, usage, request_hash.

**Step 2: Python extractor corpus replay**
Implement the same `onLlmCall` observer in the Python extractor. Run against the same inputs (same attachment files, same text/transcript). Write to `python-port/responses.jsonl`.

**Step 3: Field-level diff**
Write a diff script that pairs entries by captureId (or request_hash) and computes:
- Per-draft field match: type, event_date, species, qty, block_names, parent_names, notes
- continuity match
- capture_kind match
- Report: field match rate per field, total match rate, list of mismatches with before/after values

**Step 4: Confirm FSM parity**
Run table-driven tests: for each (initial_status, event_type) pair, assert Python transition() returns the same {nextStatus, side_effects[]} as Node. These are pure functions; no LLM call needed.

**Step 5: farmOS payload parity (dry-run)**
Point both Node and Python commit functions at a dry-run mode that returns the would-be farmOS JSON payload without making any HTTP calls. Diff the payloads for the same confirmed draft.

**Step 6: Signal round-trip smoke**
From a dev Signal account, send a test message to the bot. Verify: (a) receive loop ingests it, (b) extractor classifies it, (c) bot replies with a preview in a native quote thread. This is the only test that exercises signal-cli end-to-end.

### Pass/Fail Thresholds (Recommended)

| Check | Pass Threshold | Notes |
|-------|----------------|-------|
| Extraction field match rate | >= 95% across golden corpus | Fields: type, event_date, species, qty, block_names, parent |
| Continuity match rate | >= 90% | Continuity is LLM judgment; some variance expected |
| Confirm FSM parity | 100% | Pure function; must be exact |
| farmOS payload parity | 100% on stable_identity, asset type, log type | Field-level match on all identity fields |
| Signal round-trip smoke | Pass (bot replies in quote thread) | Binary; no threshold |

### Prod-Leak Prevention During Validation

Use throwaway Postgres at :5433 (Option A from [[project_backfill_confirmed_drafts_leak_to_prod_via_live_watchdog]]):
- Python stack connects to :5433 for all validation runs
- Commit watchdog disabled or pointed at dev farmOS :18080 only
- Never run Python commit watchdog against shared prod Timescale before cutover

---

## Sources

- `src/agents/alerter/src/index.js` -- boot wiring, full dependency graph
- `src/agents/alerter/src/signal.js` -- send/receive, quote threading, outbound persistence
- `src/agents/alerter/src/state.js` -- alert type state machine, initialState shape
- `src/agents/alerter/src/capture.js` -- capture pipeline orchestrator
- `src/agents/alerter/src/extraction/extractor.js` -- LLM call shape, retry, observer hook
- `src/agents/alerter/src/extraction/schemas/seeding-session.js` -- multi-parent inoc schema
- `src/agents/alerter/src/confirm/state-machine.js` -- confirm FSM (pure)
- `src/agents/alerter/src/farmos/commit-watchdog.js` -- commit pipeline
- `src/agents/alerter/src/farmos/merge.js` -- upsert-by-stable-identity merge rules
- `src/agents/alerter/src/event-gate/haiku-classifier.js` -- event gate LLM call
- `src/agents/alerter/src/outbound-db.js` -- signal_outbound schema + signal_msg_ts
- `src/agents/alerter/src/config.js` -- tenant config loader, signalFarmerMap parsing
- `src/agents/alerter/src/message.js` -- fmtNum, fmtDuration, hhmm
- `.planning/PROJECT.md` -- v1.12 milestone context, strategy decisions
- Memory: [[project_backfill_confirmed_drafts_leak_to_prod_via_live_watchdog]], [[project_alerter_tz_toronto_legacy]], [[project_farmos_image_upload_needs_field_scoped_route]], [[project_phase55b_hard_gate_green_2026_06_14]], [[project_v113_watchdog_origin_guard_candidate]]

---

*Feature research for: v1.12 Farm-Agent Python Port*
*Researched: 2026-06-14*
