---
date: 2026-05-17
author: claude (overnight schema audit for v1.8 Phase 44 planning)
scope: confirm whether signal_outbound table exists; enumerate all signalClient.send sites; current-state map of alerter DB schema
companion-notes:
  - .planning/notes/2026-05-17-is-this-an-event-gate.md (finding 7 design)
  - .planning/notes/2026-05-17-llm-outbound-amnesia.md (finding 1b design)
verdict: signal_outbound does NOT exist; 14 send sites in alerter (only 1 has DB durability); no Timescale hypertables in alerter schema; clean greenfield for v1.8.
---

# signal_outbound schema audit — v1.8 Phase 44 prep

## 1. Does `signal_outbound` exist?

**No.** Greps of `src/agents/alerter/src/db/`, `src/agents/alerter/src/extraction/`, and any `*.sql` / `schema*.js` in the alerter tree turned up zero references. Closest analog: `signal_capture.llm_reply` (text column, `capture-db.js:16`) — stores bot replies to conversational LLM calls only, written via UPDATE at `capture.js:200`.

The 2026-05-17 amnesia note (section 5) recommends a v1.7.x band-aid: surface `llm_reply` in `fmtHistory` for ~10 LOC. v1.8 supersedes that band-aid with the proper `signal_outbound` table per OSS-Foray Option α.

## 2. `signalClient.send(` call sites (current code)

14 individual call sites in `src/agents/alerter/src/`:

| File | Line | Body | DB durable? |
|---|---|---|---|
| receive-loop.js | 73  | "experiment dispatch unavailable (bridge unreachable)" | no |
| receive-loop.js | 85  | experiment response text | no |
| receive-loop.js | 91  | "experiment rejected: {err}" | no |
| receive-loop.js | 102 | "experiment cancelled (ended_at=...)" | no |
| receive-loop.js | 106 | "cancel rejected: {err}" | no |
| receive-loop.js | 112 | "experiment dispatch failed; check bridge logs" | no |
| receive-loop.js | 189 | exp.reply (experiment completion) | no |
| receive-loop.js | 211 | parsed.reply (multimodal extraction reply) | no |
| index.js | 180 | RH alert action.body | no |
| index.js | 183 | RH alert action.body (bypassCap) | no |
| index.js | 185 | RH alert action.body | no |
| capture.js | 192 | conversational LLM reply | **YES → signal_capture.llm_reply** |
| confirm/outbound-confirm.js | 33 | Phase 39 confirmation prompt | own draft-event log (signal_draft_event) |
| extraction/outbound.js | 55 | Phase 38 extraction preview / ask-back | own pipeline log |

The 2026-05-17 amnesia note grouped these as 6 categories (conversational, experiment acks, RH alerts, confirm prompts, extraction previews, attestation kickoffs). At the call-site granularity it's 14 lines. Phase 44 must thread every one of these through the `signal_outbound` write — easiest via a wrapped client or sink-fanout in `signal.js`.

## 3. signal_capture DDL trail (capture-db.js)

- CREATE TABLE (lines 7–20): 11 columns, regular Postgres (no hypertable). Project comment line 2: "per-farmer volume too low for hypertable."
- Two CREATE INDEX IF NOT EXISTS (lines 21–28).
- Three ALTER TABLE ADD COLUMN IF NOT EXISTS (lines 32–34, idempotent): `group_id`, `farmos_person`, `reply_target_kind`.

## 4. signal_draft DDL trail (extraction-db.js + confirm-db.js)

- extraction-db.js (lines 27–58): CREATE TABLE + 2 indexes + 1 placeholder ALTER (`needs_review_reason`).
- confirm-db.js (lines 21–48): 6 ALTER TABLE ADD COLUMN IF NOT EXISTS (`edit_turn_count`, `nudge_sent_at`, `confirmed_at`, `discarded_at`, `expired_at`, `terminal_reason`); plus `signal_draft_event` audit table.
- No Timescale features anywhere in alerter schemas.

## 5. Phase 44 implications

- New table `signal_outbound(tenant_id, intent, captured_at, sender_recipient, body, attachments_jsonb, source_module, source_line)` is clean — no migrations of populated tables required.
- `tenant_id` ships indexed from day one per OSS-Foray Option α; existing tables defer ALTER to v2.0 extraction (see `2026-05-17-tenant-id-retrofit-map.md`).
- 14 send sites need wrapper or sink-fanout. Risk per amnesia note: "double bookkeeping if half the sends miss the wrapper." Mitigation: a single `signalClient.send` wrapper in `signal.js` that all 14 sites already call through — the persistence hook lives ONCE.
- Confirm + extraction outbound modules currently log to their own per-draft event stores. v1.8 should EITHER fan those into `signal_outbound` too (cleanest) OR leave them and accept some pre-existing partial duplication. Decide at discuss-phase.

## 6. Cross-refs

- `.planning/notes/2026-05-17-is-this-an-event-gate.md` (gate consumes `lastBotOutbound` rows)
- `.planning/notes/2026-05-17-llm-outbound-amnesia.md` (the v1.7.x band-aid; v1.8 supersedes)
- `.planning/notes/2026-05-17-tenant-id-retrofit-map.md` (full tenant-boundary inventory)
- Memory `[[feedback_keep_paper_trail_of_intermediates]]` — adds the `extraction_gate` audit column on signal_capture
