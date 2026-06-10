---
phase: 55B-fidelity-corpus-unblock
plan: 04
type: execute
wave: 3
depends_on: ["55B-02", "55B-03"]
files_modified:
  - .planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-RE-SMOKE-RUNBOOK.md
autonomous: false
requirements: [SMOKE-01, SESSION-03]
must_haves:
  truths:
    - "A 5-page re-smoke against an isolated dev DB exercises all three failure modes plus the no-CSV case"
    - "IMG_3776 POY entries are HELD (not committed as KOY) -- the mode-2 silent-misattribution regression guard"
    - "Held drafts are visibly absent from the session group's member list when reconciled against the attached page image"
    - "The re-smoke is a GATE before the parked full-corpus run; it does NOT trigger the full run (Phase 55 / GA2 owns that)"
  artifacts:
    - path: ".planning/phases/55B-*/55B-RE-SMOKE-RUNBOOK.md"
      provides: "GA1-isolated 5-page re-smoke procedure + pass criteria + operator query snippets"
      contains: "IMG_3776"
  key_links:
    - from: "re-smoke runbook"
      to: ".planning/phases/55-full-corpus-run-receipt/55-FULL-CORPUS-RUNBOOK.md"
      via: "GA1 isolation pre-flight reuse"
      pattern: "GA1"
---

<objective>
Author the GA1-isolated 5-page re-smoke runbook and execute it as the phase gate: prove
the fidelity gate + session surface behave on real paid extraction before the parked
full-2025-corpus run is unblocked. This is the SMOKE-01 gate -- preparation, not the full
run (Phase 55 + GA2 still own promotion).

Purpose: Hermetic tests prove the seams; the re-smoke is the live ship-gate
([[feedback_unit_tests_dont_catch_wiring]]). The 5-page set (IMG_3775/3776/3778/3782/3777)
exercises all three failure modes from the 2026-06-07 audit plus the no-CSV "hold all"
path. IMG_3776 (POY->KOY) is the mode-2 regression guard.
Output: 55B-RE-SMOKE-RUNBOOK.md + an attested run result (held counts, session assets,
page images, F2 member-gap check) recorded for the GA2 promotion decision.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-CONTEXT.md
@.planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-RESEARCH.md
@.planning/phases/55-full-corpus-run-receipt/55-FULL-CORPUS-RUNBOOK.md
@.planning/phases/55-full-corpus-run-receipt/55-PROMOTION-DECISION.md

<interfaces>
From 55B-RESEARCH.md Pattern 7 (re-smoke spec):
- Selection: `--limit=5 --resume-from=IMG_3775.jpg` reproducibly selects
  IMG_3775 (02-01, mode 1: LIMA->LIM / POY->OYS), IMG_3776 (02-04, mode 2: POY->KOY),
  IMG_3778 (02-20, mode 1: CAZ->CAR), IMG_3782 (04-06, mode 3: 4 SHI under-capture),
  IMG_3777 (no CSV, mode 0: hold-all).
- GA1 isolation: Option A throwaway postgres :5433 (default); 4 pre-flight assertions
  (dev :18080 reachable, FARMOS_URL clean/non-prod, ANTHROPIC_API_KEY set, Jest green).
- Pass criteria: IMG_3776 POY entries held with reason 'fidelity_cross_check_unverified'
  (NOT committed as KOY); IMG_3775 7 held (LIMA x4 + POY x3) / 17 hits committed;
  IMG_3777 all held 'fidelity_cross_check_no_csv'; session group asset per page with the
  page image attached; receipt held count > 0 with fidelity_cross_check_* reasons.
- Operator held-draft query (RESEARCH Pattern 5):
  SELECT id, log_type, needs_review_reason, draft_json FROM signal_draft
  WHERE status='needs_review' AND needs_review_reason LIKE 'fidelity_cross_check%'
  AND draft_json->>'event_date' = '<page-date>';

Scope fence: this runbook PREPARES and GATES; it must NOT instruct running the full
corpus (Phase 55 owns that, GA2-gated). Prod write stays opt-in (BACK-11 default dev-only).
The harness prod-guard already refuses ':8082'/'prod'.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Author 55B-RE-SMOKE-RUNBOOK.md</name>
  <files>.planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-RE-SMOKE-RUNBOOK.md</files>
  <read_first>
    - .planning/phases/55-full-corpus-run-receipt/55-FULL-CORPUS-RUNBOOK.md (the GA1 isolation pre-flight + smoke-before-full discipline to reuse verbatim where possible)
    - .planning/phases/55-full-corpus-run-receipt/55-PROMOTION-DECISION.md (dev-only default / prod opt-in BACK-11 -- the scope fence)
    - .planning/phases/55B-*/55B-RESEARCH.md (Pattern 7: smoke set selection + pass criteria + operator query)
    - .planning/phases/55B-*/55B-CONTEXT.md (Out-of-scope: do NOT author the full run)
  </read_first>
  <action>
    Write 55B-RE-SMOKE-RUNBOOK.md reusing the GA1 isolation pre-flight from
    55-FULL-CORPUS-RUNBOOK.md (Option A throwaway postgres :5433 + the 4 pre-flight
    assertions). Document the exact invocation `--limit=5 --resume-from=IMG_3775.jpg`
    with `--bulk-backfill --farmer santi` against dev :18080 (NEVER :8082). Enumerate
    per-page PASS criteria from RESEARCH Pattern 7 (IMG_3776 POY held not KOY; IMG_3775
    7 held / 17 hits; IMG_3777 all held no_csv; session group asset + page image per page).
    Include the operator held-draft SQL query snippet and an F2 reconcile step (open each
    session group asset in farmOS, view the attached page image, confirm held blocks are
    ABSENT from members). State the scope fence explicitly: this is a GATE before the
    parked full run; the full corpus run remains Phase-55/GA2-owned and is NOT triggered
    here. No em-dashes in any farmer-facing lines (project rule); ASCII only.
  </action>
  <verify>
    <automated>RB=.planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-RE-SMOKE-RUNBOOK.md; test -f "$RB" && grep -q "IMG_3776" "$RB" && grep -q "fidelity_cross_check" "$RB" && grep -q "5433" "$RB" && echo OK</automated>
  </verify>
  <acceptance_criteria>
    - 55B-RE-SMOKE-RUNBOOK.md exists; mentions IMG_3776, fidelity_cross_check, and the
      :5433 isolated DB.
    - Per-page PASS criteria + operator held-draft SQL + F2 reconcile step present.
    - The scope fence (no full-corpus run; GA2/Phase 55 owns promotion) is explicit.
    - No em-dash characters in the file.
  </acceptance_criteria>
  <done>Re-smoke runbook authored with GA1 isolation, 5-page set, pass criteria, F2 reconcile, and scope fence.</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 2: Execute 5-page GA1-isolated re-smoke (live gate)</name>
  <action>Operator executes the 5-page GA1-isolated re-smoke per 55B-RE-SMOKE-RUNBOOK.md (how-to-verify below) and records the attested result in 55B-RE-SMOKE.md; the IMG_3776 POY-held-not-KOY check is the hard pass/fail gate.</action>
  <what-built>
    The fidelity gate (Plan 02) + session routing + page-image attach (Plan 03), now
    exercised by a real 5-page paid extraction against an isolated dev farmOS :18080 per
    55B-RE-SMOKE-RUNBOOK.md. This is the live ship-gate for the parked full-corpus run.
  </what-built>
  <how-to-verify>
    Follow 55B-RE-SMOKE-RUNBOOK.md against an isolated dev DB (Option A :5433) and dev
    farmOS :18080 (NEVER :8082):
    1. Run `--limit=5 --resume-from=IMG_3775.jpg --bulk-backfill --farmer santi`.
    2. IMG_3776: confirm the POY entries are HELD with reason 'fidelity_cross_check_unverified'
       and were NOT committed as KOY (the mode-2 regression guard). This is the hard pass/fail.
    3. IMG_3775: ~7 held (LIMA x4 + POY x3), ~17 hits committed.
    4. IMG_3777: ALL held with 'fidelity_cross_check_no_csv'.
    5. Open each session group asset in farmOS: confirm 1..N page image(s) attached and that
       held blocks are ABSENT from the member list (F2 reconcile / SESSION-03).
    6. Run the operator held-draft SQL query; confirm held counts > 0 with fidelity_cross_check_* reasons.
    Record the full result (per-page held/hit counts, session asset ids + names, image-attach
    success, F2 gap confirmation) in `.planning/phases/55B-*/55B-RE-SMOKE.md`.
    PASS = IMG_3776 POY held (not KOY) AND session images attached AND held blocks absent
    from members. FAIL = any POY-as-KOY commit, missing image, or held block appearing as a member.
  </how-to-verify>
  <resume-signal>Type "re-smoke PASS" (with the recorded 55B-RE-SMOKE.md) or paste the failing page + observed behavior</resume-signal>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| operator harness -> dev farmOS :18080 | paid extraction + writes to an isolated dev instance; prod (:8082) explicitly excluded by harness guard |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-55B-09 | Tampering | re-smoke accidentally targets prod farmOS :8082 | mitigate | harness prod-guard refuses ':8082'/'prod' (Phase 54-01); runbook pre-flight asserts FARMOS_URL is :18080 |
| T-55B-10 | Information disclosure | paid run writes test assets into a shared dev DB | mitigate | GA1 Option A throwaway postgres :5433 isolation; teardown after attestation |
| T-55B-SC | Tampering | npm installs | mitigate | zero new packages this phase; no install task |
</threat_model>

<verification>
- 55B-RE-SMOKE-RUNBOOK.md authored (Task 1 automated check green).
- Re-smoke executed; 55B-RE-SMOKE.md records the attested result.
- Checkpoint resumed only on "re-smoke PASS" with IMG_3776 POY held (not KOY), images
  attached, held blocks absent from members.
</verification>

<success_criteria>
- SMOKE-01: 5-page re-smoke green against isolated dev; receipt shows held entries for IMG_3776.
- SESSION-03 (live confirmation): held drafts are visibly absent from session members against
  the attached page image (F2 reconcile works end to end).
- Phase 55B gate satisfied; the parked full-corpus run is unblocked for the separate
  Phase-55/GA2 promotion decision (NOT triggered here).
</success_criteria>

<output>
Create `.planning/phases/55B-tbd-if-needed-per-tenant-backfill-story-observation-of-unkno/55B-04-SUMMARY.md` when done.
Record the re-smoke in `.planning/phases/55B-*/55B-RE-SMOKE.md`.
</output>
