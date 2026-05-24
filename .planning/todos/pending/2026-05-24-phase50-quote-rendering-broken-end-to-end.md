---
filed: 2026-05-24
source: Phase 50 LIVE-FIRE Step 3 + controlled curl probe (Santi-side; bot-side phone not accessible — it's a 4g router)
severity: CRITICAL — Phase 50's core wire-level mechanism is non-functional end-to-end
priority: high but DEFERRED — investigation rolled into the alerter-Python port (`2026-05-14-port-alerter-to-farm-agent-python.md`). Quote-threading should be re-attested as part of that migration's wire-level smoke, not as a standalone fix on the current Node+REST stack. Until then Phase 50's QUOT-* requirements are HERMETIC-ATTESTED ONLY.
disposition: defer-to-python-port
---

# Phase 50 quote-replies don't render on Signal clients despite REST returning 201

## What

`signal-cli-rest-api 0.200` advertises `capabilities.v2/send: ["quotes","mentions"]` via `/v1/about`. POST `/v2/send` with a properly-shaped `quote: {timestamp, author, message}` payload returns HTTP 201 with no warning. But Signal clients (Santi's Android phone confirmed 2026-05-24) render the resulting message as a plain bubble — **no quote-reply attachment, no "Original message" preview, nothing**.

This kills Phase 50's primitive at the wire layer. Every QUOT-* requirement assumes quote payloads round-trip end-to-end; if Signal protocol doesn't carry the quote, none of the routing, polite-terminal, ask-back fallback, or fail-open behaviors are observable on the farmer side.

## Controlled tests run 2026-05-24

### Test 1 — bot DM to Santi

```bash
curl -X POST "http://localhost:8085/v2/send" -H "Content-Type: application/json" -d '{
  "message": "PROBE - testing quote reply at v2/send. ...",
  "number": "+59891840205",
  "recipients": ["+59892893012"],
  "quote": {"timestamp":1779639858321,"author":"+59892893012","message":"harvest of nothing -- shelf was empty today, just a check-in"}
}'
# -> 201 {"timestamp":"1779641641693"}
```

Santi's Android Signal client received the message: **no quote bubble**. Verbatim Santi report: "NO QUOTE".

### Test 2 — natural production path (Phase 50 commit_outcome_ack)

The `7c659b8c...` draft hit `commit_failed` at 16:49:15Z. `outbound-confirm.js` dispatched `send_commit_outcome_ack` which built a valid quote via `tryBuildQuoteForDraft` (capture row exists, `signal_msg_ts=1779639858321`, sender=+59892893012, raw_text populated). No `[outbound-confirm] no quote target` warn, no `[signal] invalid quote arg` warn. The ack landed on Santi's phone with no quote.

### Test 3 — bot NTS (controlled, no human-in-the-loop)

```bash
# baseline NTS:
POST /v2/send {message:"NTS baseline...",number:"+59891840205",recipients:["+59891840205"]}
# -> 201 timestamp=1779641662213

# quote-reply NTS pointing at the baseline ts from THE SAME endpoint 2s prior:
POST /v2/send {message:"NTS quote-test...",number:"+59891840205",recipients:["+59891840205"],
               quote:{timestamp:1779641662213,author:"+59891840205","message":"NTS baseline..."}}
# -> 201 timestamp=1779641676644
```

Rendering on bot's NTS thread: **not verifiable** — bot phone is a 4g router (no display). Confirmation has to come either from a sniff of signal-cli's outgoing protobuf payload, from a re-ingestion of the NTS back into the alerter's receive-loop and inspecting `dataMessage.quote`, or from a different test recipient with display access.

## Possible root causes (ranked by likelihood)

1. **signal-cli-rest-api 0.200 silently drops the `quote` field before invoking signal-cli proper.** Capabilities listing is aspirational; actual implementation skips the field. Verify by `docker exec mushy-signal-cli-1 grep -rn 'Quote' /signal-cli-rest-api/src/` (or wherever the Go source lives in the container) and checking for v2/send marshalling.
2. **signal-cli 0.14.2 receives the quote args but doesn't include the QuoteData payload in the protocol-level Signal message.** Less likely — signal-cli proper has long-standing quote support per docs.
3. **Timestamp mismatch: the quote `timestamp` must be the EXACT Signal protocol message-id, which may differ from `signal_msg_ts` we recorded on inbound.** Plan 50-02 captured `signal_msg_ts` from `dataMessage.timestamp` per RESEARCH; if Signal uses a DIFFERENT ts as the quote-reference (e.g., serverTimestamp), all our quotes silently fail to resolve on the recipient side. **Worth a focused trace.**
4. **signal-cli daemon mode (`mode: normal`) handles `/v2/send` differently from one-shot CLI invocations, dropping quote args in the daemon RPC path.** Worth bypassing the daemon with a direct `signal-cli send --quote-timestamp ...` to compare.

## Why this is rolled into the alerter-Python port

The fix surface lives in three places — the Node alerter's signal.js, the signal-cli-rest-api Go wrapper, and signal-cli proper. Patching the Node side won't help if the wrapper or signal-cli are dropping the quote; patching the wrapper means forking + maintaining a Go service that's being rewritten anyway. The Python port (`2026-05-14-port-alerter-to-farm-agent-python.md`) is going to touch signal-cli integration end-to-end and should pick a signal-cli client library that lets us SEE and TEST the quote payload at the wire layer, then attest QUOT-01..06 against the real protocol-level send. That's a small explicit subtask of the port, not a separate phase.

## Recommended investigation order (whenever the port picks this up)

1. **Inspect signal-cli daemon's outbound trace** for any historical quote-bearing send. `docker logs mushy-signal-cli-1 | grep -i quote` should show whether the daemon received the quote args. If empty even when the alerter dispatched a quote — the REST wrapper is the culprit.
2. **Bypass REST: stop the daemon temporarily and run `signal-cli send -u +59891840205 --quote-timestamp ... --quote-author ... --quote-message ...`** as a CLI one-shot. If THAT renders correctly, the bug is in the REST→daemon path.
3. **Check signal-cli-rest-api GitHub issues** for "quote not rendered" or "v2/send quote" on releases 0.200 and below.
4. **Verify the captured `signal_msg_ts` is the right field.** Compare `dataMessage.timestamp` vs `serverReceivedTimestamp` vs `serverDeliveredTimestamp` in a fresh inbound envelope. Plan 50-02 captured `dataMessage.timestamp`; Signal protocol-quote may use a different field as the canonical message-id.
5. **Re-ingest the bot-NTS quote-test back through the alerter's receive-loop** — if signal-cli's incoming envelope on the NTS thread carries `dataMessage.quote.{id,authorNumber}` matching the original, the protocol round-trip works at the data layer AND the rendering issue is purely client-side. If the envelope does NOT carry `dataMessage.quote`, the wire-level send dropped it.

## Impact on outstanding Phase 50 work

- All 6 QUOT-* attestations blocked. The hermetic tests pass because they mock signal-cli; live-fire is the first observation.
- The "send_quote_closed" branch already logged firing in normal production traffic (`[outbound-confirm] send_quote_closed sent draft=77e1a873a9 status=needs_review` observed 2026-05-24 ~13:00) — but if quotes don't round-trip, that send-side firing means nothing; the receive-side `findDraftByQuotedMsgTs` resolution must be coming from somewhere else (likely Signal forwarded a `dataMessage.quote` payload from prior bot sends that ACTUALLY succeeded — which would contradict the rendering hypothesis). **Worth a focused investigation** — see if Signal's quote-data round-trip works DESPITE the visual not rendering, which would be a UX-vs-protocol split bug.
- Sibling findings filed same day stand on their own merits (`...quote-thread-missing-on-extraction-preview-and-ask-back.md`, `...extraction-preview-related-draft-id-null.md`, `...signal-capture-missing-followup-messages.md`) but are downstream of this root cause.

## Cross-references

- `.planning/phases/50-signal-native-quote-threading/50-LIVE-FIRE.md` (the runbook this finding blocks)
- `.planning/phases/50-signal-native-quote-threading/50-LIVE-FIRE_ack-quote.jpg` (screenshot evidence)
- `.planning/phases/50-signal-native-quote-threading/50-CONTEXT.md` D-01 (spike-pinned signal-cli 0.14.2 — needs re-verification)
- Memory: `[[feedback_verify_signal_send_attribution]]` (the cousin lesson: signal-cli send-side reports don't equal protocol-level state)
