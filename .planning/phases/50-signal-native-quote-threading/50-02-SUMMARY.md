---
phase: 50-signal-native-quote-threading
plan: 02
subsystem: alerter/outbound
tags: [signal, outbound, quote, signal_outbound, schema-consumer]
requires: [50-01]
provides:
  - "signal.js send() accepts opts.quote = {timestamp, author, message}"
  - "Every successful send persists json.timestamp into signal_outbound.signal_msg_ts"
  - "outbound-db.insertOutbound accepts row.signal_msg_ts (bigint, NULL when omitted)"
affects:
  - signal.js callers (~14 sites; all unaffected — silent unquoted path)
tech-stack:
  added: []
  patterns:
    - "isValidQuote() guard with fail-open fallback (warn + unquoted send) per CONTEXT D-05"
    - "Number()-coercion of stringified ms-ts at the row-builder seam; DAO stays uncoerced"
key-files:
  created: []
  modified:
    - src/agents/alerter/src/signal.js
    - src/agents/alerter/src/outbound-db.js
    - src/agents/alerter/test/signal.test.js
    - src/agents/alerter/test/outbound-db.test.js
decisions:
  - "Validate quote shape in signal.js (not in caller); invalid -> warn + send unquoted (fail-open)"
  - "signal-cli's stringified timestamp coerced via Number() at the signal.js seam, not in the DAO"
  - "insertOutbound back-compat preserved: omitted row.signal_msg_ts stores NULL"
metrics:
  duration_minutes: ~25
  completed_date: 2026-05-23
requirements: [QUOT-01, QUOT-04]
---

# Phase 50 Plan 02: signal.js quote pass-through + signal_msg_ts persistence — Summary

Ship the outbound side of Signal-native quote threading: `send()` carries quote
payloads through to signal-cli REST `/v2/send`, and every successful send
persists the Signal-native ms-ts that signal-cli returns. Schema column landed
in Plan 50-01; this plan wires the producer (`signal.js`) and the DAO
(`outbound-db.insertOutbound`). No caller changes — Plan 50-03 is the first
caller to set `quote`.

## What shipped

### 1. New `send()` signature

```js
async function send(body, {
  bypassCap = false, to, intent,
  relatedCaptureId, relatedDraftId, sourceModule,
  quote,                              // NEW (Plan 50-02)
} = {})
```

`quote` is optional. When supplied, it MUST be:

- a plain object
- `quote.timestamp` is a finite number OR a numeric string (e.g.
  `"1779562666675"` — signal-cli REST 0.14.2 returns this form)
- `quote.author` is a non-empty string (e164, e.g. `"+59891840205"`)
- `quote.message` is a string (empty string `""` is accepted — Signal allows
  empty quote bodies)

Anything else (including `quote.timestamp = "notanumber"`, missing `author`,
non-string `message`) triggers:

```
[signal] invalid quote arg, sending without quote: {...}
```

…and the send proceeds **without** the quote field. This is the fail-open
posture per CONTEXT D-05 and memory
`[[feedback_no_silent_failure_after_farmer_confirm]]` — a vague ack beats no
ack at all. Plan-06's `{date} {log_type} ({summary})` disambiguator template
remains the belt-and-suspenders for these fail-open paths.

### 2. /v2/send payload shape (quote present)

Spike-verified against signal-cli REST `0.14.2` on 2026-05-23:

```json
{
  "message": "ack body",
  "number": "+59891840205",
  "recipients": ["+59891840205"],
  "quote": {
    "timestamp": 1779562666675,
    "author": "+59891840205",
    "message": "original farmer text"
  }
}
```

`payload.quote` is built only when `isValidQuote(quote)` returns true. Numeric
strings on `quote.timestamp` are coerced via `Number()` before serialisation.

### 3. insertOutbound row shape extension

`outbound-db.insertOutbound` now accepts a new field on the row:

```js
{
  // …existing keys…
  signal_msg_ts,   // Plan 50-02: bigint | null
}
```

The INSERT column list and VALUES placeholder list both grow by one (`$11`).
Callers that omit `signal_msg_ts` (every existing caller at Plan-02 commit
time) store NULL — back-compat preserved. No coercion in the DAO; the
row-builder in `signal.js` is responsible for `Number()`-coercing the
stringified ms-ts before passing it down.

### 4. Persistence hook (single seam)

In the existing `if (outboundDb && pool)` block, the row passed to
`insertOutbound` now includes:

```js
signal_msg_ts: json.timestamp ? Number(json.timestamp) : null
```

This means **every** successful send writes a `signal_msg_ts` — not just
quote-bearing sends — which is what QUOT-01 demands. On the rare case where
signal-cli returns `{}` without a `timestamp` field, the column stores NULL
(best-effort; never invent ms-ts). `send()`'s return value is unchanged:
`{ ok, timestamp }`.

## Verification (all green)

- `npx jest test/outbound-db.test.js` — 11/11 pass (3 new Plan 50-02 cases +
  existing $1..$11 column-order test updated)
- `npx jest test/signal.test.js` — 45/45 pass (14 new Plan 50-02 cases)
- `npx jest --testPathPattern='outbound-confirm|capture-pipeline'` — 9/9 pass
  (existing send() consumers unaffected)
- Full alerter suite: 982/991 pass, 9 skipped, 0 fail
- `grep -n "payload.quote" src/agents/alerter/src/signal.js` → line 121
- `grep -n "signal_msg_ts" src/agents/alerter/src/signal.js` → line 187
- `grep -c "signal_msg_ts" src/agents/alerter/src/outbound-db.js` → 4 (column
  init + INSERT column list + VALUES placeholder + row.signal_msg_ts param)

## Caller compat sweep

`grep -rn "\.send(" src/agents/alerter/src/` shows ~14 sites across
`outbound-confirm.js`, `capture-pipeline.js`, `commit-watchdog.js`, etc. None
supply `quote` — all silently get the unquoted path with no behavior change.
Plan 50-03 is the first caller to set `quote` (on
`send_commit_outcome_ack` + `send_confirm_ack`).

## Threat-flag scan

Nothing new beyond the Plan threat register. `quote.author` / `quote.message`
flow into signal-cli REST inside the docker network (same posture as the
existing `body` text); no XSS or escaping surface introduced.

## Commits

- `36ad284` — feat(50-02): insertOutbound accepts row.signal_msg_ts
- `4340d3b` — feat(50-02): signal.js send() accepts opts.quote + persists
  signal_msg_ts

## Deviations from plan

None — plan executed exactly as written. Existing `$1..$10` test was updated
to assert the new `$1..$11` shape (this was implied by the plan's column-list
extension but not explicitly enumerated as a test-edit step).

## Self-Check: PASSED

- `src/agents/alerter/src/signal.js` exists, `payload.quote` at line 121,
  `signal_msg_ts` at line 187.
- `src/agents/alerter/src/outbound-db.js` exists with 4 `signal_msg_ts`
  references.
- Both commits (`36ad284`, `4340d3b`) present in `git log --oneline`.
- All targeted Jest suites green.
