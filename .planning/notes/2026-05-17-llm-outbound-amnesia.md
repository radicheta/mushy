---
date: 2026-05-17
author: claude (overnight research, read-only)
scope: alerter conversational-LLM outbound-context recall (finding 1b)
companion-notes:
  - .planning/notes/2026-05-16-findings-discussion-prep.md (finding 1b summary)
  - .planning/notes/2026-05-15-rambo-th-window-unscripted-run.md (original surfacing)
  - .planning/phases/36-signal-pre-gate/36-04-attestation.md (T+24h transcript)
  - .planning/phases/37-multi-farmer-routing/deferred-items.md (fix sketches a/b/c)
verdict: RECOMMEND Option (a*) -- surface the already-persisted `llm_reply` column in `fmtHistory`; defer durable signal_outbound table to v1.9+. Size S (~30 LOC + 2 tests).
---

# LLM outbound-amnesia (finding 1b) -- research note

## TL;DR

The deferred-items.md framing ("ring buffer vs persist-outbound vs hybrid") under-reads
the codebase. The LLM's own conversational replies are already persisted in
`signal_capture.llm_reply` (capture.js:200), but `fmtHistory()` in llm-client.js:33-40
emits only `r.transcript || r.raw_text` and never reads the `llm_reply` field. The
cheapest correct fix is a one-line projection change in `fmtHistory` plus a SELECT-list
expansion in `capture-history.js`. Process restarts (the stated weekly Compose-rebuild
concern) are a non-issue because durability is already there. Anthropic prompt caching
has no effect at this volume (well under any reasonable cache breakpoint floor) --
discuss anyway because the project's posture is cache-disciplined and a v1.8 candidate
plan will be read by future-Claude.

The finding's failure mode is real but mis-located. The T+24h kickoff that triggered it
was NOT sent through the LLM compose path -- it came from a Phase 36 attestation
script (manual or scheduled `signalClient.send`) that bypasses
`signal_capture.llm_reply` entirely. So a v1.7-tight fix closes the conversational-LLM
gap; a broader gap (every non-LLM bot send is invisible to future LLM context) is a
separate v1.9 candidate sized at the bottom.

---

## 1. Existing fix sketches (deferred-items.md:21-30)

### Sketch (a) -- Ring buffer

> Ring buffer of last N bot-sent messages per recipient, scoped per loop instance
> (lost on restart; cheap).

In-process Map keyed by recipient, holding the last N outbound message bodies. Filled
at every `signalClient.send` (would need a wrapper or a shared sink). Read at
`fmtHistory` time. Zero schema, zero DB writes. Loses state on every Compose rebuild
(weekly). For the failure mode at hand (Santi's "Ok" 12m46s after the kickoff), N=5 and
TTL=24h is fine, but if alerter rebuilds between kickoff and reply the LLM still sees
nothing. Risk: false confidence; we'd ship and discover the gap two months later when
a rebuild lands inside an active conversation.

### Sketch (b) -- Persist outbound

> Persist outbound to a new `signal_outbound` table (durable across restarts; minor
> schema change).

New Timescale table mirroring `signal_capture`'s shape but for outbound direction.
Every `signalClient.send` writes one row (probably via a wrapped client or a sink-
fanout in `signal.js`). `fmtHistory` UNION-or-second-query merges inbound + outbound by
timestamp. Durable, replayable, audit-friendly. Cost: about 120 LOC across schema +
DAO + integration + tests; 6 send sites to thread through (see section 2.C). Risk:
double bookkeeping if half the sends miss the wrapper.

### Sketch (c) -- Hybrid

> Ring buffer for hot path + DB write for audit/replay.

Union of (a) and (b). The ring buffer is redundant once the DB write lands; the only
argument is hot-path latency, and the LLM call itself costs 300-1500ms vs about 1ms
for a DB SELECT. The project's pattern is "DB-first, optimize later" (see capture-db.js,
signal_draft). I'd reject (c) in favor of pure (b) on simplicity grounds, but reject
(b) in favor of (a*) below on YAGNI grounds.

---

## 2. Current-state map

### A. Where conversation state lives today

- `signal_capture` table (capture-db.js:7-20). One row per inbound farmer message.
  Schema includes `llm_session_tag` (text) and `llm_reply` (text). The latter is the
  bot's reply to that inbound message, written by UPDATE after the send
  (capture.js:200). So outbound replies on the conversational path ARE durable,
  indexed by `(sender, captured_at)`, retained 24h+ by default. ALTER COLUMN paper
  trail in capture-db.js:32-34 shows this table is the project's conversational-state
  spine.
- `signal_draft` table (separate path, Phase 39 confirm loop). Not in scope for
  finding 1b -- confirm replies short-circuit before reaching the LLM path
  (36-04-attestation.md:89-96).
- No in-memory conversation state. `capture.js` is a per-message handler; nothing
  retained between invocations beyond what's in Postgres.

### B. What is fed into the next LLM call

Trace: receive-loop -> capture.handle (capture.js) -> llmClient.compose (llm-client.js).

1. History selection (capture.js:165-166):
   `captureHistory.selectRecentBySender(source, sinceMs)` with `sinceMs =
   capturedAtMs - 24h`. The SELECT lives in capture-history.js:8-13:

       SELECT captured_at, raw_text, transcript, message_type
       FROM signal_capture
       WHERE sender = $1 AND captured_at > $2
       ORDER BY captured_at ASC

   `llm_reply` is NOT in the projection. This is the bug locus.

2. Sensor snapshot (capture.js:167): live RH/T/CO2 + alerts_last_hour.
3. Current message (capture.js:171): text/transcript/attachmentCount/capturedAtMs.
4. `fmtHistory` (llm-client.js:33-40): formats each row as
   `[ts] message_type: 'body'` where `body = r.transcript || r.raw_text`. Even if
   `llm_reply` were in the projection, this formatter ignores it.
5. `buildUserBlock` (llm-client.js:49-62): assembles the four sections into one user
   turn. The Anthropic call (llm-client.js:69-76) is single-turn:
   `messages: [{ role: 'user', content: buildUserBlock(...) }]`. No `assistant` turns
   ever appear in the transcript.

### C. Outbound sites that bypass `signal_capture.llm_reply`

Greppable inventory (`signalClient.send` callers, src/agents/alerter/src/):

| Site | What it sends | Stored where |
|---|---|---|
| capture.js:192 | conversational LLM reply | YES -- signal_capture.llm_reply |
| receive-loop.js:73,85,91,102,106,112,189,211 | experiment ack/reject, command echoes | no |
| index.js:180,183,185 | RH alert bodies (alerter ops cycle) | no |
| confirm/outbound-confirm.js:33 | Phase 39 confirmation prompts | own draft-event log |
| extraction/outbound.js:55 | Phase 38 extraction previews | own pipeline log |
| Phase 36 attestation script | T+24h kickoff (the actual trigger of finding 1b) | no |

The conversational-LLM path has durable outbound but doesn't read it; every other send
is invisible to the next LLM turn. The actual T+24h kickoff that caused the amnesia is
in the "invisible" set (36-04-attestation.md:113), not the "durable but unused" set.

---

## 3. Option comparison

I rename the options to keep the original sketch letters intact and add (a*) for the
"use what we already persist" variant -- which the deferred-items framing missed.

| Axis | (a) ring buffer | (a*) read llm_reply | (b) signal_outbound | (c) hybrid |
|---|---|---|---|---|
| Storage cost | 0 | 0 (already stored) | +1 table, ~30 rows/farmer/day, trivial | same as (b) |
| Token cost per LLM call | +N*~50 tok | +N*~50 tok | +N*~50 tok | +N*~50 tok |
| Restart durability | LOST | durable | durable | durable |
| Captures non-LLM sends (alerts, attestation kickoffs, experiment acks)? | no unless every site instrumented | no same problem | yes if every site routes through wrapper | yes |
| Prompt-cache stability | unstable | same | same | same |
| Code surface | ~40 LOC (Map + TTL sweep + wrapper) | ~10 LOC (1 SELECT col + 1 fmtHistory line) | ~120 LOC (DDL + DAO + wrapper + 6 site edits + tests) | ~150 LOC |
| Tests touched | +2 | +2 | +4-6 | +4-6 |
| Closes finding 1b for the T+24h scenario? | no (kickoff bypasses ring) | no (kickoff bypasses llm_reply too) | yes if wrapper is mandatory | yes |
| Farmer-visibility surprise risk | low | low | low | low |

Critical observation: options (a) and (a*) do NOT actually close the specific T+24h
incident because the Phase 36 attestation kickoff was not sent through the LLM compose
path nor through anything that touches `llm_reply`. Only (b)/(c) -- which thread every
outbound through a sink -- fix the exact incident.

But (a*) closes the majority class of amnesia (conversational misfires within a chat
thread) for ~10 LOC. The T+24h class is exotic: ad-hoc attestation pings will remain
rare in steady-state operation. Reasonable to accept the residual.

---

## 4. Anthropic prompt-caching interaction

(From training-time knowledge of the Anthropic prompt-caching feature; web verification
was blocked this session. Treat exact numbers as memory-grade, not citation-grade --
verify before relying on cost math.)

Relevant mechanics:

- Default TTL: 5 minutes from last cache hit (refreshed on each read).
- Extended TTL beta: 1 hour (separate pricing tier).
- Up to 4 cache breakpoints placeable via `cache_control: {type: 'ephemeral'}` on a
  content block.
- Minimum cacheable prefix: about 1024 tokens for Sonnet (larger for smaller models).
- Cache write cost: about 1.25x base input (5min) or about 2x (1h).
- Cache read cost: about 0.1x base input.
- Cache hit requires the prefix to be byte-identical up to the breakpoint.

Implication for the alerter today:

The current SYSTEM_PROMPT (llm-client.js:10-19) is ~150 tokens. The user block runs
maybe 200-800 tokens (snapshot + 5-20 history lines + current msg). Total prompt is
well under 1024 tokens -- caching is unavailable today regardless of structure. No
sketch changes that fact at v1.7 volume.

If the alerter ever grew to a >1K-token system prompt (e.g. inlined farmer profile,
farmOS vocab dump, multimodal-extraction-style instructions), the cache-friendly
structure is:

1. `system` block with `cache_control: {ephemeral}` -- gets the system prompt + any
   stable per-farmer prelude.
2. `messages[]` as `[{role:'user', content: history_block + cache_control}, {role:
   'user', content: current_turn}]` -- history-then-tail layout so the cache hits up
   through the prior turn and only the new turn pays full input rate.

The classic anti-pattern (which all four sketches happen to avoid because the alerter
is single-turn) is rebuilding the user block from scratch every turn. The alerter does
this today (buildUserBlock concatenates everything into one big string per call), so
today no fix matters. A future v1.9+ refactor that splits the user block into stable-
prefix + tail content blocks would unlock caching IF the prompt grows past 1K tokens.

Cache-aware ranking of the four options at a hypothetical future >1K prompt:

- (a*) is cache-neutral: same one-big-user-block shape, slightly different content.
- (a) is cache-neutral for the same reason.
- (b)/(c) are cache-neutral unless merged-outbound history is structured as a separate
  cached block -- a separate refactor.

None of the four options helps OR hurts caching today. The conversation here is purely
about correctness of recall, not cost.

(Side note: the 5-minute TTL is also irrelevant to finding 1b. The Santi gap was
12m46s -- already past TTL. Whatever caching exists wouldn't have helped that turn.)

---

## 5. Recommendation: Option (a*) -- surface llm_reply in fmtHistory

### Why

1. Matches existing patterns. MEMORY entries
   `feedback_use_venv_not_break_system_packages`,
   `feedback_no_em_dashes_in_artifacts`, and the general "minimum code that solves the
   problem" karpathy guideline all point the same way: 10 LOC against a real bug beats
   120 LOC against a hypothetical clean architecture.
2. Durability already paid for. `signal_capture.llm_reply` is written every
   conversational turn (capture.js:197-206). The data is there. Not reading it is the
   bug.
3. Restart-survival is free. The brief's stated weekly-rebuild concern is satisfied
   without new schema -- Compose rebuild loses container state but not Timescale rows.
4. Closes the dominant class of finding 1b. Most amnesia episodes happen within an
   active chat thread (Santi messages, bot replies, Santi messages again). That entire
   class is fixed by reading `llm_reply` into history.
5. Leaves the rare class (non-LLM outbound -> farmer reply that hits LLM path)
   explicitly open as a v1.9 candidate. Easier to file the residual than to scope
   universal outbound capture in v1.7.
6. No prompt-cache regression -- equivalent structure to today.
7. No new behavioral surface for the farmer. Bot will "remember" within an already-
   active chat. No surprise that wasn't already the implied UX.

### What I'd reject and why

- (a) Ring buffer. Strictly worse than (a*): same coverage, less durability, more code.
  Only argument is "avoid one extra DB column in the SELECT" -- non-argument.
- (b) signal_outbound table. Right answer for "every bot send is in LLM context",
  wrong size for v1.7. File as v1.9 candidate.
- (c) Hybrid. Premature.

---

## 6. Sizing

### Option (a*) -- recommended

Size: S. About 30 LOC total, 2 test additions, no migration.

Files touched:

1. /mnt/slime-kingdom/opt/mushy/src/agents/alerter/src/capture-history.js
   - Extend SELECT projection at line 9 to include `llm_reply`. ~1 LOC.
   - Optionally extend the function to emit synthetic outbound-row entries interleaved
     by timestamp (cleanest), or pass the row through and let fmtHistory project two
     lines per row. ~10 LOC max.
2. /mnt/slime-kingdom/opt/mushy/src/agents/alerter/src/llm-client.js
   - Modify `fmtHistory` (line 33-40) to emit one inbound line AND one outbound line
     per row when `llm_reply` is non-null. Use `assistant` or `bot` as the role label.
     ~10 LOC.
   - Consider raising `MAX_HISTORY_ROWS` from 20 to 30 to absorb doubled line count,
     or count "turns" rather than "rows". ~2 LOC.
3. /mnt/slime-kingdom/opt/mushy/src/agents/alerter/test/llm-client.test.js (or
   equivalent -- check existing test pattern)
   - Add fixture: capture row with `llm_reply` set.
   - Assert formatted history contains both inbound and outbound lines.
   - Snapshot-pin the prompt string (project loves snapshot pinning, see
     `sanitizeReply` tests).
4. /mnt/slime-kingdom/opt/mushy/src/agents/alerter/test/capture-history.test.js (if
   exists; if not, skip).
   - Assert `llm_reply` appears in SELECT result.

Verification loop:
- Unit: `npm test` in alerter -- both new tests + 626/626 baseline green.
- Live: replay a stored `signal_capture` row with `llm_reply` populated, confirm next
  compose call includes outbound line. Direct Timescale query per
  `feedback_timescale_over_screenshots`.

### Option (b) -- deferred v1.9 candidate

Size: M. About 120 LOC, schema migration, 6 send-site edits, ~4 new tests.

Files touched (sketch):

1. src/agents/alerter/src/outbound-db.js (new): `signal_outbound` DDL +
   `insertOutbound` + `selectRecentByRecipient`.
2. src/agents/alerter/src/signal.js: wrap `send()` to fan-out to outbound-db sink.
3. src/agents/alerter/src/capture-history.js: merge inbound+outbound queries by ts.
4. src/agents/alerter/src/llm-client.js: same fmtHistory change as (a*).
5. 6 send sites confirmed routed through the wrapper (greppable list in section 2.C).
6. Tests: outbound-db unit, signal.send fan-out, merged history ordering, ts-merge
   tie-break.

Risk: any forgotten send site (or any new send site added later that bypasses the
wrapper) silently regresses the gap. Mitigation: lint rule or grep-gate in CI for raw
`.send(` outside of `signal.js`.

### Option (c) -- hybrid

Size: L. All of (b) plus a TTL'd Map + invalidation logic. I would not ship this.

---

## 7. Open questions for Don Santiago

1. Are you OK with the residual (rare class: non-LLM bot send followed by farmer
   reply that lands on the conversational LLM path) being explicitly deferred to v1.9?
   If not, jump straight to (b).
2. The (a*) fix will make the LLM "remember" its prior conversational reply within a
   single thread. Any thread where you'd want the bot to forget on purpose (e.g. test
   sessions, snooze windows)? Defaults: include everything from the last 24h, same
   window as inbound history.
3. `llm_reply` is a single text column. Multi-line replies are stored as-is. Confirm
   we can emit them verbatim to the LLM (no truncation policy beyond the existing
   `.slice(0, 200)` per-line cap in fmtHistory -- which would silently truncate long
   bot replies). Recommend bumping the cap to 400 for outbound lines only.

---

## 8. Companion gap (file separately if accepted)

The "every bot send is invisible" gap covers:

- RH alert text (index.js:180/183/185) -- farmer replies to an alert and the LLM
  doesn't know what the alert said.
- Experiment ack/reject (receive-loop.js:73-112) -- farmer asks "did it work?", LLM
  has no record of the prior ack.
- Phase 36 attestation kickoffs (the actual finding-1b trigger).
- Phase 38 extraction previews + Phase 39 confirm prompts (these have their own state
  machines, so probably out of scope for "conversational LLM context").

If Option (b) gets greenlit, the migration that adds `signal_outbound` should be
shaped to absorb ALL outbound (one row per `signalClient.send` call regardless of
caller), so a single grep-gate in CI suffices.

---

## 9. Verdict

Ship Option (a*) as a v1.7.x bug-fix-class change. File Option (b) as a v1.9 candidate
titled "universal outbound-context capture for LLM recall" with the companion-gap
inventory above. Reject (a) and (c) outright.

Estimated end-to-end clock for (a*) including UAT: 1 short session.
