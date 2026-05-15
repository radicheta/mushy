---
date: 2026-05-15
event_window_utc: 2026-05-15T22:52 to 23:17
farmer: vikki (f2)
draft_id: b8a1e586673b0e4f98495e614c93c26c27f010da876e139013d3c799d0f1eb9d
type: unscripted-prod-event
verdict: stack worked end-to-end up to farmOS commit; commit_failed (observation_requires_target); farmer silently left in the dark
filing_for: discuss-later (Don Santiago marker)
---

# Unscripted v1.7 prod event -- Vikki "Rambo smashes TH window"

First fully-unscripted, end-to-end run of the v1.7 multimodal Signal -> farmOS
stack on a real farmer event. Not a smoke. Not a synthetic fixture. A goat
(or other animal) named Rambo broke a window in the tropical-house
greenhouse, Vikki sent a photo, and the entire pipeline fired.

Filing this so we can pick the pieces apart in a dedicated session later.
Capturing everything now while the trail is hot.

## Timeline

| UTC | Actor | What happened |
|---|---|---|
| 22:52:21 | Vikki -> bot | Image + caption "Event Rambo smashes TH window" |
| 22:52:30 | Phase 38 (extractor) | Drafted observation, asset_ref="TH" conf 0.5, state="Window smashed by Rambo (animal). Photo shows window frame damage.", event_timestamp epoch conf 0.1. Preview asked her to double-check asset_ref. |
| 22:52ish | Phase 37 (LLM convo) | Replied: "Is this a chamber-check note for check-2026-05-15 -- can you confirm which grow room or block 'Rambo' refers to and whether the broken window is affecting your temp/humidity control?" -- conflated Rambo with a possible block name. |
| 22:59:24 | Vikki -> bot | EDIT-1: "Check pick metadata for timestamp. Animal RAMBO, no mushroom" |
| 22:59:24 | Phase 39 EDIT loop | Re-ran extractor with farmerCorrection plumbed in (Phase 39 byte-identical-when-empty regression test domain). Notes updated to "Farmer clarified: animal named Rambo, not mushroom-related. Timestamp unconfirmed -- check photo EXIF/pick metadata." asset_ref still "TH". |
| 23:15:50 | Vikki -> bot | YES (confirm) |
| 23:16:15 | Phase 40 commit attempt 1 | commit_router -> observation -> validator rejected with reason `observation_requires_target` |
| 23:16:45 | Phase 40 commit attempt 2 | same rejection (30s backoff worked) |
| 23:17:15 | Phase 40 commit attempt 3 -> commit_failed | same rejection; terminal state |
| 23:17:15+ | Phase 40 | **bot went silent**; no farmer-facing reply |
| 23:23:24 | mushy claude -> bot -> Vikki | Manual ack message sent explaining what happened (out-of-band; not part of the automated pipeline) |

Event sequence in `signal_draft_event` for `b8a1e586...`: edit(1) -> yes(2)
-> commit_attempt(3) -> commit_attempt_retry(4) -> commit_attempt(5) ->
commit_attempt_retry(6) -> commit_attempt(7) -> commit_failed(8). Clean
event-sourced trail. Watchdog backoff worked exactly as designed.

## What worked

1. **Phase 38 extraction on a 5-word caption + photo.** Got log_type,
   asset_ref hypothesis, state description, even a hedged confidence on
   event_timestamp because the photo didn't have a parseable timestamp.
   No hallucinated dates. Schema-valid output.
2. **Phase 39 EDIT loop with farmerCorrection re-extract.** Vikki's free-text
   "Animal RAMBO, no mushroom" was plumbed into the extractor, and the
   notes field updated to reflect the clarification. Byte-identical-when-empty
   invariant held -- the regression test from Phase 39 paid off here.
3. **Phase 39 YES confirm.** Plain "yes" routed to commit, no
   ceremony. Phase 36 receive-loop short-circuit behavior intact.
4. **Phase 40 commit-watchdog backoff (D-06).** 3 attempts at exactly
   15s, 30s, 60s intervals (well, ~30s apart per the timestamps). Did
   not retry forever; transitioned to terminal `commit_failed` cleanly.
5. **Phase 40 validator caught the violation.** `observation_requires_target`
   is the correct rejection -- the draft has no resolvable target asset.
   Better than silently writing a broken log to farmOS.
6. **The whole stack survived without operator intervention up to the
   point where it hit a real schema gap.** That is exactly the kind of
   "graceful degradation" we wanted.

## What broke (in increasing order of severity)

### Finding 1 (low): LLM conversational reply conflated "Rambo" with a block name

**Where:** Phase 37 LLM reply path (separate from Phase 38 extraction).

**Evidence:** llm_reply on capture 01KRPXEFFGJEBX53BFKMNRTT04:
"Is this a chamber-check note for check-2026-05-15 -- can you confirm
which grow room or block 'Rambo' refers to..."

**Why it matters:** Vikki had to spend an edit cycle clarifying that
Rambo was an animal. The extractor handled it fine (low confidence on
asset_ref); the LLM-convo path was overconfident in coercing "Rambo"
into a farm-domain noun.

**Severity:** Low. The pipeline self-corrected via the EDIT path.
But it's an extra round-trip we could avoid by tuning the LLM-convo
prompt to be more cautious about asserting block/chamber identity.

**Filing:** v1.8 candidate -- LLM-convo prompt tuning. May overlap with
the existing Phase 37 em-dash + OBJ-char prompt fixes; bundle into one
"Phase 37 prompt-pin sweep" plan.

**Update 2026-05-15 23:30Z (same session, additional evidence):** Plan 36-04
T+24h re-run produced TWO more live findings against the same Phase 37 LLM
reply surface (logged here for bundling into the prompt-pin sweep):

- **Finding 1b: LLM has no memory of its own outbound messages.** Bot
  sent T+24h kickoff at 23:15:34 ("reply ok to confirm Signal trust
  is still good"). Santi's "Ok" capture at 23:28:20 routed to the
  conversational LLM path (no pending draft to absorb). LLM replied
  (em-dashes preserved verbatim for forensic accuracy):
  *"Is this message confirming a specific session — inoculation,
  harvest, or chamber check — so I can log it correctly?"*
  The LLM did not realize it had asked the question 12m46s earlier.
  Operator had to manually ack Santi out-of-band. The fix needs a
  one-turn outbound context shim: thread the most recent bot-sent
  message into the system prompt when classifying inbound replies.
- **Finding 1c: live em-dash leak (recurrent).** Same reply contained
  two em-dashes (`—` codepoint). 2nd live em-dash leak on the
  LLM reply path (1st was 2026-05-11 per existing Phase 37
  deferred-items.md). Confirms recurrence. Prompt-pin sweep is
  necessary, not optional.

### Finding 2 (medium): commit-router has no fallback for unregistered observation targets

**Where:** Phase 40 commit-router observation path.

**Evidence:** 3x `observation_requires_target` rejections on draft
`b8a1e586...`. The greenhouse (TH) isn't a registered farmOS asset of
the bundles Phase 40 knows about (fungi/sterilization_batch). Result:
the only commit option is rejected.

**Why it matters:** v1.7 was scoped to "Signal -> mushroom assets". TH is
a structure, not a mushroom asset. But farmers don't know that scope;
they send the events that happen at their farm. Real farms have
greenhouses, irrigation lines, animals, weather events.

**Options for fix:**
- **A. Farm-level observation fallback.** If no target resolves, attach
  the observation as a farm-level (no-target) log. farmOS supports
  this; the validator currently rejects it.
- **B. Register non-fungi assets.** Add a bundle for structures
  (greenhouses, sheds, irrigation zones) so TH becomes a real asset.
  Bigger schema change; farmOS team coordination.
- **C. Farmer-facing reply: "couldn't find TH as a registered asset --
  log as farm-level note?"** Asks for explicit fallback. NORTH-STAR-safe.
- **D. Defer scope.** Keep mushroom-only. Tell farmers "this only logs
  mushroom events." Cost: farmers can't use the channel for anything
  else; they'll route around the bot or stop using it.

Recommendation: **C + A combined**. C gives the farmer agency; A is the
escape hatch when farmers want to use the channel for whatever they want
to log. B is v1.9+.

**Filing:** 999.x backlog candidate. Concrete: "Phase 40 commit-router
fallback for unregistered observation targets + farmer-facing nudge."

### Finding 3 (HIGH, NORTH-STAR violation): commit_failed leaves the farmer in the dark

**Where:** Phase 40 commit-watchdog terminal state.

**Evidence:** After commit_attempt 3 -> commit_failed at 23:17:15Z,
the bot sent nothing back to Vikki. As of 23:23:24Z when mushy claude
sent the manual ack, she had been in the dark for 6 minutes (and would
have remained so indefinitely without operator intervention). She
confirmed her event with YES and the system silently dropped it.

**Why it matters:** This is a NORTH-STAR violation. The whole premise
of v1.7 is "no bookkeeping tax on farmers." But the implicit contract
is also "if the farmer confirms an event, the farmer knows whether it
landed." Right now: confirm -> silence is a failure-mode outcome.
Worse than the timer-vs-bot baseline.

**Compare to good behavior on success path:** commit_success would
ideally also send a reply, even just a thumbs-up emoji or "saved." But
at minimum, commit_failed MUST.

**Filing:** 999.x or v1.8 headline candidate. Concrete: "Phase 40
commit-failure farmer-facing reply (NORTH-STAR fix)." Should include
the success-path acknowledgment too while we're in there. Companion to
Finding 2 (C) since the failure-side and the fallback-prompt-side
share the same notification surface.

**Severity escalation candidate:** I'd argue this should NOT wait for
v1.8 scope discussion. It's a single small reply path in the commit
watchdog. Could be a same-week fix.

## Cross-cutting observations

### "Unscripted prod event" is now a real evaluation surface

v1.7's tests + smokes were all curated or replayed corpus. This event
is the first time the full stack ran on a real unprovoked farmer
message that hit an edge case the schema didn't cover. The corpus dir
at /mnt/mossrock/shared/mushdatadump-prod/ should absorb this -- file
it as a known-edge-case fixture for future regression.

### Phase 39 EDIT loop is paying for itself

Without the EDIT path, this would have been a hard-fail: extractor
drafts something, farmer disagrees, only option is NO (discard). With
EDIT, Vikki could correct in natural language and the system did the
right thing structurally even though the final commit failed. The
correction round-trip latency was ~7 minutes from initial send to
re-prompt -- acceptable for non-time-critical observations.

### Phase 40 backoff schedule worked

attempt 1 -> attempt 2 -> attempt 3 spaced at ~30s, ~30s. D-06
locked at 15s/30s/60s in the plan; actual was tighter (30s flat)
but acceptable. Worth verifying the backoff config got the actual
exponential schedule we documented in 40-RUNBOOK.md.

### The "post-acknowledge silence" pattern is now visible across two surfaces

- Phase 40 commit_failed silence (this finding)
- The receive-loop short-circuit pattern from Plan 36-04 attestation
  (Don Santiago's "ok" got absorbed as a YES confirm without the
  farmer knowing it was ALSO the Plan 36-04 SC#1 attestation)

Both are "the bot consumed the input but didn't tell the farmer what
it did with it." Different mechanisms; same UX class. Worth thinking
about a general "what just happened?" reply policy as part of the
Phase 37 prompt sweep or as its own architectural pin.

## Recommended filings (do not auto-file yet -- Don Santiago wants to discuss)

1. **999.x: Phase 40 commit-failure farmer-facing reply (NORTH-STAR fix).**
   Owner: Don Santiago to scope. Estimate: 1-2 hour fix in commit-watchdog
   + system-prompt tune. Same-week candidate, not v1.8 scope.
2. **999.x: Phase 40 commit-router unregistered-target fallback.** Owner:
   Don Santiago to scope between options A/B/C/D above. v1.8 candidate.
3. **Phase 37 prompt-pin sweep (existing in deferred-items.md):** add LLM
   conflation cases like Rambo-as-block-name. Bundle with em-dash + OBJ-char
   fixes.
4. **mushdatadump-prod corpus addition:** capture this draft + caption +
   photo as a paper-trail fixture under `/mnt/mossrock/shared/mushdatadump-prod/2026-05-15_rambo_th_unscripted/`.
5. **Phase 40 LEARNINGS.md amendment:** add an "edge cases observed in
   prod" section noting observation_requires_target on non-fungi targets.
6. **v1.8 candidate file:** add "first-class non-fungi events on the
   Signal channel" as a v1.8 theme contender to
   `.planning/notes/2026-05-13-v1.8-candidates.md`.

## Memory entries to write (next turn or after discussion)

- `project_2026_05_15_vikki_rambo_unscripted_run` -- proof that v1.7
  stack worked end-to-end on a real unscripted event, hit one real schema
  gap (observation_requires_target), and was caught by NORTH-STAR review.
- `feedback_no_silent_failure_after_farmer_confirm` -- pin: any
  terminal state after a farmer YES MUST include a farmer-facing reply.
  Source: this incident.
- (Optional) `project_commit_failed_silence_findings` -- pointer to
  this note + the relevant Phase 40 code locations.

## Out-of-band actions taken this session

- Sent manual ack message to Vikki at 23:23:24Z explaining what
  happened (in Spanish, no em-dashes, farmer-flavored tone).
- Polling for Don Santiago's T+24h Plan 36-04 reply continuing in the
  background -- separate workflow, not blocked by this finding.

## What we deliberately did NOT do

- Did NOT manually commit Vikki's draft to farmOS as a workaround. The
  whole point is to see what the automated path does; manually fixing
  it would hide the failure-mode evidence.
- Did NOT update Phase 40 status from `passed` back to gaps_found in the
  v1.7 audit. This is a found-issue on a passed phase; it gets its own
  backlog filing, not a milestone re-open. Same pattern as v1.6 (shipped
  with deferred items).
- Did NOT file the 999.x backlog phases yet. Don Santiago wants to
  discuss the scope/severity tradeoffs.

EOF -- pick this up in the discussion session.
