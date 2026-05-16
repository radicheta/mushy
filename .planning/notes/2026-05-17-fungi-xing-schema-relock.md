---
date: 2026-05-17
author: claude (overnight research, read-only) -- summary recovered from sandboxed agent; full inline draft was lost when write was blocked
scope: v1.8 Candidate A precondition -- fungi_xing / harvest_batch / bag->fruit schema relock
companion-notes:
  - .planning/notes/2026-05-13-v1.8-candidates.md (external-pressure section + Candidate A)
  - .planning/notes/2026-05-13-fungi-type-pushback-options.md
  - .planning/notes/2026-05-14-reply-from-farmos-fungi-schema.md
  - .planning/notes/2026-05-14-seeder-run-confirmation.md
  - .planning/notes/2026-05-14-prod-cutover-status-from-farmos.md
  - .planning/notes/2026-05-14-prod-cutover-complete.md
verdict: ALREADY DONE. Re-lock landed 2026-05-14 across mushy + farmOS-dev + farmOS-prod. v1.8 Candidate A Phase 1 should be struck. Size for the relock work itself: ZERO (S; zero-day owed).
---

# fungi_xing schema re-lock -- research note

## TL;DR

The "fungi_xing schema re-lock" called out as external pressure in `2026-05-13-v1.8-candidates.md`
landed three days before this scoping run. The v1.8 candidates doc (line 25 + Candidate A Phase 1)
is stale on this axis. Mushy-side checklist for the relock proper: **0 edits owed.**

Three schema-adjacent items remain open but are NOT the re-lock and should not be folded into
Candidate A Phase 1:

1. Phase 38 <-> Phase 40 shape mismatch (see `.planning/notes/2026-05-16-schema-audit.md`)
2. No-target observation rejection (see `.planning/notes/2026-05-16-farmos-no-target-and-strain-coverage.md`)
3. Strain block-asset coverage gap (same note, Part 2)

## 1. Evidence the relock is done

### Mushy-side commits

- `0e56eec` -- alerter rewrite for Option A hybrid (`fungi_type` = strain code + `fungi_xing` in `{block, fruit}`)
- `8fd5385` -- seeder updated
- `b5d5dd2` -- substrate=log-only lock (per memory `project_substrate_log_only_lock_2026_05_14`)

### Files verified at HEAD (file:line)

- `src/agents/alerter/src/farmos/fungi-type-cache.js`
- `src/agents/alerter/src/farmos/fungi-xing-cache.js`
- `src/agents/alerter/src/farmos/assets.js`
- `src/agents/alerter/src/farmos/commits/commit-seeding.js:43-52`
- `src/agents/alerter/src/farmos/commits/commit-harvest.js:14, 69-83, 74, 97`
- `scripts/seed-dev-farmos-taxonomies.js:59-60`

All on the agreed shape. No remaining references to the old `fungi_type in {batch, block, bag}`
shape anywhere in code or tests.

### Tests

- `test/farmos/assets.test.js`
- `test/farmos/commit-seeding.test.js`
- `test/farmos/commit-harvest.test.js`
- `test/farmos/mock-client.js`

All rewritten with dual-relationship (`fungi_type` + `fungi_xing`) assertions.

### farmOS-side state (cross-repo evidence)

- Dev seeded + `fungi_xing` field added on `asset--fungi` bundle (per `2026-05-14-seeder-run-confirmation.md`)
- Prod seeded + field added + asset 31 (lion's mane) backfilled (per `2026-05-14-prod-cutover-status-from-farmos.md`)
- Prod live-smoke PASS, commit `edb416c` (per `2026-05-14-prod-cutover-complete.md`)
- `harvest_batch` is now a STRING LABEL only (`dj.harvest_batch_name` in `commit-harvest.js:14, 74, 97`) -- no asset created
- `species` vocab deleted entirely
- Substrate placement = Option C / log-only (memory: `project_substrate_log_only_lock_2026_05_14`)

NB: `/mnt/slime-kingdom/shared/farmos/` was permission-denied to the agent during this run.
State was confirmed via the cross-repo notes that already live in mushy's own `.planning/notes/`
(2026-05-14 series) plus prod-smoke commit + DB row 31 backfill evidence. No NEW farmOS-side
schema movement is visible from the mushy side post-2026-05-14.

## 2. Sizing

**Size: S (zero-day).** Mushy-side checklist: 0 files to edit, 0 tests to update, 0 migrations to run.

## 3. v1.8 planning corrections owed

The following docs reference the relock as future work and should be updated:

- `.planning/notes/2026-05-13-v1.8-candidates.md` line 25 (external-pressure bullet)
- `.planning/notes/2026-05-13-v1.8-candidates.md` Candidate A Phase 1 ("Schema re-lock") -- STRIKE. Re-number Phases 2-5 as 1-4. Reconsider Candidate A's M sizing (probably still M because Phases 2-5 are the bulk of the work, but the M no longer absorbs schema-migration risk).
- `.planning/notes/2026-05-13-v1.8-candidates.md` Candidate B Phase 1 -- update: prod schema is already live; remaining prod-cutover scope is per-farmer targeting, write-failure alerting, replay.

## 4. Coordination questions for farmOS side (non-blocking)

Each with runner named per `feedback_cross_repo_runner_must_be_named`:

1. **State confirmation** -- farmOS side: please confirm the relock matches mushy's HEAD shape (no drift since 2026-05-14). Runner: farmOS-side spot-check via `GET /api/asset/fungi?page[limit]=5`.
2. **Legacy `Sawdust` term cleanup** -- per substrate=log-only lock, the `Sawdust` taxonomy term may be vestigial in dev. Runner: farmOS-side audit + delete if unused.
3. **`farm_id_tag.type=qr` allowed-value flip** -- check whether `qr` is in the allowed-values list now that prod has live QR-tagged assets. Runner: farmOS-side schema check.
4. **Future-strain-additions runner convention** -- when new strain codes appear (LIMA/MAI/CAS surfaced 2026-05-15), who runs the seeder update? Runner: mushy-side (`scripts/seed-dev-farmos-taxonomies.js`) and farmOS-side (prod seeding). Codify in cross-repo handoff template.

None gate v1.8 planning.

## 5. What the relock does NOT cover (file separately)

Three schema-adjacent failure modes remain open but are NOT the relock:

1. **Phase 38 extractor <-> Phase 40 commit handler shape mismatch.** Full audit in `2026-05-16-schema-audit.md`. 4 of 5 log_types have terminal mismatches. Fix: router-side normalizer (Option A) + chain integration tests (Option C). **~1 day.**
2. **No-target observation rejection.** Full analysis in `2026-05-16-farmos-no-target-and-strain-coverage.md` Part 1. Pure mushy-side policy bug; farmOS field is already optional + multiple. Fix: delete three early-returns + add commit-failed farmer reply (see `2026-05-17-northstar-commit-failed-reply.md`). **~1 day.**
3. **Strain block-asset coverage gap.** Same note, Part 2. Only 5/14 active strains have any blocks in prod-farmOS (SHI/DT/WIN/KOY/MOR; missing LIMA/MAI/CAS/MALI/KOS/CAZ/ALM/BP/LIMA per memory `project_mossrock_active_strain_codes`). Fix: backfill sweep + auto-create fallback. **~1 week.**

## 6. Verdict

The fungi_xing relock is done. v1.8 Candidate A no longer needs a Phase 1 for schema work
-- its scope reduces to harvest extraction prompts, harvest write-path, yield analytics,
and live attestation. Candidate B (prod cutover) gets a similar reduction because prod
schema is already live.

The three schema-adjacent items above are independent of the relock and are tracked in
their own notes. None of them block v1.8 planning.
