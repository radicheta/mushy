---
phase: 36-signal-pre-gate
plan: 04
status: partial-T0-green-T+24h-pending
last_updated_utc: 2026-05-13T22:37:00Z
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

DEFERRED. Schedule: 2026-05-14 ~22:34 UTC (≥20h after T0). Will send a
fresh kickoff to both farmers and capture the same evidence shape as T0.

Rationale: T+24h tests background drift (D-13); requires real wall-clock
gap. Farmer #2 (Vikki) leg also picked up in this window per the plan's
"T0 partial: farmer1 only" gate-pass clause.

## Verdict (interim)

- [x] **SC#1 PASS** -- farmer #1 round-trip captured (kickoff -> reply -> ack); see T0 row above
- [ ] **SC#2 PENDING** -- farmer #2 round-trip; deferred to T+24h window
- [x] **SC#3 PASS** -- alerter rebuild did not break trust (verdict=ok, fingerprint match)

Phase 36 ship-gate can flip from PARTIAL to PASS once SC#2 is attested at T+24h.

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
