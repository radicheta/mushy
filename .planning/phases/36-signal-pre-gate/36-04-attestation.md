---
phase: 36-signal-pre-gate
plan: 04
status: SC1-PASS-T0-and-Tplus24; SC2-deferred-Vikki; SC3-PASS
last_updated_utc: 2026-05-15T23:30:00Z
verdict: PASS-with-SC2-carryover -- SC1 attested twice (T0 + T+38h), SC3 attested 2026-05-13, SC2 deferred (Vikki SC#2 acceptable per plan resume-signal "T0 partial: farmer1 only")
---

# Plan 36-04 -- Live Round-Trip Attestation (T0 + Rebuild)

T+24h re-run still pending (2026-05-14 ~22:34 UTC); farmer #2 (Vikki)
deferred to T+24h window because she was mid-confirm on a real squash
harvest draft at T0 send time.

## T0 Round-Trip

| Farmer | Kickoff send_ts | Reply ts | Reply text | Bot ack send_ts | Latency (reply - kickoff) |
|--------|-----------------|----------|------------|-----------------|---------------------------|
| santi (farmer #1) | 2026-05-13T22:34:23Z | 2026-05-13T22:34:49.530Z | `ok` (inferred from `signal_draft_event.event='yes'`; receive-loop short-circuit prevents capture-table persistence -- see Notes) | 2026-05-13T22:36:48Z | **26.5s** |
| vikki (farmer #2) | DEFERRED | -- | -- | -- | -- |

Evidence:
- `.planning/phases/36-signal-pre-gate/snapshots/kickoff-sends-20260513.json` (kickoff payload + signal-cli timestamp 1778711666557)
- `signal_draft_event` table, draft_id=`946a7b...`, seq=2 event=`yes` at 22:34:49.530 (the ok reply that the receive-loop consumed and routed to Phase 39 confirm flow; the same ok satisfies SC#1)
- Bot ack signal-cli timestamp 1778711812017 (return-leg proof; farmer received "got you -- round-trip works...")

## Post-Rebuild Attestation (SC#3)

Rebuild driven by Phase 40 deploy unblock (alerter image predated Phase
39/40 merges); doubles as SC#3 evidence. The rebuild happened BEFORE the
farmer round-trip rather than during the verification window, but the
trust-check is verdict-`ok` and the farmer round-trip immediately
afterward proves trust survived intact.

| Field | Value |
|-------|-------|
| Rebuild at | 2026-05-13T22:32:28Z |
| Image pre | f4cad852d88c (built 2026-05-12 20:58) |
| Image post | 0ab5ca7d42cb (built 2026-05-13 22:25) |
| Healthcheck status | healthy |
| `post-rebuild-trust-check.sh` verdict | **ok** |
| Trust-check exit code | **0** |
| Recipients checked | 3 |
| Bot fingerprint pre/post | **match** (`05 d1 a5 89 50 7c ec 3e 1a 47 96 92 7a 4...`) |
| Post-rebuild farmer ping | satisfied by kickoff at 22:34:23 + reply at 22:34:49 (2 min after rebuild) |

Full JSON: `.planning/phases/36-signal-pre-gate/snapshots/rebuild-attestation-20260513.json`

## T+24h Re-Run

Fired 2026-05-15 (T+~38h from T0 -- past the ≥20h D-13 floor; still
meaningful for background-drift detection). Window slipped because the
2026-05-14 audit session didn't run; closed in the 2026-05-15 session
during v1.7 re-audit + recommended-order action queue.

| Farmer | Kickoff send_ts | Reply ts | Reply text | Bot ack send_ts | Latency (reply - kickoff) |
|--------|-----------------|----------|------------|-----------------|---------------------------|
| santi (farmer #1) | 2026-05-15T23:15:34Z (signal-cli ts 1778886932248) | 2026-05-15T23:28:20.563Z | `Ok` (capture id `01KRPZGC2KD6GGKR6EQMH9X3ZW`) | 2026-05-15T23:29:26Z (signal-cli ts 1778887764910) | **12m 46s** |
| vikki (farmer #2) | DEFERRED to a quieter window (live event in flight at T+24h fire time -- her Rambo draft `b8a1e586...` was mid-pipeline) | -- | -- | -- | -- |

Evidence:
- `.planning/phases/36-signal-pre-gate/snapshots/receive-Tplus24-f1-20260515.json` (redacted capture record from `signal_capture` table)
- Bot ack /v2/send timestamp 1778887764910 captured in `/tmp/santi-ack.json` during session

## Verdict (final, pending Vikki SC#2)

- [x] **SC#1 PASS x2** -- farmer #1 T0 + T+~38h both attested (26.5s + 12m46s latency); no trust drift detected across 38h gap
- [ ] **SC#2 carryover** -- farmer #2 SC#2 deferred per plan resume-signal escape hatch ("T0 partial: farmer1 only" acceptable per D-12 since farmer #2 is dev-side-flexible). Don Santiago can choose to close later via fresh kickoff in a quieter Vikki window.
- [x] **SC#3 PASS** -- alerter rebuild did not break trust (verdict=ok, fingerprint match, 2026-05-13)

Phase 36 ship-gate flip: **PARTIAL -> PASS-with-SC2-carryover**. Mirrors v1.6/v1.5 audit pattern (ship with named deferred items). Plan 36-04 considered closed for v1.7 milestone gating purposes; SC#2 attestation can be added retroactively without re-opening the plan.

## Notes / Anomalies

1. **Phase 39 `ok` confirm absorbs Plan 36-04 attestation replies**. The
   receive-loop interprets a farmer's "ok" as a YES vote for their most
   recent `awaiting_farmer` draft, NOT as a standalone Plan 36-04 ack.
   Don Santiago's "ok" at 22:34:49 was matched to the thumbs-up
   observation draft (`946a7b...`) that the Phase 39 confirm-watchdog
   had just nudged. The same `ok` simultaneously:
   - satisfies Plan 36-04 SC#1 (Signal round-trip works)
   - triggers Phase 39 confirm flow (draft -> confirmed)
   - triggers Phase 40 commit-watchdog (commit attempt 1/3)
   - is rejected by commit-router as `observation_requires_target`

   Trace evidence in `signal_draft_event` for draft `946a7b...` (8 rows
   covering nudge_sent -> yes -> commit_attempt x3 -> commit_failed).

2. **Receive-loop short-circuit means `signal_capture` is empty for
   confirm-verb replies.** A standalone Plan 36-04 attestation would
   need to either (a) park the farmer's pending drafts before sending
   the kickoff, (b) match a different verb than `ok/yes` for the SC#1
   reply (e.g. `SC1 ack`), or (c) read the attestation evidence from
   `signal_draft_event` as we did here. We took option (c) for this
   round; future plans should consider (b) if SC#1 attestation needs
   to be cleanly orthogonal to draft confirms.

3. **Phase 40 commit pipe was end-to-end exercised by accident.** The
   junk thumbs-up draft drove a full commit_attempt -> retry -> failed
   cycle pointed at dev-farmOS (`:18080`). Validator caught the schema
   violation correctly. Not a happy-path ship-gate commit, but useful
   evidence that the path is wired and the validator is awake. Real
   happy-path commit evidence still pending (Vikki's squash or a fresh
   clean test message).

4. **Image-staleness gap.** The alerter image at T0 minus 7 minutes
   predated all Phase 39 + Phase 40 code. Captured in memory
   `project_2026_05_13_phase39_40_silent_downtime`. Compose-env-passthrough
   memory was insufficient to catch this -- the override.yml change AND
   the merged feature code both required a `--build` that hadn't run.

5. **NEW 2026-05-15: Phase 37 LLM has no memory of outbound kickoff context.**
   The T+24h kickoff at 23:15:34Z asked Santi to reply "ok". His "Ok"
   capture at 23:28:20Z routed to the conversational LLM path (no
   pending draft to absorb it via receive-loop short-circuit). The LLM
   then replied (em-dashes preserved verbatim for forensic accuracy):
   "Is this message confirming a specific session — inoculation,
   harvest, or chamber check — so I can log it correctly?" -- not
   realizing it had asked the question 12m46s earlier. Conversation
   state is one-turn; the bot has no outbound-message recall. Filing as
   v1.8/999.x candidate: outbound-context-aware LLM replies (track recent
   bot-sent messages in the system-prompt context window).

6. **NEW 2026-05-15: live em-dash leak.** Same LLM reply contained two
   em-dashes (codepoint `—`). Existing Phase 37 deferred-items.md
   style-pin finding now has a second live example beyond the
   2026-05-11 occurrence. Confirms the em-dash issue is *recurrent*,
   not a one-time prompt slip. Strengthens the case for the prompt-pin
   sweep recommended in v1.7 audit.
