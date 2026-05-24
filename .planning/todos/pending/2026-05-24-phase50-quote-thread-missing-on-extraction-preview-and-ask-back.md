---
filed: 2026-05-24
source: Phase 50 LIVE-FIRE Step 3 (Santi-driven) — 50-LIVE-FIRE_ack-quote.jpg
severity: design-gap (not regression — Phase 50 shipped with this scope explicitly)
priority: high (covers the highest-traffic farmer ack path, not the rarest)
---

# Phase 50 quote-threading coverage gap: extraction_preview + ask_back not wired

## What

Phase 50 wired the Signal-native quote payload into `send_commit_outcome_ack` + `send_confirm_ack` per the locked decision "the two highest-traffic acks" (50-CONTEXT.md). Live-fire run 2026-05-24 surfaced two more outbound intents that fire on the same farmer thread WITHOUT a quote attachment:

- **`extraction_preview`** — fires every time a draft enters `awaiting_farmer` and the bot needs the farmer to confirm/correct extracted fields. This is the MOST common ack the farmer sees (every captured event passes through here).
- **`ask_back`** — fires when extraction needs an unambiguous answer (e.g. "double-check the asset_ref"). High-traffic for the observation-of-unknown-asset class today.
- (`convo_reply` and other Phase 44 event-gate chit-chat outbounds are correctly NOT quote-wired — they're not draft-anchored.)

Effect: when a farmer juggles >1 open draft (the exact scenario Phase 50 exists to solve), an `extraction_preview` reply from the farmer has no way to anchor itself to a specific draft via the quote channel. Falls through to "most-recent-active" routing, which is exactly the ambiguity Phase 50 was filed to close.

## Evidence

`signal_outbound` 2026-05-24 16:24 ART (during LIVE-FIRE Step 3, Santi-driven):

```
intent              | signal_msg_ts | related_draft_id | body_head
extraction_preview  | 1779639873573 | NULL              | Can you double-check the asset_ref for this observation? ...
convo_reply         | 1779639868958 | NULL              | Logged as harvest-2026-05-24: empty shelf check ...
```

`signal_outbound.signal_msg_ts` is populated (Plan 50-01 capture-on-send is working), so the bot's own ts is recorded — but the outgoing /v2/send call carried no `quote: {timestamp, author, message}` payload, hence no quote-reply bubble on the farmer's phone (screenshot at `.planning/phases/50-signal-native-quote-threading/50-LIVE-FIRE_ack-quote.jpg`).

Code site for the gap: `src/agents/alerter/src/confirm/outbound-confirm.js`. The two wired branches build a quote via `tryBuildQuoteForDraft` and pass it into `safeSend`. The unwired branches (preview/ask_back) call `safeSend(..., null, ...)` for the quote slot.

## Why it shipped without coverage

The 50-CONTEXT.md scope decision picked the smaller surface (commit_outcome_ack + confirm_ack only) because the FAILED-vs-AMBIGUOUS branches of `commit_outcome_ack` were where the original `[[project_phase45_followon_edit_no_disambiguation]]` ambiguity surfaced. The team didn't yet have live evidence that `extraction_preview` had the same ambiguity load. Today's live-fire is that evidence.

## Fix sketch

Touch `outbound-confirm.js`. Extend `tryBuildQuoteForDraft` to be called by the dispatch sites for `extraction_preview` (Phase 38 → Phase 39 routing) and optionally `ask_back` (Phase 39 → ask-back routing — but ask_back is by definition sender-scoped not draft-scoped, so the quote target is "the most recent inbound capture from this sender", not "the capture that spawned a specific draft"; that's a slightly different resolver).

- For `extraction_preview`: should be a copy of the `send_commit_outcome_ack` dispatch — has a `draftRow`, resolves via `getCaptureQuoteTarget(captureId)`, FAIL-OPEN on null.
- For `ask_back`: different resolver — needs `getLatestInboundFromSender(sender)` or equivalent. Open design question.

Hermetic gate: a test mirroring `outbound-confirm.test.js`'s `send_commit_outcome_ack` case but for `extraction_preview`. Live-fire: re-run the LIVE-FIRE Step 3 trigger (any ambiguous observation that produces a preview) and verify the screenshot shows the quote-reply attachment.

## Cross-references

- `.planning/phases/50-signal-native-quote-threading/50-CONTEXT.md` D-04 (the algorithm that's now under-deployed)
- `.planning/phases/50-signal-native-quote-threading/50-LIVE-FIRE.md` Step 3 (the runbook surfaced this)
- `.planning/phases/50-signal-native-quote-threading/50-LIVE-FIRE_ack-quote.jpg` (screenshot evidence)
- Sibling finding filed same day: `2026-05-24-phase50-extraction-preview-related-draft-id-null.md`
- Memory: `[[project_phase45_followon_edit_no_disambiguation]]`, `[[feedback_no_silent_failure_after_farmer_confirm]]`
