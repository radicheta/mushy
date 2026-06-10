---
phase: 55B
slug: 55b-fidelity-corpus-unblock
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-09
---

# Phase 55B — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: 55B-RESEARCH.md "Validation Architecture".

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Jest (existing; 1383 tests green as of 2026-06-09) |
| **Config file** | `src/agents/alerter/package.json` (inline jest config) |
| **Quick run command** | `cd src/agents/alerter && npx jest --testPathPattern="backfill|commit-seeding-session" --passWithNoTests` |
| **Full suite command** | `cd src/agents/alerter && npx jest --passWithNoTests` |
| **Estimated runtime** | ~quick <15s / full ~60-90s |

---

## Sampling Rate

- **After every task commit:** Run quick command (`--testPathPattern="backfill|commit-seeding-session"`)
- **After every plan wave:** Run full suite
- **Before `/gsd:verify-work`:** Full suite green, THEN 5-page paid re-smoke green
- **Max feedback latency:** ~15 seconds (quick)

---

## Per-Task Verification Map

> Filled at plan-time per task; mapped from research's Phase-Requirements-to-Test table.
> Req IDs are phase-local (no REQUIREMENTS.md IDs mapped to 55B).

| Req | Behavior | Test Type | Automated Command | File Exists | Status |
|-----|----------|-----------|-------------------|-------------|--------|
| FIDELITY-01 | CSV cross-check holds mismatched strain | unit | `npx jest scripts/backfill-notebook.test.js -t "fidelity"` | ❌ W0 | ⬜ pending |
| FIDELITY-01 | CSV cross-check holds when no CSV rows | unit | `npx jest scripts/backfill-notebook.test.js -t "no_csv"` | ❌ W0 | ⬜ pending |
| FIDELITY-01 | CSV-verified draft proceeds to commit | unit | `npx jest scripts/backfill-notebook.test.js -t "csv_verified"` | ❌ W0 | ⬜ pending |
| FIDELITY-02 | needs_review_reason=fidelity_cross_check_unverified on mismatch | unit | `npx jest scripts/backfill-notebook.test.js -t "hold_reason"` | ❌ W0 | ⬜ pending |
| FIDELITY-02 | needs_review_reason=fidelity_cross_check_no_csv on no-CSV page | unit | `npx jest scripts/backfill-notebook.test.js -t "no_csv_reason"` | ❌ W0 | ⬜ pending |
| SESSION-01 | aggregateSeedingDraftsToSessionJson groups by parent+species | unit | `npx jest scripts/backfill-notebook.test.js -t "aggregate"` | ❌ W0 | ⬜ pending |
| SESSION-02 | commitSeedingSession uploads attachments when sessionPagePaths set | unit | `npx jest test/farmos/commit-seeding-session.test.js -t "image"` | ❌ W0 | ⬜ pending |
| SESSION-02 | patchGroupAssetFiles sends correct JSON:API PATCH payload | unit | `npx jest test/farmos/commit-seeding-session.test.js -t "patch_files"` | ❌ W0 | ⬜ pending |
| SESSION-03 | held drafts produce no farmOS assets (absent from membership) | integration | smoke dev :18080 (manual) | — | ⬜ pending |
| SMOKE-01 | 5-page paid smoke receipt shows held entries for IMG_3776 | smoke | manual (operator) | — | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `scripts/backfill-notebook.test.js` — add `processDraftsForCapture` tests with mocked `loadCsvForPage`: (a) no-CSV holds all, (b) CSV-match commits, (c) CSV-mismatch holds, (d) budget-exhausted holds
- [ ] `test/farmos/commit-seeding-session.test.js` — add: (a) `patchGroupAssetFiles` payload shape, (b) upload-then-patch path, (c) image upload failure is non-fatal
- [ ] `scripts/backfill-notebook.test.js` — add `aggregateSeedingDraftsToSessionJson` unit tests: (a) single parent+species, (b) multi-parent, (c) block_names array
- [ ] **Wave 0 smoke probe (A1):** verify `PATCH /api/asset/group/<id>` with `relationships.file` associates files on dev `:18080` BEFORE the image-attach implementation commit

---

## Manual-Only Verifications

| Behavior | Why Manual | Test Instructions |
|----------|------------|-------------------|
| Held entries absent from session membership in farmOS (SESSION-03) | Requires live farmOS dev instance + visual member-list check | Run 5-page smoke against dev :18080; open the `asset--group` session page; confirm held blocks are NOT members |
| 5-page re-smoke fidelity pass (SMOKE-01) | Paid-LLM run; operator-gated (GA1 isolation) | `--limit=5 --resume-from=IMG_3775.jpg` against isolated dev DB; check receipt shows held entries for IMG_3776 (mode-2 regression guard) |
| Page image(s) visible on session asset (D-03) | Visual farmOS check | Open session group asset; confirm 1..N notebook page images attached and viewable |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (incl. A1 PATCH smoke probe)
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s (quick)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** planner-signed 2026-06-09 -- all tasks carry <automated> verify or a Wave 0 dependency; A1 PATCH probe is the explicit Wave 0 smoke gate
