# Tenant-ID Retrofit Cost Map (2026-05-17)

**Scope:** Full inventory of schema tables and configuration in src/agents/alerter/ and src/mission-control/bridge/, classified by retrofit strategy under OSS-Foray Option α (tenant-aware from day one).

---

## Tables (Database Schema)

### (a) NEW-IN-V1.8 — Ship with tenant_id from day one

**signal_outbound** (planned v1.8, durable bot outbound messages)
- Status: Not yet implemented; referenced in notes 2026-05-17-llm-outbound-amnesia.md (Option b deferred to v1.9)
- Proposed columns: id, created_at, recipient_e164, message_type, body, tenant_id (indexed)
- Requirement: `tenant_id text NOT NULL` indexed
- v2.0 implication: Clean extraction as multi-tenant from v1.8 onward

### (b) EXISTING-MOSSROCK-DATA — Defer ALTER to v2.0 extraction

**signal_capture** (Phase 25, live in Mossrock)
- Rows: ~10k-50k estimated (4 weeks of farmer messages, moderate volume)
- Columns: id, captured_at, sender, message_type, raw_text, attachment_paths[], llm_session_tag, llm_reply, degraded, expired, group_id, farmos_person, reply_target_kind
- Current constraint: sender (E.164 phone) is the de-facto tenant proxy
- Retrofit: Add `tenant_id text` column in v2.0 extraction; backfill sender-to-tenant mapping during carve-out
- Risk: Moderate. Cross-tenant queries on sender alone are possible today; tenant_id prevents accidental leakage

**signal_draft** (Phase 38, live in Mossrock)
- Rows: ~500-2000 estimated (1-2 per inbound message, most expired/discarded within 24h)
- Columns: id, created_at, updated_at, sender_e164, farmos_person, source_capture_ids[], status, log_type, draft_json, per_field_confidence, askback_turns, farmer_facing_preview, needs_review_reason, reply_target_kind, group_id, edit_turn_count, nudge_sent_at, confirmed_at, discarded_at, expired_at, terminal_reason, farmos_response, committed_at, commit_failed_reason, commit_attempt_count, committed_at_attempt
- Current constraint: sender_e164 is the de-facto tenant key
- Retrofit: Add `tenant_id text` column in v2.0; backfill from signal_capture mapping; drop unique index `idx_signal_draft_in_flight_per_sender` and replace with `(tenant_id, sender_e164)` scope
- Risk: Moderate. The partial unique index on in-flight drafts assumes global sender uniqueness; will silently permit multi-tenant drafts per sender today

**signal_draft_event** (Phase 39, audit log for drafts)
- Rows: ~5000-20000 estimated (7-15 events per draft, retention ~30 days)
- Columns: draft_id, seq, event, payload, created_at
- Current constraint: composite PK (draft_id, seq); draft_id references signal_draft
- Retrofit: FK on draft_id must cascade tenant_id constraint; add `(draft_id, tenant_id)` coverage in v2.0
- Risk: Low. No direct sender reference; tenant is inherited from FK

**timelapses** (Phase 23, MissionControl bridge, chamber-specific)
- Rows: ~1000 estimated (one per camera-date pair, 365 days = one chamber)
- Columns: camera_id, date, file_path, frames_used, composed_at, duration_sec
- Current constraint: camera_id is implicitly Mossrock-specific (no cross-farm reuse of chamber hardware)
- Retrofit: Stays in mushy/ (not in Foray v0.1); mark camera_id as tenant-scoped if bridge ever multi-tenant
- Risk: Negligible. Not extracted in v0.1 OSS release

**telemetry** (Phase 999.1 bridge, hypertable for chamber telemetry)
- Rows: ~86M estimated (one per sensor reading, 10min interval, ~600/day, 4 months)
- Columns: topic, time (partitioning key), value, unique index (topic, time)
- Current constraint: topic (e.g., 'fc.humidity') scoped to one chamber
- Retrofit: Stays in mushy/ (chamber hardware); not extracted
- Risk: Negligible. Not extracted in v0.1

---

## Configuration (Env Vars & Static Maps)

### (c) CONFIG-TREE-MOVE — Tenant-key into tenants/<id>/ directory layout

**Tenant identity & secrets** (from config.js load())
- SIGNAL_SENDER (required) → tenants/mossrock/SIGNAL_SENDER
- SIGNAL_RECIPIENT (required) → tenants/mossrock/SIGNAL_RECIPIENT (farmer phone or group base64)
- SIGNAL_GROUP_ID (optional) → tenants/mossrock/SIGNAL_GROUP_ID
- SIGNAL_FARMER_MAP (optional, Phase 37 D-11) → tenants/mossrock/SIGNAL_FARMER_MAP ("+phone:slug,..." CSV)
- ANTHROPIC_API_KEY (required) → tenants/mossrock/ANTHROPIC_API_KEY

**FarmOS integration** (Phase 40, commit write path)
- FARMOS_URL → tenants/mossrock/FARMOS_URL
- FARMOS_USERNAME → tenants/mossrock/FARMOS_USERNAME
- FARMOS_PASSWORD → tenants/mossrock/FARMOS_PASSWORD
- FARMOS_INTEGRATION (0 or 1 feature flag) → tenants/mossrock/config.yaml

**Global (shared across tenants, not tenant-specific)**
- TZ (timezone, for date boundaries in alerter)
- TIMESCALE_HOST, TIMESCALE_DB, TIMESCALE_USER, TIMESCALE_PASSWORD (shared Postgres pool)
- WHISPER_URL (shared transcription service)
- BRIDGE_WS_URL, BRIDGE_HEALTH_URL (shared bridge infra for all chambers)
- SIGNAL_API_URL (shared signal-cli service)
- ALERT_* thresholds (RH_TARGET, OOB_N, COOLDOWN_MIN, etc. — Phase 29 Tier A/B/C/D)
- DASHBOARD_URL, LOG_LEVEL
- CAPTURE_* (base dir, retention days/cron) — apply to all tenants' captures
- DRAFT_*, MAX_* timeouts and turn caps — apply to all tenants' state machines
- COMMIT_* watchdog knobs (interval, batch cap, retry policy)

**Fuzzy boundary — could be tenant-scoped or shared; design choice pending v1.8**
- EXTRACTION_CONFIDENCE_THRESHOLD (Phase 38 D-03) — per-farmer override or global floor?
- SIGNAL_ADDITIONAL_SENDERS (optional multi-phone array) — Mossrock ops acks, should move to tenants/mossrock/

**Recommendation for v1.8 implementation:**
- Create `tenants/mossrock/config.yaml` with all tenant-specific keys above
- Boot code: env fallback chain: `tenants/<TENANT_ID>/key` → `tenants/mossrock/key` → env var → default
- CI/secrets: TENANTS_MOSSROCK_SIGNAL_SENDER and friends as GitHub secrets, injected at runtime
- v0.1 Foray: single-tenant, default to `tenants/example/config.yaml` with placeholders

---

## Fuzzy Tenant Boundaries

### 1. Farmer phone number as natural tenant key vs. multi-tenant groups

**Current state:** 
- SIGNAL_FARMER_MAP parseFarmerMap(env) creates a Map<E164, slug> at boot
- signal_capture.sender (E.164 phone) is the row-level tenant proxy
- signal_draft.sender_e164 same

**Fuzziness:**
- Mossrock has multiple farmers (Santi, Ash, ...) sending to one shared Signal group
- SIGNAL_RECIPIENT could be a group (base64, Phase 37 D-16)
- Each farmer gets a slug (e.g., "santi", "ash") from the map
- When extracting to Foray, second farm might have different group structure: individual farmers with DMs, or a different group layout

**Implication:**
- signal_capture.sender is not universally unique (Santi's number exists at Mossrock AND elsewhere)
- Add explicit `tenant_id` column now, index it alongside sender
- Don't rely on global sender uniqueness after v1.8

### 2. Shared lookup tables (if any)

**Current findings:** None identified in the codebase yet. Strain codes and modes are per-chamber (Mossrock only, staying in mushy/). FarmOS asset taxonomy is to-be-designed in v1.9.

---

## Summary: Cost of Going Tenant-Aware in v1.8

| Category | Count | Effort |
|----------|-------|--------|
| NEW-IN-V1.8 (add tenant_id at CREATE) | signal_outbound (1) | ~20 LOC DDL + DAO |
| EXISTING-MOSSROCK-DATA (defer ALTER) | signal_capture, signal_draft, signal_draft_event (3) | ~0 LOC now; ~50 LOC backfill + index rebuild in v2.0 |
| CONFIG-TREE-MOVE (add tenants/<id>/) | 10 env keys → YAML + boot chain | ~100 LOC config.js refactor + 20 LOC example |
| **Total v1.8 scope impact** | | **~120 LOC, one new table** |

**Extraction cost savings in v2.0:** By going tenant-aware now, v2.0 carve-out is a clean `SELECT * WHERE tenant_id != 'mossrock'` + YAML walk, not a 9-month ALTER + backfill ops event.

---

## Cross-refs

- `.planning/notes/2026-05-17-oss-foray-decision.md` (strategic decision, locked)
- `.planning/seeds/SEED-010-foray-oss-extraction.md` (extraction trigger conditions)
- `.planning/notes/2026-05-17-llm-outbound-amnesia.md` (signal_outbound planned shape, deferred to v1.9 in Option a*)
- `src/agents/alerter/src/config.js` (current env-var inventory)
- `src/agents/alerter/src/capture-db.js`, `src/agents/alerter/src/extraction/extraction-db.js`, etc. (current schema)
