---
phase: 42-shi-pilot
status: deprecated
verified_at: never
deprecated_at: 2026-08-21
---

# Phase 42 Verification

**Phase status: DEPRECATED 2026-08-21. The pilot never ran and will not run.**

`42-PILOT-LOG.md` has a single commit -- the scaffold -- and every field in it
still reads `[pending operator]`. No block was ever sterilized for this.

Deprecated rather than deferred a third time, on the operator's call. The pilot
existed to prove the Signal-to-farmOS record-keeping path before it could be
trusted; that path has been carrying real farmer traffic in production since,
which is a broader test than one scripted block would have been. PILOT-01 to
PILOT-03 (sterilization, QR-bound block assets, stage transitions) happen in prod
whenever the farmer logs a session.

PILOT-04, PILOT-05 and PILOT-06 remain genuinely unproven: production has not
reached a harvest, so the harvest batch, archive_spent, and the four-hop lineage
walk (bag -> harvest batch -> block -> sterilization batch) have never been
exercised end to end. This is a known, accepted gap and is deliberately not
ticketed. It gets proved by the first real harvest reaching farmOS, or it breaks
there and is fixed there.

The three verification tools this phase built (`tools/farmos-lineage.js`,
`farmos-current-stage.js`, `farmos-pilot-reconstruct.js`) are Node, belong to the
retired stack, and are now orphaned. Their disposal folds into MUSHY-101. If the
lineage walk is ever wanted against prod, `farmos-lineage.js` is the one worth
porting -- it is the only piece here that checks something production does not
check for itself.

---

## Original verification record (2026-05-13), retained

**Phase status:** scaffolded (autonomous run); pilot pending operator on
real-world calendar.

The autonomous run delivers scaffolding only per CONTEXT D-05a:
- Three query-only verification tools in `tools/` (23/23 Jest tests green).
- `42-RUNBOOK.md` operator playbook with one section per PILOT-NN.
- `42-PILOT-LOG.md` append-only journal scaffold.
- This file as the ship-gate placeholder.

Per CONTEXT D-05b the actual ship-gate flip to `passed` requires operator
attestation against real biological reality. Status remains
`human_needed` until then.

## Requirements coverage

| REQ-ID   | Status        | Evidence                                                                                                                         |
|----------|---------------|----------------------------------------------------------------------------------------------------------------------------------|
| PILOT-01 | human_needed  | Scaffolded. Operator executes per `42-RUNBOOK.md` section 1; records outcome in `42-PILOT-LOG.md`. Tools wired (no direct CLI).  |
| PILOT-02 | human_needed  | Scaffolded. Operator executes per `42-RUNBOOK.md` section 2; verification via `tools/farmos-current-stage.js <block_uuid>`.      |
| PILOT-03 | human_needed  | Scaffolded. Operator executes per `42-RUNBOOK.md` sections 3a..3f over 4-8 weeks; verification via `farmos-current-stage --at`.  |
| PILOT-04 | human_needed  | Scaffolded. Operator executes per `42-RUNBOOK.md` section 4; verification via `tools/farmos-lineage.js <bag_uuid>` (4-hop chain).|
| PILOT-05 | human_needed  | Scaffolded. Operator executes per `42-RUNBOOK.md` section 5; verification via `farmos-current-stage` returning `spent`.          |
| PILOT-06 | human_needed  | Scaffolded. Operator executes per `42-RUNBOOK.md` section 6; verification via `tools/farmos-pilot-reconstruct.js <block_uuid>`.  |

## Calendar-blocking

Per CONTEXT D-01a: real-world lifecycle is unavoidable.

- Sterilize -> inoc: same-day after PILOT-01.
- Colonize: 3-4 weeks.
- Cold_shock: 2-3 days.
- Fruiting flushes: 1+ week per flush, 2-3 flushes typical.
- Bagging + archive_spent: same-day after final flush.
- **Total: 4-8 weeks calendar from PILOT-01 to PILOT-06.**

The v1.7 milestone close partial-blocks here. The milestone-audit step
should recognize Phase 42 as "scaffolding shipped, pilot deferred to
real-world calendar" and proceed with the rest of v1.7 close. Phase 42
re-enters `/gsd-verify-work 42` once the operator finishes the lifecycle.

## Operator action list

Verbatim from CONTEXT D-05b:

> Operator must execute pilot per RUNBOOK; estimated calendar duration 4-8
> weeks; re-run `/gsd-verify-work 42` once lifecycle completes.

Concretely:

1. Run pre-flight (`42-RUNBOOK.md` section 0). Block if it fails.
2. (Optional but recommended) Run dry-run rehearsal against Phase 41
   synthetic-fixture corpus (`42-RUNBOOK.md` section 0a).
3. Execute PILOT-01 (sterilize batch). Journal in PILOT-LOG.md. Commit.
4. Execute PILOT-02 (inoculate 1 block with SHI + QR). Journal. Commit.
5. Execute PILOT-03 over 4-8 weeks: 5+ natural-message events (no_contam,
   relocate, cold_shock, pins, first flush). Journal each. Commit each.
6. Execute PILOT-04 (bagging with N QRs). Journal. Commit.
7. Execute PILOT-05 (archive_spent). Journal. Commit.
8. Execute PILOT-06 (timeline reconstruct + comparison). Save timeline as
   sibling artifact `42-pilot-timeline.txt`. Commit.
9. Re-run `/gsd-verify-work 42`. Flip this file's frontmatter to
   `status: passed` only after all 6 criteria attested.

## Failure modes that still PASS

Per RUNBOOK section 7: a real contamination or sterilizer failure does NOT
invalidate the pilot. If the failure-mode Signal message (`contam`) flips
the block to the `contaminated` terminal stage, that is a valid PILOT-03/05
attestation. Restart with a fresh block for PILOT-04..06 once ready.

---

*Scaffolded 2026-05-13. Pilot run pending. This file flips to
`status: passed` upon operator completion of all 6 criteria.*
