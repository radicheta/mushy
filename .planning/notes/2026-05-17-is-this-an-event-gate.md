---
date: 2026-05-17
author: claude (overnight research, read-only) -- summary recovered from sandboxed agent; full inline draft was lost when write was blocked
scope: design for an is-this-an-event gate before Phase 38 paid Sonnet extraction (finding 7)
companion-notes:
  - .planning/notes/2026-05-16-findings-discussion-prep.md (finding 7 summary)
  - .planning/notes/2026-05-17-llm-outbound-amnesia.md (finding 1b -- shares signal_outbound table; recommend bundling)
verdict: BUILD IT. Hybrid (rule pre-filter + Haiku 4.5 pre-classifier). Size M (~3-4 days gate-only, ~4-5 days bundled with finding 1b). BUNDLE with 1b for ~1.2x cost vs ~2x sequential.
---

# Is-this-an-event gate -- research note

## TL;DR

Finding 7 (phantom drafts from chit-chat) is real and pays NORTH-STAR risk every time.
The fix is a hybrid gate inserted at `src/agents/alerter/src/capture.js:147`:
1. Rule fast-path POSITIVE (image/audio/strain-code/block-name/long-text -> enqueue immediately)
2. Rule fast-path NEGATIVE (reply matches recent attestation kickoff + short text -> skip)
3. Haiku 4.5 pre-classifier on the gray zone (cheap binary "is_event")
4. Sonnet 4.6 only after gate passes

Bundle with finding 1b (LLM outbound amnesia) because both need the same new
`signal_outbound` table with intent-tagged bot sends.

## 1. Current gate stack (file:line)

Only ONE content-aware gate today between Signal-receive and paid Sonnet call:

- Sender whitelist: `src/agents/alerter/src/receive-loop.js:118-134`
- Command short-circuit (snooze/experiment): `receive-loop.js:179-216`
- Phase 39 confirm short-circuit (YES/NO/EDIT to in-flight draft): `receive-loop.js:220-264`
  -- this is the **only** content-aware bypass today; NOOP falls through to capture
- Capture pipeline always runs: `src/agents/alerter/src/capture.js:65-159`
- Extractor enqueue gate is **only** `farmosPerson !== '(unassigned)'`: `capture.js:147`
- Extractor model `claude-sonnet-4-6`, max_tokens 16384, 2 round-trips max:
  `extraction/extractor.js:101, 109, 152-181`
- Cached system prompt ~2.5-3K tokens: `extraction/prompts/system.js:217-231`

## 2. Why the 2026-05-15 23:28 "Ok" became phantom draft `6934760c`

Santi's 23:28:20 "Ok" arrived 12m46s after the bot's T+24h attestation kickoff at
23:15:34. His last draft `946a7b` had hit `commit_failed` 38h earlier, so
`findAwaitingForSender` returned null. `parseReply` returned a YES kind but had no draft
to attach it to -> NOOP fall-through at `receive-loop.js:262` -> `capture.js` fired
Sonnet 4.6 on the text "Ok" -> extractor produced a clean draft -> state-machine landed
it in `awaiting_farmer` -> Santi received a preview ping for a draft he didn't intend
to create. NORTH-STAR risk.

Status quo is NOT free.

## 3. Sample distribution (~25 messages, eyeballed)

Prod corpus `/mnt/mossrock/shared/mushdatadump-prod/` was permission-blocked from the
sandboxed agent. Sample drawn from recent UAT notes (`36-04-attestation.md`,
`2026-05-15-rambo-th-window-unscripted-run.md`, `2026-05-15-lion-mane-bridged-uat.md`,
`2026-05-14-prod-cutover-complete.md`):

| Class | Count (~25) | % | Action |
|---|---|---|---|
| Hard event (photo + caption / strain code / paper log) | ~9 | 36% | SHOULD extract |
| Confirm verbs to in-flight draft | ~7 | 28% | already gated by Phase 39 |
| Conversational ack on no-draft (the 6934760c case) | ~2 | 8% | finding 7 |
| UX feedback / meta | ~2 | 8% | should skip |
| Soft observation | ~3 | 12% | should extract |
| Greetings / chit-chat | ~2 | 8% | should skip |

~36% real events; ~64% currently burn paid Sonnet (with phantom-draft risk on subset).
Caveat: pilot-phase UAT bias; ratio will shift as farmers acclimate. **Need a
100-capture hand-classification from prod corpus before spec-locking** (per
`feedback_real_data_before_ship_gate_pass`).

## 4. Cost-per-1000-captures (Anthropic public pricing, Jan 2026)

| Option | $/1000 captures | Saves vs status quo | False-neg risk | Code surface |
|---|---|---|---|---|
| 3a -- Rules-only | $0 | ~50-65% of paid calls | 5-15% on free-text obs (NORTH-STAR risk) | ~150 LOC, no new infra |
| 3b -- Haiku 4.5 pre-classifier | ~$0.20 | ~$9.40 net saved at 64% chit-chat ratio | <5% (LLM is good at this binary) | ~120 LOC, new paid surface, +300-600ms latency |
| 3c -- Skip the gate | n/a | $0 saved | n/a, BUT farmer-pings still leak | 0 |

Baseline pricing assumptions: Sonnet 4.6 ~$0.012-0.025/call cache-warm; cached input
$1.50/M, output $15/M; Haiku 4.5 ~$1/M input, $5/M output.

## 5. Recommended hybrid (insert after `capture.js:147`)

1. **Rule fast-path POSITIVE.** ANY of:
   - image attachment OR audio attachment
   - strain-code regex `/\b[A-Z]{2,4}\b/` (per memory
     `project_phase38_b5_regex_relaxed`)
   - block-name regex `/\b\d{6}_[A-Z]{2,4}_\d+\b/`
   - text length > 200 chars
   -> enqueue immediately, no Haiku call.

2. **Rule fast-path NEGATIVE.** IF `lastBotOutbound.intent === 'attestation_kickoff'`
   within 30m AND reply text < 40 chars AND matches `^(ok|yes|got it|thanks|gracias|si)$/i`
   -> skip extractor. (This catches `6934760c` exactly.)

3. **Haiku gate (gray zone).** Single tool call `classify_capture {is_event, kind,
   confidence}`. If `is_event === true` OR `confidence < 0.7` -> enqueue. Else skip.

4. **Audit column.** `signal_capture.extraction_gate VARCHAR(32)` in
   `{skipped_rule_neg, fast_event, haiku_event, haiku_chitchat, forced}`. Per
   `feedback_keep_paper_trail_of_intermediates`.

**Bias toward extraction on any failure.** Haiku error/timeout -> fall through to
Sonnet. Missed events are NORTH-STAR violations; over-extraction is recoverable.

## 6. Bundling with finding 1b (LLM outbound amnesia)

Both finding 7 and finding 1b need a new `signal_outbound` table with intent-tagged bot
sends. Candidate intents:

- `ask_back` -- bot asked the farmer a question
- `attestation_kickoff` -- Phase 36 T+24h ping (the literal trigger of the 6934760c case)
- `commit_ack` -- the NORTH-STAR reply from finding 3
- `convo_reply` -- general conversational reply

Shared use:
- Gate uses `intent` for negative fast-path (finding 7).
- Phase 37 LLM-convo prompt consumes `lastBotOutbound.text` (closes finding 1b proper).
- Phase 39 confirm-router gets richer context too.

NB: finding 1b's primary recommendation (in `.planning/notes/2026-05-17-llm-outbound-amnesia.md`)
is Option (a*) -- just surface the already-persisted `signal_capture.llm_reply` column.
That's a 30-LOC fix. But the broader signal_outbound table is filed there as Option (b) /
v1.9 candidate; finding 7 elevates it. Bundling them moves Option (b) into v1.8 scope.

**Cost: ~1.2x bundled vs ~2x sequential. Recommend bundling.**

## 7. Phase 43 (proposed) plan sketch

1. `signal_outbound` table + persistence hook in `capture.js:191-194` (uses
   `signalClient.send` wrapper or sink fanout; covers all 6 send sites enumerated in
   the amnesia note section 2.C)
2. `bot-context.js` reader + Phase 37 prompt integration (closes finding 1b for the
   broader class)
3. `event-gate.js` rules-only -- SHIP and audit before paying for Haiku
4. `haiku-classifier.js` (only if Plan 03 audit shows >30% residual phantom rate)
5. 100-capture gate-eval set from prod corpus (smoke before paid batch per
   `feedback_smoke_before_expensive_batch`)
6. One-week live UAT + closeout per `feedback_real_data_before_ship_gate_pass`

## 8. Ship-gate

Per `feedback_real_data_before_ship_gate_pass`:
- Zero farmer-facing preview pings on hand-labeled chit-chat
- >=95% event recall

## 9. Open questions

1. Real prod chit-chat ratio -- need 100-capture hand-classification before spec-locking.
2. Acceptable to pay Haiku per gray-zone call, or rules-only acceptable as v1?
3. Should the gate also gate the Phase 37 LLM-convo `compose` call at `capture.js:168`
   (the other paid call per message)? Filed as v1.8 candidate; out of scope for this gate.
4. Does `signal_outbound` already exist? Not found in this run; new table assumed.

## 10. Verdict

Build the hybrid gate. Bundle with finding 1b's broader option (b). Treat as a single
v1.8 phase (~4-5 days). Plan order matters: ship rules-only first (Plan 03), audit one
week, only add Haiku (Plan 04) if residual phantom rate justifies the cost surface.
