---
phase: 50-signal-native-quote-threading
plan: 03
subsystem: alerter/confirm
tags: [signal, outbound, quote, confirm-loop, fail-open]
requires: [50-01, 50-02]
provides:
  - "outbound-confirm safeSend(body, target, draftId, intent, quote) forwards opts.quote to signal.js"
  - "send_commit_outcome_ack dispatch resolves source_capture_ids[0] -> quote payload (best-effort)"
  - "send_confirm_ack dispatch resolves source_capture_ids[0] -> quote payload (best-effort)"
  - "confirm-db.getCaptureQuoteTarget(pool, captureId) -> {signal_msg_ts, sender, raw_text} | null"
affects:
  - "createConfirmOutbound factory now accepts optional pool + confirmDb (back-compat: omit -> unquoted)"
  - "index.js wires pool + confirmDb into confirmOutbound"
tech-stack:
  added: []
  patterns:
    - "Multi-layer fail-open: helper returns null on any error, dispatcher logs warn + sends unquoted"
    - "Empty source_capture_ids stays silent (expected shape); lookup failure warns"
    - "raw_text truncated to 200 chars at the dispatch seam (avoid /v2/send payload bloat)"
key-files:
  created: []
  modified:
    - src/agents/alerter/src/confirm/confirm-db.js
    - src/agents/alerter/src/confirm/outbound-confirm.js
    - src/agents/alerter/src/index.js
    - src/agents/alerter/test/confirm/confirm-db.test.js
    - src/agents/alerter/test/confirm/outbound-confirm.test.js
    - src/agents/alerter/test/confirm/fake-pool.js
decisions:
  - "Computed quote inside the send_confirm_ack case (split from the shared bottom path) rather than threading the quote arg through the generic fall-through; keeps the 6 untouched cases verifiably quote-free"
  - "warn fires when lookup was attempted but yielded nothing (missing row / NULL ts / DB error); empty source_capture_ids stays silent"
  - "pool + confirmDb are optional factory args -- pre-Plan-03 callers (none today, but defensive) still work, just unquoted"
metrics:
  duration_minutes: ~20
  completed_date: 2026-05-23
requirements: [QUOT-04, QUOT-05]
---

# Phase 50 Plan 03: Outbound quote-threading at the two highest-traffic ack dispatch sites -- Summary

Wire Signal-native quote payloads into `send_commit_outcome_ack` (Phase 45
commit-outcome ack, T4 / T6) and `send_confirm_ack` (Phase 39 confirm prompt
ack). At dispatch time we look up `draftRow.source_capture_ids[0]` in
`signal_capture` and, when `signal_msg_ts` is populated, pass
`quote: {timestamp, author, message}` to `signal.js send()` -- which Plan
50-02 already validates and forwards to signal-cli REST `/v2/send`.

## 1. safeSend signature extension

```js
async function safeSend(body, target, draftId, intentOverride, quote) {
  const opts = { to: target, intent: intentOverride || 'confirm_prompt',
                 relatedDraftId: draftId || null,
                 sourceModule: 'outbound-confirm.js' };
  if (quote) opts.quote = quote;     // Plan 50-03: pass-through
  const res = await signalClient.send(body, opts);
  ...
}
```

5th positional arg. Existing 4-arg callers (the 6 untouched cases) silently
take the unquoted path.

## 2. Quote-aware dispatch sites (2 of 8)

`send_commit_outcome_ack` (around outbound-confirm.js:209) and
`send_confirm_ack` (around :149) both call:

```js
const quote = await tryBuildQuoteForDraft(draftRow || null);
const res = await safeSend(body, dm, draftRow && draftRow.id,
                           'commit_outcome_ack' /* or undefined */, quote);
```

`tryBuildQuoteForDraft` returns `null` (degrading to unquoted ack) when:

- `pool` or `confirmDb` is missing on the factory (defensive)
- `draftRow` is falsy
- `draftRow.source_capture_ids` is empty or non-array
- the capture row is missing
- `signal_capture.signal_msg_ts` is NULL
- `getCaptureQuoteTarget` throws (DB error)

The first three are silent (expected shapes). The last three warn:

```
[outbound-confirm] no quote target for draft=<truncId> capture=<truncId> -- sending unquoted ack
```

When the lookup succeeds, the payload shape is:

```js
{
  timestamp: Number(capture.signal_msg_ts),
  author:    capture.sender,
  message:   String(capture.raw_text || '').slice(0, 200),
}
```

## 3. Deferred dispatch sites (6 of 8)

Per CONTEXT explicit scope ("first ship is the 2 highest-traffic acks
only"), the following remain quote-free in this plan:

| Side-effect | Note |
|---|---|
| `send_preview_resend` | farmer hasn't seen the previous preview yet -- nothing to quote against; group-aware path |
| `send_discard_ack` | NO ack; quote adds little |
| `send_expired_note` | terminal-state notice; can roll in once pattern is proven |
| `send_confirm_idempotent_ack` | "already locked in" -- nice-to-quote but follow-on |
| `send_nudge` | follow-on |
| `send_edit_cap_msg` | follow-on |

Regression-guarded by a parameterised `test.each` that asserts each of
the 6 calls `signal.send` with `opts.quote === undefined` and does NOT
touch `confirmDb.getCaptureQuoteTarget`.

## 4. confirm-db.getCaptureQuoteTarget helper

```js
async function getCaptureQuoteTarget(pool, captureId) {
  if (!captureId) return null;
  if (!pool || typeof pool.query !== 'function') return null;
  try {
    const r = await pool.query(
      'SELECT signal_msg_ts, sender, raw_text FROM signal_capture WHERE id = $1 LIMIT 1',
      [captureId]
    );
    const row = r && r.rows && r.rows[0];
    if (!row || row.signal_msg_ts == null) return null;
    return { signal_msg_ts: row.signal_msg_ts,
             sender: row.sender,
             raw_text: row.raw_text == null ? '' : row.raw_text };
  } catch (_e) {
    return null;
  }
}
```

Never throws; null on any failure. Returns `raw_text: ''` (not null) for
image-only captures, so the dispatcher can pass through to `.slice(0, 200)`
without an extra guard.

## 5. Fail-open posture (the rule)

This plan is the consumer-side proof of memory
`[[feedback_no_silent_failure_after_farmer_confirm]]` -- every terminal
state post-farmer-YES MUST farmer-ack, success OR failure. When the quote
lookup chain (capture-row / signal_msg_ts / DB) fails, we emit the ack
without the quote bubble rather than letting the farmer's reply vanish
into a thrown error. The Phase 45 Plan 06 `{date} {log_type} ({summary})`
disambiguator template remains in the ack BODY as belt-and-suspenders --
if the quote bubble doesn't render (older Signal client, clipped, fail-open
path), the body text still tells the farmer which observation the ack
refers to.

## Verification

- `npx jest test/confirm/confirm-db.test.js --no-coverage` -> 23/23 green
  (6 new Plan 50-03 cases)
- `npx jest test/confirm/outbound-confirm.test.js --no-coverage` -> 26/26
  green (17 new Plan 50-03 cases, 9 pre-existing untouched)
- Full alerter suite: 1010 passed / 9 skipped / 0 failed across 75 suites
- `grep -n "tryBuildQuoteForDraft" outbound-confirm.js` -> definition +
  2 call sites (commit_outcome_ack, confirm_ack)
- `grep -n "getCaptureQuoteTarget" confirm-db.js` -> definition + export
- `grep -n "safeSend(body" outbound-confirm.js` -> 3 calls (2 new 5-arg +
  1 unchanged shared bottom path serving the 6 untouched cases)
- ASCII check (U+2014): clean on both modified `.js` files

## Commits

- `e97874a` -- feat(50-03): confirm-db.getCaptureQuoteTarget helper
- `9d65293` -- feat(50-03): quote-thread send_commit_outcome_ack +
  send_confirm_ack

## Deviations from plan

**1. [Rule 3 - Blocking issue] createConfirmOutbound factory did not previously
   accept `pool` + `confirmDb`.**
- **Found during:** Task 2 wiring.
- **Issue:** The plan's `<interfaces>` claimed `outbound-confirm.js already
  destructures pool + confirmDb from its factory args (Phase 45 wiring)`,
  but the actual factory signature in `src/confirm/outbound-confirm.js:29`
  only took `{signalClient, previewBuilderConfirm, operatorRecipient, logger}`,
  and `src/index.js:297` did NOT pass pool/confirmDb when constructing it.
- **Fix:** Added `pool = null, confirmDb = null` to the factory destructure
  (both optional, defaulting to null -> dispatcher degrades to unquoted acks)
  AND threaded `pool, confirmDb: confirm.confirmDb` through the
  `index.js:297` call site. Defensive shape: every test case in this plan's
  test file exercises the pool-and-confirmDb-present path, but one extra
  test (`no pool/confirmDb in scope -> ack sends WITHOUT quote, no crash`)
  guards the back-compat path so a future caller construction that omits
  them still ships acks.
- **Files modified:** `src/confirm/outbound-confirm.js`, `src/index.js`
- **Commit:** `9d65293`

## Cross-references

- CONTEXT D-03 (lookup chain) -- locks `source_capture_ids[0]` as the quote anchor
- CONTEXT D-05 (best-effort) -- drives the fail-open posture
- `[[feedback_no_silent_failure_after_farmer_confirm]]` -- the rule
- 50-01 SUMMARY -- schema column `signal_capture.signal_msg_ts` we SELECT
- 50-02 SUMMARY -- `signal.js send()` quote validation + `/v2/send` payload shape
- Phase 45 Plan 06 -- disambiguator template remains as belt-and-suspenders

## Known Stubs

None.

## Threat Flags

None -- threat surface matches the plan's threat register
(T-50-03-01..05 + T-50-03-SC). No new endpoints, no new auth paths,
no new schema, no new deps.

## TDD Gate Compliance

This plan combined RED + GREEN per task into a single commit each
(test + impl shipped together). Both Task 1 (`e97874a`) and Task 2
(`9d65293`) are `feat(...)` commits that include both the failing-tests-
turned-passing AND the production code. RED was empirically observed
in the working directory (6 failing test cases in Task 1, 6 failing in
Task 2) before the implementation was added; the working state was
never committed mid-RED. Pre-existing tests stayed green throughout.

## Self-Check: PASSED

- `src/agents/alerter/src/confirm/confirm-db.js` line 306 -- `getCaptureQuoteTarget` exists.
- `src/agents/alerter/src/confirm/outbound-confirm.js` line 78 -- `tryBuildQuoteForDraft` exists; lines 149 + 209 are the two call sites.
- `src/agents/alerter/src/index.js` line ~302 -- `pool` + `confirmDb` wired into the factory.
- Both commits (`e97874a`, `9d65293`) present in `git log --oneline`.
- `test/confirm/confirm-db.test.js` + `test/confirm/outbound-confirm.test.js` green.
- Full alerter Jest suite green.
