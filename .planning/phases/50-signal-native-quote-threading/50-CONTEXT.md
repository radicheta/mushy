# Phase 50: Signal-native quote threading for ack and reply routing — Context

**Gathered:** 2026-05-23
**Status:** Ready for planning
**Source:** post-Phase-45 spike (2026-05-23, see "Spike findings" section below)

<domain>
## Phase Boundary

Use Signal's native quote/reply primitive to eliminate referent-ambiguity in the alerter↔farmer loop:

**Outbound side.** When the bot sends an ack tied to a specific source capture (Phase 25 capture, Phase 38 extraction commit, Phase 45 commit_outcome_ack, Phase 39 confirm prompt, Phase 38 ask-back), the outgoing Signal message **quotes** the source capture. The farmer's Signal client renders the ack visually attached to their original message — no more "which observation are we talking about" gap.

**Inbound side.** When a farmer's incoming message **quotes** an earlier bot message, the receive-loop resolves the quote target back to a draft id (via `signal_outbound.signal_msg_ts` lookup) and routes EDIT/NO/freeform-correction to the **exact** quoted draft rather than the most-recent-active. The single-active-draft happy path is unchanged.

**Fallback.** When inbound has no quote (farmer types EDIT plain), the existing most-recent-active behavior runs, AND if >1 draft is active, the receive-loop emits a one-shot numbered ask-back (the original Phase 50 "ask-back" design, demoted from primary mechanism to ~5-line fallback).

In scope:
- Schema: `signal_capture.quote_msg_ts bigint` + `signal_capture.quote_author_e164 text` (persist incoming quote target). `signal_outbound.signal_msg_ts bigint` (persist Signal-native ms-since-epoch returned by /v2/send so future inbound quotes can resolve to this row).
- Outbound plumbing: `signal.js send()` gains a `quote: {timestamp, author, message}` option; passes through to `/v2/send`; persists returned `json.timestamp` into the new column.
- Outbound integration: `outbound-confirm.js send_commit_outcome_ack` (and at least the confirm-prompt path) fetches source capture's `signal_msg_ts` from `signal_capture` via `draftRow.source_capture_ids[0]` and quotes it.
- Inbound plumbing: receive-loop persists `dataMessage.quote.{id|timestamp, author/authorNumber}` into capture; new `findDraftByQuotedMsgTs(pool, quote_msg_ts)` helper.
- Inbound routing: EDIT/NO router checks quote-resolved draft first; falls back to most-recent-active (existing behavior); emits numbered ask-back when fallback finds >1 candidate.
- Live-fire UAT: trigger a fresh commit_failed in prod, verify ack lands as Signal quote-reply on farmer's phone (visual confirmation), farmer quote-replies EDIT, system routes to the correct draft (not most-recent), end-to-end logged in JSONL.

Out of scope (deferred):
- Quote propagation across multi-turn capture sessions (only first-capture is quoted; sufficient because the *ack* is what farmers reply to, not intermediate captures).
- Multi-language quote tooling (English-only; same posture as Phase 45 Plan 06).
- Quote support on group threads — out of initial scope because the failure mode this addresses is DM ack-debt; group quote routing can ship in a follow-on if surfaced.
- Editing/deleting the quoted message after send (Signal supports it; not needed for this loop).
- Backfilling `signal_msg_ts` for historical `signal_outbound` rows (only new rows from Plan 02 onward will have it; old rows remain quote-unresolvable, which is fine — they're already-acked).
</domain>

<decisions>
## Implementation Decisions

### Quote payload shape on outbound
**Use the nested `quote: {timestamp, author, message}` shape on `/v2/send`** (confirmed accepted by signal-cli `0.14.2` REST during 2026-05-23 spike). The flat `quote_author / quote_timestamp / quote_message` style may also work but is not the canonical v2 shape; ignoring it keeps one code path.

Why: spike-verified. Returned a valid Signal timestamp (`1779562666675`) → accepted.

### Persist Signal-native timestamps
**`signal_outbound.signal_msg_ts bigint` (new column).** Populated from the `{timestamp}` field already returned by `send()` (`signal.js:157`). Indexed for inbound quote-lookup (`CREATE INDEX idx_signal_outbound_msg_ts ON signal_outbound (signal_msg_ts) WHERE signal_msg_ts IS NOT NULL`).

**`signal_capture.quote_msg_ts bigint` + `quote_author_e164 text` (new columns).** Populated at capture time from `env.envelope.dataMessage.quote.{id|timestamp, author|authorNumber}` (receive-loop already reads `.author/.authorNumber` for group-trigger detection per `src/agents/alerter/src/receive-loop.js:23-24` — extend to persist).

Why: native Signal ms-since-epoch IS the cross-reference key. `signal_outbound.sent_at` (timestamptz) is wall-clock and lossy for this.

### What gets quoted on the outbound side
**The first entry in `draftRow.source_capture_ids[]`.** That's the farmer's original turn that produced the draft. Multi-capture sessions: only the FIRST capture is quoted (the rest are intermediate; the farmer's mental model is "I sent you the May 13 photo, you replied about it").

The lookup chain at dispatch time:
1. `draftRow.source_capture_ids[0]` → `capture_id`.
2. `SELECT signal_outbound.signal_msg_ts ... WHERE related_capture_id = $1 ORDER BY sent_at DESC LIMIT 1` — actually NO, we want the **inbound** capture, not bot outbound. Correct path:
3. `SELECT signal_capture.{id, sender as quote_author, captured_at} WHERE id = $1`. The Signal ms-ts of the inbound is NOT stored anywhere today.

**Decision: capture-side also needs a new column.** `signal_capture.signal_msg_ts bigint` — the inbound message's Signal-native ts, persisted at capture time from `env.envelope.dataMessage.timestamp`. This is the field the outbound `quote.timestamp` references.

So three schema additions total:
- `signal_capture.signal_msg_ts bigint` (inbound msg ts — what we quote)
- `signal_capture.quote_msg_ts bigint` + `quote_author_e164 text` (incoming-reply's quote target — what we resolve)
- `signal_outbound.signal_msg_ts bigint` (bot's outbound msg ts — what the farmer quotes back)

### Inbound resolution algorithm
When a capture arrives with `quote.timestamp` set:
1. `SELECT related_draft_id FROM signal_outbound WHERE signal_msg_ts = $1 LIMIT 1` — quote-resolved draft.
2. If found AND draft is still in an actionable state (`awaiting_farmer`, `commit_failed`) → route the reply to it (EDIT/NO/etc.).
3. If found but draft is terminal (committed/discarded) → polite "that one is already closed" ack (use Phase 45 Plan-06 template style); operator can amend via farmOS direct.
4. If NOT found (orphan quote — quote target was outside the alerter loop, e.g., quoting another farmer's message) → fall through to existing most-recent-active resolution.

### Fallback: numbered ask-back when >1 active and no quote
**Keep as fallback, NOT the primary mechanism.** When `findAwaitingForSender` returns >1 row AND incoming has no quote → emit the numbered ask-back (the original Phase 50 ask-back design, ~5 LOC at the dispatch site rather than a 3-plan feature). When `findAwaitingForSender` returns 1 row → behave as today (silent route to the one row). When the incoming has a quote → quote wins.

### Best-effort outbound (do not block ack on quote failure)
**If quote fetch for the source capture fails (capture not found, signal_msg_ts NULL, DB error), send the ack WITHOUT a quote rather than blocking the ack.** Logged warning. This honors `[[feedback_no_silent_failure_after_farmer_confirm]]` — we'd rather farmer get a vague ack than no ack at all. Plan-06 template's date+summary disambiguator remains as belt-and-suspenders for these cases.

### Cross-version quote field drift
**Accept both `quote.author` and `quote.authorNumber` on inbound** (receive-loop already does this per `receive-loop.js:24` Risk #9 comment from Phase 37). Persist the e164 form.

### Group threads
**Out of scope for first ship.** Outbound quotes in DM only. Group-thread quote routing has different semantics (multiple farmers, who's the quoter, mention-vs-quote disambiguation per Phase 37) and adds risk. Defer to a follow-on if a real group failure mode surfaces.

### Ack copy after threading
**Keep Plan 06 disambiguator template unchanged.** Even with quotes, the template's `{date} {log_type} ({summary})` is useful when the quote-bubble is clipped/collapsed in Signal client UI (Signal sometimes shows quote as "Original message" if too long) and serves users on older Signal versions that don't render quotes. Belt-and-suspenders — don't strip.
</decisions>

<spike_findings>
## Spike Findings (2026-05-23)

Documented in conversation; replicating key results here for downstream agents.

| Question | Answer | Evidence |
|---|---|---|
| signal-cli REST supports quote-on-send? | YES | Live probe: POST `/v2/send` with `{quote: {timestamp, author, message}}` returned `{"timestamp":"1779562666675"}` = accepted. Bot version `0.14.2`. |
| `signal_capture` has quote columns? | NO | `\d signal_capture` shows no quote_*; needs migration. |
| Inbound envelope already exposes quote? | YES | `receive-loop.js:23-24` reads `dm.quote.author / .authorNumber` today for group-trigger detection. Just not persisted. |
| `signal.js send()` handles quotes? | NO | Signature: `send(body, { bypassCap, to, intent, relatedCaptureId, relatedDraftId, sourceModule })`. No quote param. |
| Signal-native ts already in outbound return? | YES | `signal.js:157` returns `{ ok: true, timestamp: json.timestamp || now }`. Just not persisted. |
| Phase 25 prior work to reuse? | NO | `git log -S quote` in Phase 25 commits returned no relevant hits. |

**Safety check:** spike probe self-sent to bot's own phone (`+59891840205 → +59891840205`); confirmed via `SELECT … FROM signal_outbound WHERE sent_at > now() - 5min` returned 0 rows. No farmer was touched by the spike.
</spike_findings>

<canonical_refs>
## Canonical References (MUST read before planning)

- `.planning/phases/45-…/45-CONTEXT.md` — Phase 45 NORTH-STAR ack decisions; explains the ack-pipeline this phase enhances
- `.planning/phases/45-…/45-05-SUMMARY.md` — live-fire that surfaced the ambiguity; quote you'll cite if you need to remember WHY
- `[[project_phase45_followon_edit_no_disambiguation]]` — original Phase 50 (ask-back) spec; this phase supersedes it but the verbatim farmer feedback in that memory is the canonical motivation
- `[[feedback_no_silent_failure_after_farmer_confirm]]` — the rule that drives "send ack without quote rather than block on quote failure"
- `[[feedback_verify_signal_send_attribution]]` — paste-verification protocol; still applies, just easier when quote is present
- `[[feedback_unit_tests_dont_catch_wiring]]` — Plan-04's lesson; live-fire is the ship-gate, not unit tests
- `src/agents/alerter/src/signal.js:64-160` — `send()` implementation that gains the `quote` param
- `src/agents/alerter/src/signal.js:157` — Signal-native ts already returned, just not persisted
- `src/agents/alerter/src/receive-loop.js:23-24` — `dm.quote.author / .authorNumber` parsing precedent (Phase 37 group triggers)
- `src/agents/alerter/src/outbound-db.js:49-87` — `insertOutbound` extends to write the new column
- `src/agents/alerter/src/confirm/outbound-confirm.js:122-150` — `send_commit_outcome_ack` dispatch case that fetches source capture and quotes

## ROADMAP-named requirements (proposed; lock at plan-phase if not already)

QUOT-01 — `signal_outbound.signal_msg_ts` is populated on every successful send; non-null on ≥99% of new rows (allow 1% margin for signal-cli responses without timestamp).
QUOT-02 — `signal_capture.signal_msg_ts` is populated on every captured inbound message.
QUOT-03 — When a farmer's incoming message quotes a bot outbound, the receive-loop resolves the quoted-msg-ts to the originating `related_draft_id` and routes EDIT/NO accordingly. Verified by integration test + live-fire.
QUOT-04 — When outbound ack dispatch resolves a quote target, the outgoing message includes `quote: {timestamp, author, message}` in the /v2/send payload. Verified by integration test (mock signal-cli) + live-fire (visual on farmer's Signal).
QUOT-05 — When quote target lookup fails (capture missing or signal_msg_ts null), ack still sends, no exception escapes. Logged warning.
QUOT-06 — Numbered ask-back fires only when (>1 active draft) AND (no inbound quote). Verified by integration test covering 4 cases: 1-active / 1-active+quote / >1-active+quote / >1-active+no-quote.
</canonical_refs>

<code_context>
## Existing Code Insights

**Outbound (signal.js):**
- `createSignalClient` constructor already has `outboundDb, pool, tenantId` for persistence (Phase 44 D-14 plumbing).
- `send()` already returns `{ ok, timestamp }` — Signal-native ts is in scope, just discarded after persistence.
- Adding a `quote` param is a pass-through: fetch body builder near `signal.js:120` already constructs the JSON for /v2/send.

**Outbound dispatcher (outbound-confirm.js):**
- `send_commit_outcome_ack` case (`outbound-confirm.js:122`) already has draftRow in scope → `draftRow.source_capture_ids[0]` → SELECT capture row's signal_msg_ts → pass as quote.
- safeSend wrapper passes `intent` through to `signal.js`; needs to also pass `quote`.
- Same shape applies to `send_confirm_ack`, `send_discard_ack`, etc. — but first ship is just `send_commit_outcome_ack` + `send_confirm_ack` (the two highest-traffic farmer-facing acks). Other 6 side effects roll in once the pattern is proven.

**Inbound (receive-loop.js):**
- `collectGroupTriggers` (`:23-24`) already reads `dm.quote.author / .authorNumber`. Pattern to mirror for full-quote persistence.
- Capture write site: needs `signal_msg_ts = env.envelope.dataMessage.timestamp` and `quote_msg_ts = dm.quote?.id || dm.quote?.timestamp`. Confirm by reading 1 fixture envelope from `test/fixtures/`.
- New helper: `confirmDb.findDraftByQuotedMsgTs(pool, quote_msg_ts)` — single SELECT joining signal_outbound → signal_draft.

**Schema migrations:**
- All three migrations are additive `ALTER TABLE … ADD COLUMN IF NOT EXISTS …`. No data migration. Boot-time at `initDb()` in `signal.js / confirm-db.js / capture-db.js` (wherever the existing schema-init pattern lives — confirm in plan-phase).

**Test infrastructure:**
- `test/confirm/fake-pool.js` is the pattern for new IN-list/UPDATE matchers (extended in Plans 45-01 and 45-04 — mirror that pattern).
- Existing capture envelope fixtures live under `test/fixtures/` (per Phase 37 work) — extend with quote-bearing fixtures.

**Real test data we already have:**
- Drafts `1fb28e70…` (Santi May 15 relocate, committed) and the 3 ack-debt drafts (`0c5533f9`, `6934760c`, `946a7b08`) are good real-shape candidates for integration test fixtures. They have populated `source_capture_ids` → backfill their inbound `signal_msg_ts` by running `signal-cli receive --dump` or pulling from `signal_capture.captured_at` if no native ts is recoverable.
</code_context>

<specifics>
## Specific Ideas

- Plan size: M (~1-1.5 days), 5 plans matching the spike sketch:
  - P-01 schema migration (3 columns, 1 index) — XS
  - P-02 signal.js send() quote param + signal_outbound persistence — S
  - P-03 outbound-confirm.js dispatch sites use quote (commit_outcome_ack + confirm_ack first) — S
  - P-04 receive-loop persistence + quote-resolution helper + EDIT/NO router patch + numbered-ask-back fallback — M
  - P-05 live-fire UAT — M, autonomous: false
- Wave 1: P-01 alone. Wave 2: P-02 (depends on P-01 column). Wave 3: P-03 + P-04 (parallel — disjoint files). Wave 4: P-05.
- Live-fire ship-gate (P-05): operator triggers a fresh commit_failed by sending Santi's bot a message with no asset_ref, waits for ack, observes that ack appears as a Signal quote-reply on the farmer's phone (screenshot), quote-replies "EDIT block 260415_LIMA_1", verifies the system writes to the exact draft (not most-recent).
- Use the actual ack-debt drafts as integration test fixtures rather than synthetic envelopes — they're real-shape and we already touched them this session.
- Plan-06 disambiguator template stays in place; the success of this phase doesn't depend on removing it.
</specifics>

<deferred>
## Deferred Ideas

- Quote-routing for group threads (different semantics; needs Phase 37 attribution awareness; defer until a real group failure mode surfaces).
- Backfill `signal_msg_ts` for historical `signal_outbound` rows (would require re-fetching from signal-cli, which has limited history; not worth it — quote resolution gracefully falls back).
- Extend quote to all 8 outbound side-effect kinds in one shot. Ship first with the 2 highest-traffic (`send_commit_outcome_ack`, `send_confirm_ack`); roll the rest in as a follow-on once the pattern is proven.
- Editing/deleting the quoted ack after farmer-acknowledged (Signal supports message edit; not needed for this loop).
- Multi-language quote tooling (English only this phase; same posture as Phase 45 Plan 06).
- Phase 50 fallback ask-back COULD itself be a Signal-quote-bearing message ("which one are you replying about?"), making the numbered options click-to-quote. Nice but not the first ship.
</deferred>
