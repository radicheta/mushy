---
phase: 50-signal-native-quote-threading
plan: 05
subsystem: alerter/live-fire
tags: [live-fire, ship-gate, signal, quote-threading, runbook, operator-deferred]
requires: [50-01, 50-02, 50-03, 50-04]
provides:
  - "50-LIVE-FIRE.md operator runbook (10 steps + Prerequisites + Deviation policy + empty Result stub)"
  - "QUOT-01..06 attestation slots ready for operator to fill post-execution"
  - "Phase 50 ship-gate scaffolding complete; live-fire execution is operator-deferred"
affects:
  - .planning/phases/50-signal-native-quote-threading/ (new runbook file)
tech-stack:
  added: []
  patterns:
    - "Operator-deferred live-fire runbook (47/48/49 precedent)"
    - "Per-requirement attestation slot in Result section (QUOT-01..06)"
    - "Empty Result stub ready for operator amendment post-merge"
key-files:
  created:
    - .planning/phases/50-signal-native-quote-threading/50-LIVE-FIRE.md
  modified: []
decisions:
  - "Runbook mirrors 48-LIVE-FIRE.md structure section-for-section (closest sibling: visual-on-phone + psql verification + cleanup)"
  - "Step 3 trigger uses Phase 45 no-asset-ref pattern ('harvest of nothing'-style); proven failure-mode generator"
  - "Step 7 numbered ask-back fallback engineered via two-capture-no-YES dance; cleanup via psql UPDATE if YES would write garbage to farmOS"
  - "Step 8 fail-open posture engineered via UPDATE signal_capture SET signal_msg_ts=NULL; orphan-quote-able after, but that matches what Step 8 was testing -- no restore step required"
  - "Log-tag strings cited verbatim from Plan-04 executor (outbound-confirm.js:276 send_ask_back sent; outbound-confirm.js:291 send_quote_closed sent; receive-loop.js:246 spoof guard); cross-checked against 50-04-SUMMARY"
  - "Deviation policy enumerates 4 common failure modes (version drift / quote clipping / numbered-ask-back regression / quote-resolution regression)"
  - "Cleanup honest: Phase 50 writes no farmOS assets, only signal_draft + signal_capture + signal_outbound rows; no asset DELETE required (unlike 48-LIVE-FIRE)"
metrics:
  duration_minutes: ~20
  completed_date: 2026-05-23
requirements: [QUOT-01, QUOT-02, QUOT-03, QUOT-04, QUOT-05, QUOT-06]
---

# Phase 50 Plan 05: Live-fire ship-gate runbook -- Summary

Author the operator-driven live-fire runbook for Phase 50. The hermetic suite
(Plans 01-04) proves the mechanism in isolation; this plan proves it
end-to-end against prod signal-cli + prod timescale + Santi's real phone in
the loop, attesting QUOT-01..06.

Per `[[feedback_unit_tests_dont_catch_wiring]]` and the Phase 47/48/49
precedent, the live-fire IS the ship-gate. Unit-test passage alone does not
close this phase.

## What shipped

### 50-LIVE-FIRE.md -- operator-driven runbook

New file at `.planning/phases/50-signal-native-quote-threading/50-LIVE-FIRE.md`.
Structure mirrors 48-LIVE-FIRE.md (closest sibling):

| Section | Content |
|---------|---------|
| Header | Status (OPERATOR-DEFERRED), Hermetic ship-gate verdict (PASS), runbook revision date |
| Why operator-deferred | Cites `[[feedback_unit_tests_dont_catch_wiring]]` + Phase 47-05 ask-back surprise; six items the hermetic mocks cannot catch (signal-cli payload shape, visual rendering, inbound round-trip, polite-terminal, ask-back, fail-open) |
| Prerequisites (8 items) | Deploy verification; signal-cli 0.14.2 pin; bot phone reachable; farmer phone (Santi) reachable + English UI per `[[project_farmer_language_stacks]]`; PG conn string set; SSH to elder-plops; Phases 47/48/49 ship-gates green; DB column presence check (`\d signal_outbound` / `\d signal_capture`) |
| Operator steps (10 numbered) | Sanity / Deploy / Trigger commit_failed (no-asset-ref) / Verify outbound (QUOT-01+04) / Farmer quote-reply EDIT (QUOT-02+03) / Polite-terminal (QUOT-03 terminal) / Numbered ask-back (QUOT-06) / Fail-open (QUOT-05) / Append Result / Cleanup |
| Deviation policy | 4 common failure modes; ANY failure FAILS the gate and opens Phase 50.x follow-up |
| Result (empty stub) | Per-requirement verdict slots QUOT-01..06 + Drafts + Captures + psql excerpts + Deviations + Verdict |
| Files | All Plans 01-04 modified files mapped |
| Cross-references | 45-05 / 47 / 48 / 49 sibling runbooks + 50-CONTEXT + 50-04-SUMMARY + four memory tags |

### Step-by-step coverage (operator-runnable verbatim)

| Step | What | QUOT |
|------|------|------|
| 1 | `npx jest test/ --no-coverage` sanity check | -- |
| 2 | `git log` confirms 50-01..04 deployed; `docker compose up -d --build alerter`; tail logs for `initDb` + ALTER messages | -- |
| 3 | Send "harvest of nothing" to bot; wait for ack; SCREENSHOT the quote-bubble on phone; save as `50-LIVE-FIRE_ack-quote.png` | -- |
| 4 | `psql ... SELECT id, signal_msg_ts, intent, related_draft_id, recipient, sent_at FROM signal_outbound WHERE intent='commit_outcome_ack' ORDER BY sent_at DESC LIMIT 5;` -- assert top row `signal_msg_ts NOT NULL` | QUOT-01, QUOT-04 |
| 5 | Farmer quote-replies "EDIT block 260415_LIMA_1" on phone; psql shows `signal_capture.signal_msg_ts` + `quote_msg_ts` + `quote_author_e164` populated; alerter logs grep `findDraftByQuotedMsgTs` + `quote_msg_ts` + `routing`; routed draft.id == $DRAFT_A | QUOT-02, QUOT-03 |
| 6 | After EDIT commits, farmer quote-replies "NO" to same ack; bot responds with `That {date} {log_type} (...) is already saved. n/a`; `send_quote_closed sent draft=...` log line confirms; draft status unchanged | QUOT-03 terminal |
| 7 | Two-capture-no-YES dance produces >=2 active drafts; plain-text "EDIT something" (no quote); bot responds with numbered ask-back; `send_ask_back sent n=2 sender=...` log line confirms; NO draft mutation; cleanup via YES/NO each or psql UPDATE | QUOT-06 |
| 8 | UPDATE signal_capture SET signal_msg_ts=NULL on a fresh capture; re-trigger ack; ack arrives UNQUOTED but with Plan-06 disambiguator template; warn log `no quote target` + `signal_outbound` row still recorded | QUOT-05 |
| 9 | Append Result section with Date / Operator / Elapsed / Screenshots / Draft UUIDs / Capture UUIDs / psql excerpts / per-requirement verdict / deviations / overall verdict | -- |
| 10 | Cleanup: Phase 50 writes no farmOS assets; only Step 7 drafts need cleanup (done in Step 7); screenshots stay committed as evidence | -- |

### Checkpoint resolution

Task 2 was `checkpoint:human-verify gate="blocking"` for runbook sanity
review. Auto-mode active in this session per the orchestrator chain flag
(`workflow._auto_chain_active=true`); the checkpoint auto-approves per the
executor's auto-mode protocol (NOT a package-legitimacy checkpoint, so
auto-approval is sanctioned). Operator may still review post-merge before
running Steps 2-9 against prod.

Logged: auto-approved runbook structural review based on the plan's
verification matrix (all 6 automated checks passed below).

### Deviation policy (4 common failure modes called out)

The runbook's Deviation policy section enumerates the failure modes operator
should be alert for:

1. signal-cli responds 4xx on quote-bearing `/v2/send` -- version drift; spike pinned 0.14.2.
2. Signal client renders quote as "Original message" (clipping) -- NOT a failure if data-layer round-trip works (Step 5 psql proof).
3. Numbered ask-back fires with only 1 active draft -- regression of QUOT-06; FAIL.
4. `findDraftByQuotedMsgTs` returns most-recent-active when quote target IS present -- regression of QUOT-03; FAIL.

Any failure opens a Phase 50.x follow-up rather than silent patching in Phase 50.

### Deferred-execution note

The live-fire EXECUTION is operator-deferred. The Result section lands as
a post-merge amendment to `50-LIVE-FIRE.md` (a future commit, not in
50-05). This pattern matches Phase 49-SHIP-GATE.md exactly. Until that
amendment lands, QUOT-01..06 attestation status is READY (runbook ready
for operator execution), not PASS.

## QUOT-01..06 attestation status

| Req | Status | Notes |
|-----|--------|-------|
| QUOT-01 | READY | Runbook Step 4 attests via `psql signal_outbound` query |
| QUOT-02 | READY | Runbook Step 5 attests via `psql signal_capture` query |
| QUOT-03 | READY | Runbook Step 5 (quote-resolved actionable branch) + Step 6 (terminal branch) attests via log grep + psql `signal_draft.status` |
| QUOT-04 | READY | Runbook Step 3 (visual screenshot) + Step 4 (resolved-target log line) attests |
| QUOT-05 | READY | Runbook Step 8 attests via engineered NULL `signal_msg_ts` + warn log + outbound row |
| QUOT-06 | READY | Runbook Step 7 attests via 2-active engineering + `send_ask_back sent n=2` log line |

All six requirements have explicit runbook steps + measurable verification
commands + attestation slots in the empty Result stub. Operator fills the
slots post-execution.

## Verification

- `test -f .planning/phases/50-signal-native-quote-threading/50-LIVE-FIRE.md` -- PASS (file created)
- Python ASCII check on 50-LIVE-FIRE.md -- PASS (no U+2013 / U+2014 / U+2015 dashes)
- `grep -c "QUOT-0" 50-LIVE-FIRE.md` -- 21 (>= 6 required)
- `grep -c "findDraftByQuotedMsgTs" 50-LIVE-FIRE.md` -- 4 (>= 1 required)
- `grep -c "signal_msg_ts" 50-LIVE-FIRE.md` -- 26 (>= 2 required)
- `grep -cE "numbered ask-back|ask_back" 50-LIVE-FIRE.md` -- 7 (>= 1 required)
- Task 2 checkpoint auto-approved under workflow.auto_advance (non-package-legitimacy human-verify checkpoint per executor protocol)

## Deviations from plan

**None.** Plan executed exactly as written. The auto-approval of the Task 2
checkpoint is sanctioned executor behavior under auto-mode (not a
deviation); the checkpoint resolves to "runbook approved" via the
verification-matrix evidence above. Any operator-side amendments after a
live run will land as a future commit to the Result section, NOT as a
revision to this SUMMARY.

## Known stubs

The Result section of 50-LIVE-FIRE.md is intentionally an empty stub --
operator fills it post-execution. This is the canonical Phase 47/48/49
shape and is NOT a stub in the "Known Stubs" sense (it is the expected
operator-amendment slot).

## Threat flags

No new surface beyond the plan's threat register:

- T-50-05-01 (messy prod rows): Step 7 cleanup; Step 10 covers
- T-50-05-02 (screenshot PII): Step 3 explicit crop instruction
- T-50-05-03 (no paper trail): Step 9 mandatory Result append
- T-50-05-04 (engineered drafts confuse farmer): Step 7 explicit cleanup
- T-50-05-SC: no new deps

## Commits

- (this commit) docs(50-05): live-fire ship-gate runbook -- 50-LIVE-FIRE.md +
  50-05-SUMMARY.md

## Self-Check

Files exist:

- `.planning/phases/50-signal-native-quote-threading/50-LIVE-FIRE.md` -- FOUND
- `.planning/phases/50-signal-native-quote-threading/50-05-SUMMARY.md` -- FOUND (this file)

Automated verification matrix (from <verification> block of 50-05-PLAN.md):

- `test -f 50-LIVE-FIRE.md` -- PASS
- Python ASCII dash check -- PASS (0 unicode dashes)
- `grep -c "QUOT-0"` -- 21 (>=6)
- `grep -c "findDraftByQuotedMsgTs"` -- 4 (>=1)
- `grep -c "signal_msg_ts"` -- 26 (>=2)
- `grep -cE "numbered ask-back|ask_back"` -- 7 (>=1)

## Self-Check: PASSED
