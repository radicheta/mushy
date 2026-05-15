---
phase: 42-shi-pilot
extracted: 2026-05-13
status: SCAFFOLDED -- calendar-deferred 4-8 weeks (sterilize -> inoc -> colonize -> cold_shock -> fruiting -> bag -> archive_spent)
---

# Phase 42 Learnings -- SHI-on-Sawdust Pilot

**Note:** This phase is scaffold-only. The actual pilot runs on real biological time and re-enters `/gsd-verify-work 42` at archive_spent. LEARNINGS will be revised post-pilot. Below is what was learned *building the scaffold and tools*.

## Decisions made

- **D-01 / D-01a / D-01b:** Pilot is operator-executed against real mushrooms; no "run pilot" command exists. Phase 42 delivers RUNBOOK + PILOT-LOG + verification tools, not automation. Dev-farmOS only (`:18080`) for the pilot; prod-flip deferred per Phase 40 D-04a.
- **D-03 / D-03a / D-03b:** Three query-only JS tools shipped: `farmos-current-stage.js`, `farmos-lineage.js`, `farmos-pilot-reconstruct.js`. All reuse Phase 40 `client.js` (no new HTTP code). Query-only by design -- safe to spot-check repeatedly during the pilot.
- **D-04 / D-04a / D-04b:** Three documents own the pilot artifact set: RUNBOOK (operator playbook), PILOT-LOG (running journal, append-only one section per event), VERIFICATION (final ship-gate, generated semi-manually post-pilot).
- **D-05 / D-05a / D-05b:** Autonomous run delivers scaffolding only. Verification status at end = `human_needed` with explicit re-entry instruction.
- **D-06 / D-06a:** No CI tests for the lifecycle itself (every criterion needs real farm-side reality). Dry-run mode rehearses RUNBOOK against Phase 41 synthetic fixtures -- catches RUNBOOK ambiguities before they cost a real inoc cycle.

## Lessons learned

(Pre-pilot scaffolding only; pilot-execution lessons captured post-archive_spent.)

- **23 / 23 Jest PASS on the 3 query tools.** Tools-as-code-paid-for-themselves: even before the pilot starts, the alerter team gets reusable read-side primitives (current-stage derivation, lineage walk, pilot-reconstruct) that are useful for any future audit query.
- **RUNBOOK style locks honored** (no em-dashes, fmtNum, named address). Operator reads this -- it counts as a farmer-facing surface in spirit.
- **`farmos_asset_link` fallback in Phase 40 D-04a was the right call.** Phase 42 inherits the live "asset_link absent, use farm_id_tag filter" path. Without the fallback, pilot would be blocked on the module install.

## Patterns worth reusing

- **Phase-as-scaffold-plus-real-world-wait.** Phase 42 is the template for any milestone phase that genuinely depends on calendar time. Ship scaffolding + tools + docs in autonomous run; mark `human_needed` with re-entry instruction; archive the milestone with the gap noted.
- **Query-only tools alongside write-path code.** Phase 40 wrote; Phase 42 reads. Same client, different verbs. Tools shipped here are reusable beyond the pilot.
- **Dry-run rehearsal via Phase 41 synthetic corpus.** Catches RUNBOOK ambiguities before real biological time is spent.
- **PILOT-LOG = append-only paper trail.** One section per event committed atomically. Honors `feedback_keep_paper_trail_of_intermediates` for the pilot's lifecycle.

## Surprises

- None at scaffold time. The phase planned out cleanly precisely because it's mostly write-the-RUNBOOK + extract-three-tools-from-Phase-40-client.

## Open threads

- **PILOT-01 (sterilization batch)** -- can fire as soon as Phase 40 dev-farmOS taxonomy is seeded (Backlog B operator action).
- **PILOT-02 (inoculation event with QR)** -- can fire immediately after PILOT-01.
- **PILOT-03 (colonize/cold_shock/fruiting transitions)** -- 4-8 weeks real-world.
- **PILOT-04 / 05 / 06 (bagging / archive_spent / end-to-end reconstruct)** -- contingent on PILOT-03 completion.
- **Re-entry:** `/gsd-verify-work 42` once lifecycle completes.
