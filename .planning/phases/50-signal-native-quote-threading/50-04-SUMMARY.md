---
phase: 50-signal-native-quote-threading
plan: 04
subsystem: alerter/inbound
tags: [signal, inbound, quote, receive-loop, edit-handler, ask-back, schema-consumer]
requires: [50-01, 50-02]
provides:
  - "signal_capture.signal_msg_ts populated on every captured inbound (QUOT-02)"
  - "signal_capture.quote_msg_ts + quote_author_e164 populated when farmer used Signal's quote/reply UI"
  - "confirm-db.findDraftByQuotedMsgTs(pool, quote_msg_ts) JOIN resolver"
  - "confirm-db.findActiveDraftsForSender(pool, sender_e164) list-shape sibling"
  - "receive-loop quote-first routing: quote -> actionable draft = route to THAT draft (skip MRU)"
  - "receive-loop terminal-quote path: quote -> terminal draft = polite 'already closed' ack (no mutation)"
  - "receive-loop numbered ask-back: >1 active AND no quote = one-shot ask-back; no state tracking"
  - "outbound-confirm.dispatch('send_ask_back', null, { activeDrafts, senderE164 })"
  - "outbound-confirm.dispatch('send_quote_closed', terminalDraftRow)"
  - "T-50-04-01 sender-equality guard on quote-resolved drafts (spoof protection)"
affects:
  - capture.js row builder (every successful capture writes 3 new fields)
  - fake-pool harness (new seedOutbound + JOIN matcher + list-vs-LIMIT-1 branch)
tech-stack:
  added: []
  patterns:
    - "List-shape sibling alongside single-row finder (back-compat for tests that mock only findAwaitingForSender)"
    - "buildDisambiguator helper now exported from commit-outcome-preview.js for reuse across confirm-side renderers"
    - "Cross-version drift acceptance: dm.quote.{id ?? timestamp}, dm.quote.{author ?? authorNumber}"
key-files:
  created:
    - src/agents/alerter/test/fixtures/envelopes/text-quote-reply.json
    - src/agents/alerter/test/fixtures/envelopes/text-quote-reply-authornumber-only.json
  modified:
    - src/agents/alerter/src/capture-db.js
    - src/agents/alerter/src/capture.js
    - src/agents/alerter/src/receive-loop.js
    - src/agents/alerter/src/confirm/confirm-db.js
    - src/agents/alerter/src/confirm/outbound-confirm.js
    - src/agents/alerter/src/farmos/commit-outcome-preview.js
    - src/agents/alerter/test/capture-db.test.js
    - src/agents/alerter/test/capture.test.js
    - src/agents/alerter/test/confirm/confirm-db.test.js
    - src/agents/alerter/test/confirm/fake-pool.js
    - src/agents/alerter/test/confirm/outbound-confirm.test.js
    - src/agents/alerter/test/confirm/receive-loop-confirm.test.js
decisions:
  - "Routing lives in receive-loop.js (where EDIT/NO/YES dispatch already lives), NOT edit-handler.js — plan explicitly accepts this seam"
  - "findActiveDraftsForSender added alongside findAwaitingForSender (no breaking change to existing callers / tests)"
  - "Numbered ask-back capped at 5 entries; first-ship is intentionally quote-less (deferred-ideas: make ask-back itself a quote-bearing message)"
  - "Quote-closed ack uses Plan 45-06 disambiguator shape via newly-exported buildDisambiguator helper"
  - "T-50-04-01 sender-equality guard explicitly added: spoofed cross-farmer quote treated as orphan, falls through to that sender's own active-drafts path"
metrics:
  duration_minutes: ~45
  completed_date: 2026-05-23
requirements: [QUOT-02, QUOT-03, QUOT-06]
---

# Phase 50 Plan 04: inbound quote-threading + numbered ask-back fallback — Summary

Wire the inbound side of Signal-native quote threading end-to-end. Three coupled
changes ship as one logical unit, then the verification matrix (QUOT-06 four
cases + terminal + orphan + spoof) is proven hermetically. Plan 05 is the
live-fire ship-gate; this plan locks the mechanism.

## What shipped

### 1. Capture-side persistence (insertCapture row keys + receive-loop wiring)

`capture-db.insertCapture` now accepts three new optional fields:

| Field               | Source                              | Persisted in            |
|---------------------|-------------------------------------|-------------------------|
| `signal_msg_ts`     | `dm.timestamp`                      | every inbound (QUOT-02) |
| `quote_msg_ts`      | `dm.quote.id ?? dm.quote.timestamp` | only when farmer quoted |
| `quote_author_e164` | `dm.quote.author ?? dm.quote.authorNumber` | only when farmer quoted |

INSERT shape grew from `$1..$13` to `$1..$16` (one new column triple appended).
All three default NULL when caller omits them (back-compat). The row builder
in `capture.js` derives them inline:

```js
const sigMsgTs = (typeof dm.timestamp === 'number')
  ? dm.timestamp
  : (Number.isFinite(Number(dm.timestamp)) ? Number(dm.timestamp) : null);
const q = dm.quote || null;
const quoteMsgTsRaw = q ? (q.id != null ? q.id : q.timestamp) : null;
const quoteMsgTs = quoteMsgTsRaw != null && Number.isFinite(Number(quoteMsgTsRaw))
  ? Number(quoteMsgTsRaw) : null;
const quoteAuthor = q ? (q.author || q.authorNumber || null) : null;
```

Cross-version drift acceptance follows the `receive-loop.js:23-24` precedent
(Phase 37 Risk #9 / Phase 50 CONTEXT D-07).

### 2. Quote-resolution helper (`findDraftByQuotedMsgTs`)

```sql
SELECT d.*
  FROM signal_outbound o
  JOIN signal_draft d ON d.id = o.related_draft_id
 WHERE o.signal_msg_ts = $1
 ORDER BY o.sent_at DESC
 LIMIT 1
```

Returns the joined draft row or `null` (null arg, no match, NULL related_draft_id,
DB error). Never throws — matches Plan 50-03 `getCaptureQuoteTarget` posture.
Leverages the `idx_signal_outbound_msg_ts` partial index from Plan 50-01.
`ORDER BY sent_at DESC LIMIT 1` guards the (rare) two-outbounds-same-ts edge.

### 3. List-shape sibling (`findActiveDraftsForSender`)

```sql
SELECT * FROM signal_draft
 WHERE sender_e164=$1
   AND status IN ('awaiting_farmer','commit_failed')
 ORDER BY CASE status WHEN 'awaiting_farmer' THEN 0 ELSE 1 END ASC,
          updated_at DESC
```

Returns `rows[]` (no LIMIT 1). Same ordering as the single-row variant
(`findAwaitingForSender`). Receive-loop uses this to detect the `>1-active`
ambiguity case. Single-row variant is preserved unchanged for back-compat.

### 4. Receive-loop routing (the CONTEXT D-04 algorithm)

The patch lives in `receive-loop.js` (where YES/NO/EDIT dispatch already lives;
plan accepted this seam — `edit-handler.js` is the re-extraction handler, not
the router). The new flow:

1. Parse `dm.quote.{id ?? timestamp}` -> `quoteMsgTs` (or null).
2. If `quoteMsgTs != null`: call `findDraftByQuotedMsgTs`.
   - **Sender mismatch (T-50-04-01)**: warn and drop (treat as orphan).
   - **Actionable** (`awaiting_farmer` | `commit_failed`): pin `draftRow`, set
     `quoteResolved=true`. Skip the active-drafts list lookup.
   - **Terminal** (`committed` | `discarded` | `expired` | `needs_review` |
     `confirmed`): dispatch `send_quote_closed`, `continue`.
   - **Other transitional**: fall through.
3. If no `draftRow` was pinned: `findActiveDraftsForSender` -> list.
   - **0 actives**: fall through to capture pipeline (unchanged).
   - **1 active**: route to it (unchanged behavior).
   - **>1 actives AND `!quoteResolved`**: dispatch `send_ask_back`, `continue`.
   - Else: pick `activeDrafts[0]` (deterministic tie-break by the SQL ordering).
4. Hand `draftRow` to existing YES/NO/EDIT branches (unchanged).

### 5. Numbered ask-back renderer + side-effect

`renderNumberedAskBack(activeDrafts)` produces:

```
Which one are you replying about?
1. May 22 observation (block A note)
2. May 21 seeding (inoc)
Reply with the number, or quote the original message.
```

Uses `buildDisambiguator` from Plan 45-06 (newly exported). Cap at 5 entries.
**One-shot semantics** — we do NOT track an "awaiting numbered reply" state.
Next inbound from the farmer goes through the same routing (quote wins if
attached; current parser handles "1" / "EDIT block …" text).

New side-effects on `outbound-confirm.dispatch`:

| Side effect           | Target            | Intent          | Quote? |
|-----------------------|-------------------|-----------------|--------|
| `send_ask_back`       | sender (DM)       | `ask_back`      | no     |
| `send_quote_closed`   | sender (DM)       | `quote_closed`  | no     |

`send_quote_closed` body shape:

```
That May 13 seeding (inoc) is already saved. n/a
```

Plan-06 disambiguator shape via `buildDisambiguator`. Status word mapped to
human-readable (`committed`->`saved`, `discarded`->`discarded`, etc.).
ASCII-only, no em-dashes (asserted by a test).

### T-50-04-01 sender-equality guard

Explicitly added at the quote-resolution branch in `receive-loop.js`:

```js
if (qr.sender_e164 && qr.sender_e164 !== source) {
  logger.warn(`[receive] quote spoof guard: draft sender mismatch (drop)`);
  // treat as orphan; fall through to THIS sender's own active-drafts path
}
```

A farmer who quotes another farmer's bot ack does NOT get routed to that
other farmer's draft. The guard treats the quote as orphan and falls through
to the inbound sender's own active-drafts lookup (which is correct).

## Numbered ask-back render shape + one-shot semantics

Render shape (5-entry max, with `buildDisambiguator`):

```
Which one are you replying about?
1. {date} {log_type} ({summary})
2. {date} {log_type} ({summary})
…
Reply with the number, or quote the original message.
```

**One-shot**. No state tracking. The farmer's next inbound is treated as a
fresh routing decision:

- If they quote one of the listed acks -> quote wins (CONTEXT D-04 step 2a/2b).
- If they type "1" or "EDIT block 260415_LIMA_1" -> falls through to the same
  router; the current parser handles the text shape.

Deferred (CONTEXT deferred-ideas): make the ask-back itself a quote-bearing
message so the numbered options become click-to-quote on the farmer's side.

## QUOT-06 hermetic proof (the four cases + spoof + orphans + terminal)

All cases covered by `test/confirm/receive-loop-confirm.test.js` Phase 50
Plan-04 describe block:

| Case | Active | Quote? | Expected behavior | Test |
|------|--------|--------|-------------------|------|
| 1    | 1      | no     | route to that draft | `(QUOT-06 case 1)` |
| 2    | 1      | yes    | route to QUOTED draft (ignore MRU) | `(QUOT-06 case 2)` |
| 3    | >1     | yes    | route to QUOTED draft; NO ask-back | `(QUOT-06 case 3)` |
| 4    | >1     | no     | emit `send_ask_back`; no mutation | `(QUOT-06 case 4)` |
| --   | 0      | yes->terminal | `send_quote_closed`; no mutation | `quote resolves to a terminal …` |
| --   | 1      | yes->null (orphan) | fall through to that 1 active | `orphan quote (resolves null) + 1 active …` |
| --   | >1     | yes->null (orphan) | numbered ask-back | `orphan quote + >1 active …` |
| --   | 0      | yes->other-sender (spoof) | drop quote; fall through to capture | `T-50-04-01: …` |

Plus a cross-version-drift test (`quote.timestamp` when `quote.id` absent).

## Test count

| Suite | New cases |
|-------|-----------|
| `capture-db.test.js` | 2 (16-placeholder + Plan-04 round-trip) + 1 updated |
| `capture.test.js` | 4 (signal_msg_ts persistence + quote both author shapes + missing-ts) |
| `confirm/confirm-db.test.js` | 9 (3 findActiveDraftsForSender + 6 findDraftByQuotedMsgTs) |
| `confirm/outbound-confirm.test.js` | 8 (send_ask_back × 4 + send_quote_closed × 3 + ASCII guard) |
| `confirm/receive-loop-confirm.test.js` | 9 (QUOT-06 four-case matrix + terminal + 2 orphan variants + T-50-04-01 spoof + drift) |
| **Total new** | **32** |

Full alerter suite: 1036/1045 pass, 9 skipped, 0 fail.

## Verification

- `npx jest test/capture-db.test.js test/capture.test.js` — green (capture persistence)
- `npx jest test/confirm/confirm-db.test.js` — green (helpers)
- `npx jest test/confirm/receive-loop-confirm.test.js` — green (QUOT-06 + variants)
- `npx jest test/confirm/outbound-confirm.test.js` — green (dispatch + ASCII guard)
- `grep -n "quote_msg_ts" src/agents/alerter/src/capture.js` -> line 164 (row builder)
- `grep -n "findDraftByQuotedMsgTs" src/agents/alerter/src/receive-loop.js` -> line 235 (routing branch)
- `grep -n "ask_back\|send_ask_back" src/agents/alerter/src/confirm/outbound-confirm.js src/agents/alerter/src/receive-loop.js` -> multiple hits in both files
- ASCII check on all NEWLY-ADDED lines: zero em-dashes / en-dashes (`git diff main..HEAD | grep "^+" | grep -E "[—–]"` -> empty)

## Deviations from plan

**None for behavior**. Two seam choices worth recording explicitly (both
sanctioned by the plan text):

1. **Routing lives in receive-loop.js, not edit-handler.js**. The plan's
   Task 3 says "edit-handler.js (or wherever EDIT/NO routing currently lives)"
   — and the actual YES/NO/EDIT dispatch is in receive-loop. `edit-handler.js`
   only handles the re-extraction step inside an EDIT. Patch landed where the
   real router sits.

2. **`findActiveDraftsForSender` is a new sibling helper, not a modification
   of `findAwaitingForSender`**. The latter returns a single row; the former
   returns the list. This preserves every existing call-site / test in the
   wider codebase. Receive-loop calls the list-shape helper when available,
   falls back to the single-row helper otherwise (back-compat path covered
   by the existing `null pool/confirmDb/editHandler -> back-compat` test).

## Known stubs

None. The mechanism is hermetically complete. Plan 05 is the live-fire
ship-gate that exercises the full loop on production Signal.

## Threat flags

No new surface beyond the plan's threat register. T-50-04-01 (cross-farmer
spoofing) is mitigated with the explicit sender-equality guard (Task 3
action item 1, line `qr.sender_e164 && qr.sender_e164 !== source`).
T-50-04-05 (DB error blocks ack) is mitigated by `findDraftByQuotedMsgTs`
returning null on throw — the receive-loop treats null as orphan and proceeds.

## Commits

- `e102e7b` — feat(50-04): capture-side persistence of signal_msg_ts + quote_{msg_ts,author_e164}
- `f94d79d` — feat(50-04): confirm-db.findDraftByQuotedMsgTs resolver
- `210340f` — feat(50-04): quote-first routing + numbered ask-back fallback

## Self-Check

Files exist:

- `src/agents/alerter/src/capture-db.js` — `signal_msg_ts` at line 50 (initDb) + INSERT extended to 16 placeholders
- `src/agents/alerter/src/capture.js` — quote row-builder at lines ~128-145, `signal_msg_ts:` at line ~163
- `src/agents/alerter/src/confirm/confirm-db.js` — `findActiveDraftsForSender` + `findDraftByQuotedMsgTs` both exported
- `src/agents/alerter/src/confirm/outbound-confirm.js` — `send_ask_back` + `send_quote_closed` cases
- `src/agents/alerter/src/farmos/commit-outcome-preview.js` — `buildDisambiguator` + `labelFor` exported
- `src/agents/alerter/src/receive-loop.js` — quote-resolution branch at line 235

Commits in git log: `e102e7b`, `f94d79d`, `210340f` — all FOUND.

## Self-Check: PASSED
