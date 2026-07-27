---
filed: 2026-05-24
source: Phase 50 LIVE-FIRE Step 3 — DB inspection
severity: HIGH (data-quality / paper-trail gap; affects Phase 50 quote routing + Phase 51 stub-merge audit)
priority: high
---

# `signal_capture` not persisting follow-up farmer messages in active draft threads

## What

Between 16:24:21Z and 16:49:15Z 2026-05-24, Santi (`+59892893012`) sent the bot at least three inbound messages in a single DM thread. Only the FIRST one landed in `signal_capture`:

```
SELECT captured_at, sender, signal_msg_ts, substr(raw_text,1,80)
  FROM signal_capture
  WHERE sender='+59892893012' AND captured_at > now() - interval '40 minutes';
-- → 1 row: 16:24:21 "harvest of nothing -- shelf was empty today, just a check-in"
```

But the alerter clearly processed at least two more inbound messages from Santi in that window:

- A message that updated `signal_draft.7c659b8c...` `draft_json.asset_ref` to `"999999_FAKE_99"` and `state` to `"looking great today"` (between ~16:25 and ~16:46:54Z when the bot dispatched the confirm_prompt with those new values).
- A `YES` reply between 16:46:54Z and 16:47:51Z (when the bot dispatched "Locked in. Writing now." and triggered commit-attempt).

Neither shows in `signal_capture`. The draft's `source_capture_ids` array contains only the original ULID.

## Why this matters

1. **Phase 50 quote routing breaks for any reply after the first message.** `findDraftByQuotedMsgTs(quoted_msg_ts)` JOINs through `signal_capture.signal_msg_ts`. If the inbound row isn't persisted, the farmer's quote-reply can never resolve to its source draft via the structured path — falls through to most-recent-active. The entire phase is built on the premise that every inbound carries `signal_msg_ts` AND lands in `signal_capture`.
2. **Phase 51 stub-merge audit cannot reconstruct the conversation.** "Show me everything the farmer said about draft X" returns the first message only.
3. **Forensic queries silently undercount.** Any "messages per farmer per week" metric is wrong by the followup-multiplier (likely 2-4x for typical sessions).
4. **No paper trail of farmer EDITs / YES / NO confirmations on the alerter side.** The fact that Santi typed YES is inferable from the bot's "Locked in" outbound and from commit-attempt audit events, but the *literal text Santi sent* is gone. For ambiguous cases (typo'd YEAH, "go ahead", "do it", etc.) the alerter has no evidence of what it interpreted.

## Hypotheses (need investigation)

- (H1) The Phase 44 event-gate or `convo suppressed by gate=haiku_chitchat` path persists nothing for non-event messages. YES/NO/EDIT in an active confirm thread are routed via a different path that doesn't touch `signal_capture`. The persistence happens at the LLM-event-extraction site, not at the receive-loop site.
- (H2) The capture write is wrapped in a try/catch that swallows DB errors. Some inbounds fail the write and the alerter continues processing in-memory.
- (H3) Captures with quote-payload (Signal swipe-to-reply) take a different code path that skips the capture write.

The fact that exactly ONE inbound landed (the first one) and all subsequent ones in the same thread were dropped points strongly at H1 — the capture write is gated on extraction-classification, not on receipt.

## Evidence trail

- Bot's 16:46:54Z `confirm_prompt` body contains `asset_ref: 999999_FAKE_99` — must have come from a farmer message.
- Bot's 16:47:51Z `confirm_prompt` body is "Locked in. Writing now. (draft 7c659b8c8e)" — must have come from a YES/CONFIRM message.
- Bot's 16:49:15Z `commit_outcome_ack` fired with `outcome=failed` — confirms commit_attempt fired, which means YES was processed.
- All three farmer messages have `signal_msg_ts` values that the bot's signal-cli stack saw (otherwise extraction wouldn't have run), but those ts values are nowhere in `signal_capture`.

## Suggested investigation

1. Grep `src/agents/alerter/src/` for every call site that inserts into `signal_capture`. Confirm the YES/EDIT/short-text paths reach an insert call.
2. Re-create the test by sending two messages in quick succession on dev (after dev gets capture wiring) — first one should land, second should NOT if H1 is right.
3. The fix is likely a single missed `insertCapture()` call at the EDIT/confirm-handler site, OR a config flag that gates capture writes by "is this an event" classification (where it should gate by "is this from a recognized farmer").

## Phase relevance

- Phase 50: this silently undermines QUOT-02 (`signal_capture.signal_msg_ts populated`) — the column EXISTS but the row doesn't. The hermetic tests pass because they explicitly insert mock rows; live-fire is the first time we'd notice.
- Phase 51: stub-merge audit will need to confirm a farmer was informed before enriching a stub. Without follow-up capture rows, the audit has no inbound side.

## Cross-references

- `.planning/phases/50-signal-native-quote-threading/50-LIVE-FIRE.md` Step 3 + Step 5 (the runbook assumes captures persist; they do not)
- `.planning/phases/50-signal-native-quote-threading/50-CONTEXT.md` D-04 (quote-resolution algorithm relies on this column)
- Sibling findings filed same day: `2026-05-24-phase50-quote-thread-missing-on-extraction-preview-and-ask-back.md`, `2026-05-24-phase50-extraction-preview-related-draft-id-null.md`
- Memory: `[[feedback_no_silent_failure_after_farmer_confirm]]` (every terminal state needs ack — but if the inbound isn't captured, the ack-vs-no-ack analysis can't be done)
