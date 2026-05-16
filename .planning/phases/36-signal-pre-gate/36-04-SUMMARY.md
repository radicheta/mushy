---
phase: 36-signal-pre-gate
plan: 04
status: complete
completed_utc: 2026-05-15
verdict: PASS-with-SC2-carryover
---

# Plan 36-04 — Live Round-Trip Attestation (T0 + Rebuild) — SUMMARY

## What shipped

Live evidence that the farmer↔bot Signal round-trip works end-to-end and survives an alerter container rebuild without trust drift. SC#1 attested twice (T0 + T+38h) for farmer #1; SC#3 attested via the Phase 40 deploy rebuild; SC#2 (farmer #2 round-trip) deferred per plan resume-signal escape hatch.

## Concrete outputs

| Path | Purpose |
|------|---------|
| `.planning/phases/36-signal-pre-gate/36-04-attestation.md` | Full attestation log (T0 + T+38h + rebuild + notes/anomalies) |
| `.planning/phases/36-signal-pre-gate/snapshots/kickoff-sends-20260513.json` | T0 kickoff payload + signal-cli timestamp `1778711666557` |
| `.planning/phases/36-signal-pre-gate/snapshots/rebuild-attestation-20260513.json` | Pre/post fingerprint + healthcheck verdict for the 22:32:28Z rebuild |
| `.planning/phases/36-signal-pre-gate/snapshots/receive-Tplus24-f1-20260515.json` | T+~38h capture row for farmer #1's `Ok` reply |

## Verdict matrix

| SC | Status | Evidence |
|----|--------|----------|
| SC#1 (round-trip works) | **PASS ×2** for farmer #1 | T0 26.5s latency (2026-05-13); T+~38h 12m46s latency (2026-05-15). Both reply→ack pairs captured with signal-cli timestamps. |
| SC#2 (farmer #2 round-trip) | **carryover** | Vikki deferred at both T0 (mid Rambo draft `b8a1e586...`) and T+24h fire (live event in flight). Plan resume-signal "T0 partial: farmer1 only" acceptable per D-12. |
| SC#3 (rebuild does not break trust) | **PASS** | Image swap f4cad852 → 0ab5ca7d (2026-05-13 22:32:28Z); `post-rebuild-trust-check.sh` verdict=`ok`, exit=0, fingerprint match, container healthy. Farmer round-trip 2 min after rebuild succeeded. |

## Key observations

- **Latency envelope:** 26.5s (T0, immediate reply) → 12m46s (T+38h, asynchronous farmer attention). Both well within "Signal is alive" interpretation; the T+38h gap is normal farmer behaviour, not a system delay.
- **SC#3 evidence came opportunistically.** The rebuild was driven by Phase 40 deploy unblock (alerter image predated Phase 39/40 merges per memory `project_2026_05_13_phase39_40_silent_downtime`) rather than being staged as a Plan 36-04 step. Doubles correctly as SC#3 evidence: trust-check verdict was `ok` and the farmer round-trip 2 min later proved trust survived intact.
- **Phase 36 ship-gate:** PARTIAL → PASS-with-SC2-carryover. Mirrors v1.6/v1.5 audit pattern (ship with named deferred items).

## Plan deviations

1. **`signal_capture` table is empty for confirm-verb replies.** Receive-loop short-circuits `ok`/`yes` into the Phase 39 confirm flow before `signal_capture` is written, so SC#1 evidence at T0 came from `signal_draft_event` (draft `946a7b...`, 8 rows) instead of the originally-imagined `signal_capture` row. Future plans needing clean orthogonality should use a non-confirm verb (e.g. `SC1 ack`) for the kickoff.
2. **T+24h slipped to T+~38h.** 2026-05-14 audit session didn't run; closed in 2026-05-15 session during v1.7 re-audit. Still past the ≥20h D-13 floor.
3. **Rebuild attested BEFORE round-trip, not during.** Plan envisioned a deliberate mid-window rebuild; reality was rebuild-then-round-trip, which is strictly weaker as a stress test but verdict-equivalent for SC#3 since both pre/post-rebuild trust state and a working farmer reply were captured.

## New findings filed during this plan

Four anomalies surfaced and were captured for downstream phases (see `36-04-attestation.md` §Notes):

1. **Phase 39 `ok` absorbs SC#1 replies.** The same `ok` simultaneously satisfied SC#1, triggered Phase 39 confirm, drove Phase 40 commit_attempt ×3, and was rejected by commit-router as `observation_requires_target`. Surfaces the no-target-rejection issue (see `2026-05-16-farmos-no-target-and-strain-coverage.md` Part 1).
2. **Receive-loop short-circuit hides confirm-verb attestation in standard tables** (deviation 1 above).
3. **Phase 40 pipe exercised end-to-end by accident.** Junk thumbs-up draft drove the full commit_attempt → retry → failed cycle against dev-farmOS. Validator awake; happy-path commit evidence still owed (later satisfied 2026-05-15 by lion's mane bridge — `a1705ac`).
4. **Phase 37 LLM has no outbound-context recall.** T+~38h kickoff asked Santi to reply "ok"; LLM then asked the same question 12m46s later, not knowing it had already asked. Filed as v1.7 finding 1b — see `2026-05-17-llm-outbound-amnesia.md` (decision: bundle with finding 7 event-gate as v1.8 phase per memory `[[2026-05-17-findings-discussion-decisions]]`).
5. **Live em-dash leak in LLM reply** (two `—` codepoints). Second occurrence after 2026-05-11; later fixed in commit `3c7c723` (em-dash sanitize + iOS OBJ-char strip).

## Verification

- T0 round-trip: kickoff signal-cli ts `1778711666557` → reply ts `1778711689530` (Δ 26.5s) → bot ack ts `1778711812017`
- T+38h round-trip: kickoff `1778886932248` → reply 23:28:20.563Z → bot ack `1778887764910` (Δ 12m46s)
- Rebuild trust-check: verdict=`ok`, exit=0, recipients_checked=3, fingerprint match (`05 d1 a5 89 50 7c ec 3e 1a 47 96 92 7a 4...`)

## What's next

- SC#2 attestation for farmer #2 (Vikki) can be closed retroactively in any quieter window without re-opening the plan.
- Findings 1b and 7 are scheduled as a bundled v1.8 phase (event-gate + durable `signal_outbound` table) per memory `[[2026-05-17-findings-discussion-decisions]]`.
- Phase 36 ship-gate now PASS-with-SC2-carryover; phase considered closed for v1.7 milestone gating.
