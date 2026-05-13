# Phase 39: Farmer Confirmation Loop - Research

**Researched:** 2026-05-13
**Researcher:** orchestrator (in-context — CONTEXT.md is fully locked, no subagent dispatch available)
**Status:** Ready for planning

---

## 1. Phase Goal Restated

Every `signal_draft` row that Phase 38 hands off in status `awaiting_farmer` (with a populated `farmer_facing_preview`) must reach one of five terminal states through farmer action:

| Terminal status | Trigger | Phase-39-owned? |
| --- | --- | --- |
| `confirmed` | YES/Y/OK/SI/SÍ first-token reply | yes |
| `discarded` | NO/N/CANCEL/STOP first-token reply | yes |
| `expired` | watchdog: idle ≥ `DRAFT_PENDING_TIMEOUT_MIN` after one nudge | yes |
| `needs_review` (edit_cap_exceeded) | 4th EDIT against the same draft | yes |
| `confirmed`/`discarded`/`needs_review` (`superseded_by_newer_draft`) | new draft for same sender while one is pending | yes (auto-`expired` on the older one) |

Phase 39 does **not** own `committed` (Phase 40 farmOS write) nor re-extraction for fresh paper-log batches (Phase 38 D-12, `drafts.length > 1`).

---

## 2. Upstream Contract (Phase 38)

Already locked. The Phase 38 seam is fully described in `38-CONTEXT.md` D-02b (status enum) and `extraction-db.js` (this file). Concretely:

- `signal_draft` row in `awaiting_farmer` carries:
  - `id` (sha256 of sorted source_capture_ids)
  - `sender_e164`, `farmos_person` (Phase 37 lookup)
  - `farmer_facing_preview` (preview-builder.js output, sanitized — no em-dashes, `fmtNum()` numbers)
  - `reply_target_kind`, `group_id` (from Phase 37 routing)
  - `askback_turns` (Phase 38 counter, capped at 3 — independent from Phase 39's `edit_turn_count` per D-03b)
  - `source_capture_ids` (text[])
  - `draft_json`, `per_field_confidence`
- Partial unique index `idx_signal_draft_in_flight_per_sender` enforces "at most one in-flight (pending|awaiting_farmer) per sender" at the DB layer. Phase 39 status transitions must respect this — leaving a row in `awaiting_farmer` while inserting a new one will 23505.
- Phase 38 also runs `expireIdle(pool, gapMinutes)` via the idle-gap closer (`draftIdleGapMin`, default 30, `DRAFT_IDLE_GAP_MIN`). **This is conversational-idle on the capture side, not Phase 39's `DRAFT_PENDING_TIMEOUT_MIN`.** The two timers must not collide. Recommendation: keep them at the same default (30min) for v1.7 to avoid surprise, but they remain independent env knobs.

**Implication for Phase 39:** the watchdog's idempotent `expired` transition (D-04b) and Phase 38's `expireIdle` will racily target the same row in some windows. Both use `updated_at < now() - interval`; both write `status='expired'`. The second writer is a no-op. Safe but worth a test.

---

## 3. Reply Parser (D-01) — How It Hooks Into receive-loop.js

The reply parser must intercept BEFORE the capture pipeline. Today's `receive-loop.js` flow (lines 113–214):

```
tick → for envelope:
  whitelist gate
  group-context decoration (replyTargetKind, suppressReply)
  experiment-command branch (continues on hit)
  snooze-command branch (continues on hit)
  capture pipeline (fire-and-forget)
```

The confirm-loop reply parser is a **new branch** inserted between snooze and capture:

1. Resolve sender (already done — `source`).
2. `getInFlightForSender(pool, source)` (already in `extraction-db.js`).
3. If status is `awaiting_farmer`: classify the body.
   - YES family → `confirm` side-effect.
   - NO family → `discard` side-effect.
   - EDIT (any other non-empty text) → enqueue an EDIT re-extraction.
   - Empty / sticker / emoji-only → noop (no state transition; let the natural capture path persist the reaction for audit but don't drive the state machine).
4. `continue` to next envelope after any state transition (don't double-dispatch to the capture pipeline).

If status is not `awaiting_farmer` (e.g. `pending`, `needs_review`, terminal), the reply is **not** a confirm reply — fall through to capture pipeline as a fresh message. The pipeline's normal idle-gap / continuity logic handles it.

**Empty-body classification.** The pure-function classifier must return `{ kind: 'YES'|'NO'|'EDIT'|'noop', editText?: string }`. Living in `src/agents/alerter/src/confirm/parser.js`. Lowercase the trimmed body, take first token. The `EDIT <text>` prefix is one form; any other non-trivial first token also routes to EDIT (D-01). Pure, unit-testable.

**Selection rule.** D-01a: latest `awaiting_farmer` by `updated_at`. Already covered by the partial unique index — multiple rows shouldn't exist, but the parser still uses `ORDER BY updated_at DESC LIMIT 1` defensively. Older `awaiting_farmer` rows for the same sender (if any survive) get auto-`expired` with `terminal_reason='superseded_by_newer_draft'`.

---

## 4. Idempotency (D-02) — Conditional UPDATE Pattern

The atomic YES handoff is:

```sql
BEGIN;
  UPDATE signal_draft
     SET status = 'confirmed',
         confirmed_at = NOW(),
         terminal_reason = 'farmer_yes',
         updated_at = NOW()
   WHERE id = $1
     AND status = 'awaiting_farmer'
  RETURNING id;
  -- If rowCount == 1: insert event row, send "Locked in" reply.
  -- If rowCount == 0: idempotent no-op (already confirmed / discarded / expired) — send soft re-affirm.
  INSERT INTO signal_draft_event (draft_id, seq, event, payload, created_at)
       VALUES ($1, (SELECT COALESCE(MAX(seq), 0)+1 FROM signal_draft_event WHERE draft_id=$1), 'yes', $2::jsonb, NOW());
COMMIT;
```

`seq` is per-draft monotonic (composite primary key `(draft_id, seq)`). The `COALESCE(MAX(seq),0)+1` pattern is racy under concurrent writers, but **Phase 39 inserts events synchronously inside one transaction per state-machine tick** — the receive-loop is single-tick, the watchdog is single-tick. No concurrent same-draft writers in practice. If we ever need it, an advisory lock keyed on `draft_id` is the upgrade path.

NO follows the same pattern: `WHERE status = 'awaiting_farmer'`, sets `discarded_at`, terminal_reason='farmer_no'.

---

## 5. EDIT Loop (D-03) — Re-Extraction Integration

EDIT re-uses the Phase 38 extractor. The signature change is small:

`extractor.extract({ captures, inFlightDraft, corpusContext })` already accepts `inFlightDraft`. We add a new field on the captures item — `farmerCorrection: string` — that gets formatted into the user content block. The extractor's `buildInitialUserContent` already emits a free-text "In-flight draft: ..." block; we add a second text block "Farmer correction: <text>" right after it. No schema change in the LLM tool spec; the new context just biases the model toward the correction.

**Concretely:** Phase 39 doesn't fork the extractor. It calls the existing one with:

```js
extractor.extract({
  captures: [{
    captureId: editReplyCaptureId,         // the EDIT reply's own capture row
    text: null,                            // intentionally null; the correction is bound to the in-flight draft, not a fresh capture
    transcript: null,
    images: [],
    farmerCorrection: editText,
  }],
  inFlightDraft: draftRow.draft_json,
});
```

`extractor.js buildInitialUserContent` gains a `farmerCorrection` plumbing in one place. The Phase 38 author already considered this in D-03 ("Reuses `llm-client.js extract()`") — so this is a tracked, scoped Phase 38 surface change.

**Update in place.** The draft row stays at the same `id` (same `source_capture_ids`); we `UPDATE signal_draft SET draft_json=$, per_field_confidence=$, farmer_facing_preview=$, edit_turn_count = edit_turn_count + 1, updated_at = NOW() WHERE id=$ AND status='awaiting_farmer'`. The preview is re-rendered via `preview-builder.buildPreview` (already shared, per D-05) and re-sent through `signal.js`.

**Cap = 3 (D-03a).** `edit_turn_count >= 3` before the increment means the next EDIT is the 4th — escalate. Status → `needs_review`, terminal_reason='edit_cap_exceeded', send the cap message. Done.

**Counter independence (D-03b).** Phase 38's `askback_turns` does not gate Phase 39's `edit_turn_count`. Two columns, two counters. Tests must cover the combined budget — a draft that consumed 3 ask-back turns in Phase 38 can still take 3 EDITs in Phase 39.

---

## 6. Watchdog / Timeout (D-04) — Polling Pattern

`setInterval(watchdogTick, DRAFT_WATCHDOG_INTERVAL_MS)`, default 60s. The tick:

```sql
-- Find nudge candidates: never-nudged, past 0.8 * timeout.
SELECT id, sender_e164, reply_target_kind, group_id, farmer_facing_preview, updated_at
  FROM signal_draft
 WHERE status = 'awaiting_farmer'
   AND nudge_sent_at IS NULL
   AND updated_at < NOW() - ($1 || ' minutes')::interval;

-- Find expire candidates: past full timeout.
SELECT id, sender_e164, reply_target_kind, group_id
  FROM signal_draft
 WHERE status = 'awaiting_farmer'
   AND updated_at < NOW() - ($2 || ' minutes')::interval;
```

For each nudge: send the soft reminder via `signal.js`, then `UPDATE signal_draft SET nudge_sent_at = NOW() WHERE id = $ AND nudge_sent_at IS NULL` (conditional to prevent re-nudge in restart-race scenarios) + insert event row.

For each expire: `UPDATE signal_draft SET status='expired', expired_at=NOW(), terminal_reason='timeout_expired', updated_at=NOW() WHERE id=$ AND status='awaiting_farmer'` (conditional, idempotent) + final "Draft expired" send + event row.

**Restart safety (D-04d).** The watchdog runs **immediately on alerter start-up**, not after the first interval. A draft that crossed timeout while the alerter was down still fires nudge/expire on first tick. The conditional `WHERE nudge_sent_at IS NULL` (for nudges) and `WHERE status='awaiting_farmer'` (for expires) guarantee idempotency across restarts and watchdog-tick races.

**Bypass for batch-mode drafts.** Phase 38 batch-mode (D-12 / pipeline.js `runBatchMode`) routes drafts to `needs_review` directly — they never enter `awaiting_farmer`, so the watchdog's `WHERE status='awaiting_farmer'` filter naturally excludes them. No special-case needed.

**Process placement.** D-08 puts the watchdog in-process inside the alerter (not a separate compose service). One Node.js timer alongside the receive-loop and capture pipeline. Restart of `mushy-alerter` reinitializes the timer.

**Nudge text rounding (D-04a).** "auto-expires in 6 min" not "in 6.0 min" — use `Math.round` on remaining-minutes for the body. No em-dashes; `fmtNum()` for any numbers.

---

## 7. State Persistence (D-07, D-07a) — Schema Migration

Idempotent migration to `signal_draft`:

```sql
ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS edit_turn_count   integer NOT NULL DEFAULT 0;
ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS nudge_sent_at     timestamptz NULL;
ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS confirmed_at      timestamptz NULL;
ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS discarded_at      timestamptz NULL;
ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS expired_at        timestamptz NULL;
ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS terminal_reason   text NULL;
```

New audit table:

```sql
CREATE TABLE IF NOT EXISTS signal_draft_event (
  draft_id   text NOT NULL,
  seq        integer NOT NULL,
  event      text NOT NULL,           -- 'preview_sent','yes','no','edit','nudge_sent','expired','edit_cap_exceeded','superseded'
  payload    jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (draft_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_signal_draft_event_created_at ON signal_draft_event (created_at);
```

Convention: match `extraction-db.js` style (pool-injected, never-throw on writes, idempotent CREATE).

**New CRUD module:** `src/agents/alerter/src/confirm/confirm-db.js` exporting:

- `initDb(pool)` — ALTERs + CREATE TABLE (idempotent).
- `confirmDraft(pool, draftId)` — atomic UPDATE+event, returns rowCount (0 = idempotent no-op).
- `discardDraft(pool, draftId)` — same shape.
- `expireDraft(pool, draftId, reason)` — same shape, `reason` ∈ `{'timeout_expired','superseded_by_newer_draft','edit_cap_exceeded'}`.
- `markNudgeSent(pool, draftId)` — conditional UPDATE.
- `appendEvent(pool, draftId, event, payload)` — used by the EDIT path and any sender that doesn't go through the dedicated transition helpers above.
- `bumpEditTurn(pool, draftId)` — RETURNING edit_turn_count for cap check.
- `findNudgeCandidates(pool, nudgeMin)` / `findExpireCandidates(pool, timeoutMin)` — watchdog queries.
- `findAwaitingForSender(pool, senderE164)` — defensive `ORDER BY updated_at DESC LIMIT 1`. Distinct from Phase 38's `getInFlightForSender` (which matches pending|awaiting_farmer).

---

## 8. Outbound Path (D-08) — Extending outboundDispatcher

`outbound.js createOutboundDispatcher` already handles `send_ask_back`, `send_needs_review_ping`, `send_batch_review_summary`. Phase 39 adds **side-effect tags**:

| tag | resolves to | target |
| --- | --- | --- |
| `send_confirm_ack` | "Locked in — writing now. (draft <truncId>)" | DM to sender |
| `send_confirm_idempotent_ack` | "Already locked in. Check the previous message." (D-02a) | DM to sender |
| `send_discard_ack` | "Discarded. Nothing written." | DM to sender |
| `send_edit_cap_msg` | escalation message (D-03a) | DM to sender |
| `send_nudge` | nudge text (D-04a) with remaining-min int | DM to sender (per D-06a — even if group-origin) |
| `send_expired_note` | "Draft expired. Nothing was written. Send a fresh message..." | DM to sender |
| `send_preview_resend` | re-rendered preview after EDIT | per `reply_target_kind` (group or DM, D-06) |

Per D-06a, **confirms always DM**, regardless of `reply_target_kind`. Only the preview hand-off (initial + EDIT re-render) honors the group target. This is a deliberate per-side-effect routing override; encode it in the dispatcher (not the caller).

All text passes `sanitizeFarmerText()` (already in `preview-builder.js`). All numbers use `fmtNum()` (already in `message.js`).

---

## 9. New Env Vars — Compose Passthrough

Per memory `feedback_compose_env_passthrough_not_envfile`:

| env var | default | purpose |
| --- | --- | --- |
| `DRAFT_PENDING_TIMEOUT_MIN` | `30` | D-04 full timeout |
| `DRAFT_NUDGE_FRACTION` | `0.8` | D-04a nudge timing (24min at default timeout) |
| `DRAFT_WATCHDOG_INTERVAL_MS` | `60000` | D-04c poll interval |
| `MAX_EDIT_TURNS` | `3` | D-03a EDIT cap |

Each MUST be added to `docker-compose.override.yml` `mushy-alerter` `environment:` block with the `- X=${X:-default}` shape in the same PR that wires the reader. Same trap as the 2026-05-12 SHT30 false-alarm incident.

---

## 10. Test Harness Layout

Match Phase 38 conventions:

- Unit tests next to the source: `src/agents/alerter/test/confirm/parser.test.js`, `state-machine-39.test.js`, `confirm-db.test.js`, `watchdog.test.js`, `outbound-39.test.js`.
- Integration test: `src/agents/alerter/test/confirm/integration.test.js` — wires the parser + DB + outbound + a mock LLM extractor end-to-end against an in-memory pg pool (use the same harness Phase 38 used for `pipeline.test.js`).
- **Real-data fixture (D-09a, ship-gate).** At least one integration scenario must replay a real prod inoc draft sourced from `/mnt/mossrock/shared/mushdatadump-prod/`. The fixture takes a known `awaiting_farmer` snapshot (saved as JSON; no live LLM needed for YES/NO scenarios) and drives the loop through YES, NO, EDIT (mocked re-extract), and timeout paths. For EDIT only, a live LLM smoke is acceptable IF results go to a per-call unique JSONL path (memory `feedback_persist_paid_results_default`).
- Synthetic 39 scenarios (8): YES happy path, NO discard, duplicate YES no-op, EDIT once, EDIT 3 times then cap, nudge fires at 0.8×timeout, expire fires at timeout, superseded-by-newer-draft.

---

## 11. Validation Architecture (Nyquist)

| Dimension | How Phase 39 satisfies it |
| --- | --- |
| Functional correctness (D1) | 8 synthetic + 1 real-prod-fixture integration scenarios |
| State transition coverage (D2) | Every `awaiting_farmer` → terminal arc exercised |
| Idempotency (D3) | Duplicate-YES, duplicate-watchdog-tick, restart-watchdog all rowCount=0 expected |
| Concurrency (D4) | Single-receive-loop + single-watchdog; tested with a serialized fake clock |
| Persistence (D5) | After each transition, expect a `signal_draft_event` row + non-null terminal `*_at` column |
| Restart safety (D6) | Watchdog tick on first start-up after gap > timeout fires nudge/expire correctly |
| Style locks (D7) | sanitizeFarmerText sweep across outbound messages; assert no `—` / `–` |
| Real-data ship-gate (D8) | At least one prod-fixture in eval (D-09a); curated-only does NOT pass |

---

## 12. Files Touched (Anticipated)

**New:**
- `src/agents/alerter/src/confirm/parser.js`
- `src/agents/alerter/src/confirm/confirm-db.js`
- `src/agents/alerter/src/confirm/state-machine.js` (or extend Phase 38's; see D-09 below)
- `src/agents/alerter/src/confirm/watchdog.js`
- `src/agents/alerter/src/confirm/preview.js` (suffix builder + nudge/ack text)
- `src/agents/alerter/src/confirm/index.js` (barrel)
- `src/agents/alerter/test/confirm/*.test.js` (6+ files)
- `.planning/phases/39-farmer-confirmation-loop/39-RUNBOOK.md` (real-farmer UAT script)

**Modified:**
- `src/agents/alerter/src/config.js` (add 4 env knobs)
- `src/agents/alerter/src/receive-loop.js` (insert confirm-reply branch between snooze and capture)
- `src/agents/alerter/src/extraction/extractor.js` (plumb `farmerCorrection` into `buildInitialUserContent`)
- `src/agents/alerter/src/extraction/outbound.js` (add new side-effect tags + DM-override for confirms)
- `src/agents/alerter/src/index.js` (wire the new modules + start the watchdog)
- `docker-compose.override.yml` (4 new env vars)

---

## 13. Open Decisions for Planner (Subordinate to CONTEXT.md)

CONTEXT.md `<decisions>` is fully locked; the planner inherits all of D-01..D-09a. Planner discretion (per the "Claude's Discretion" block in CONTEXT.md):

- Exact wording of confirm/discard/nudge/expire/escalation text (must obey style locks D-05b).
- Whether confirm/discard/expire side-effects emit a single `signal_draft_event` row or split into `state_changed` + `outbound_sent` rows (the audit table is loose enough to accommodate either; recommend the simpler one-row-per-transition shape).
- Whether to keep one consolidated confirm/state-machine module or split (parser + state-machine + watchdog as three modules; recommend three for testability).
- Migration commit shape — one migration touching both tables, or two separate migrations. Recommend one (the diff is tightly coupled to Phase 39 columns + audit table).

---

## RESEARCH COMPLETE

8 synthetic + 1 real-prod-fixture integration scenarios planned; 6 new source modules + 6 test files; 4 new env knobs + override.yml plumbing; pure-function parser + state-machine isolated from IO for unit-testability; watchdog as in-process setInterval with restart-safe immediate first tick + conditional UPDATEs for idempotency. CONTEXT.md decisions cover every implementation question.
