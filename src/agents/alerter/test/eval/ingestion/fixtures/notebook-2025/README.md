# notebook-2025 hermetic eval corpus (BACK-04 ship-gate)

**Status (2026-05-24):** POPULATED — 8 fixtures covering Feb–Nov 2025. Hermetic
suite green. Phase 54 unblocked.

This directory is the ship-gate corpus for Phase 53 BACK-04 (year-context
shim + small-N routing + capture_kind classifier). Phase 54 (backfill harness)
depends on `cd src/agents/alerter && npx jest --config test/eval/ingestion/jest.config.js
--runInBand test/eval/ingestion/notebook-2025.test.js` being green.

## What's here

8 fixtures drawn from the operator-curated mushdatadump corpus at
`/mnt/slime-kingdom/shared/mushdatadump/`. Each `image.jpg` is a symlink to a
notebook page photo under `jpeg/`; each `ground-truth.json` is derived from the
hand-transcribed rows in `mushroom_log.csv` (829 entries Feb–Dec 2025).
Source images are NOT copied into the repo — symlinks resolve at test time
from the shared mount.

| Fixture | Image | Date(s) | Entries | Profile |
|---------|-------|---------|---------|---------|
| 2025-02-01_IMG_3775 | IMG_3775.jpg | 2025-02-01 | 24 | First page; multi-strain (CAS/LIMA/SHI/POY/CAZ); date header "2-01-1" (compact) |
| 2025-02-04_IMG_3776 | IMG_3776.jpg | 2025-02-04 | 17 | Mid-size multi-strain; header "2025-02-04" (fully dated) |
| 2025-02-20_IMG_3778 | IMG_3778.jpg | 2025-02-20 | 8 | Small/sparse (CAZ/CAS/SHI); header "25-0220" |
| 2025-04-06_IMG_3782 | IMG_3782.jpg | 2025-04-06 | 4 | Sparse experimental (SHI + substrate notes GRAIN/SAWDUST); blank sources → parent="NO_PARENT" |
| 2025-05-27_IMG_3785 | IMG_3785.jpg | 2025-05-27 + 2025-05-28 | 18 | YEAR-ABSENT page covering two dates ("0527" + "0528"); KOY/CAS bulk |
| 2025-08-06_IMG_3800 | IMG_3800.jpg | 2025-08-06 | 21 | YEAR-ABSENT ("08 06"); single-strain bulk (DT/CAS/SHI) |
| 2025-11-08_IMG_3825 | IMG_3825.jpg | 2025-11-08 | 22 | YEAR-ABSENT ("1108"); multi-strain (SHI/CCM/MALI/BP); entries 21-22 blank source |
| 2025-11-17_IMG_3830 | IMG_3830.jpg | 2025-11-17 | 22 | YEAR-ABSENT ("1117"); multi-strain (SHI/KOS); page truncates at entry 22 (CSV continues 23-31 on a separate page not included) |

Coverage:
- **≥3 paper-log pages:** all 8 are `capture_kind=paper_log`
- **≥1 year-absent (BACK-01 case):** 4 fixtures (2025-05-27, 2025-08-06, 2025-11-08, 2025-11-17)
  have headers with no year — extractor must use `corpus_context.default_year=2025`
- **Page with notes:** 2025-04-06 (substrate notes), plus all year-absent pages
- **Sparse / mid / dense:** 4-entry, 8-entry, 17-22-entry, 24-entry pages
- **Date range:** Feb → Nov 2025
- **Physical-object photo:** NOT present — the mushdatadump corpus is exclusively
  notebook pages. The harness handles missing `expected_capture_kind` gracefully
  (skips the round-trip assertion); a physical-object fixture can be added later
  if/when one lands in the corpus.

## Per-fixture layout

```
fixtures/notebook-2025/<page-id>/
  image.jpg                # symlink → /mnt/slime-kingdom/shared/mushdatadump/jpeg/IMG_*.jpg
  manifest.json            # { name, year, corpus_context, expected_capture_kind, regression_guard:true, ... }
  ground-truth.json        # { drafts: [{ draft: { type:'seeding_session', event_date, groups:[...] } }] }
  mock-extraction.json     # raw Anthropic tool_use response for hermetic replay
```

Each `ground-truth.json` draft is one `seeding_session` per page-date, with one
`group` per CSV row (qty=1, parent=source-or-"NO_PARENT", species=strain,
child_block_names=["NEEDS_SEQ"]). Schema-conformant per
`src/extraction/schemas/seeding-session.js` and `src/extraction/schemas/index.js`.

## How to add a fixture

1. Pick a notebook page from `/mnt/slime-kingdom/shared/mushdatadump/jpeg/` in
   the IMG_3775–IMG_3861 range (2025-dated; ground-truth rows exist in
   `mushroom_log.csv`). Confirm the image's date header and entry count
   against the CSV.
2. Create a subdir here named `<YYYY-MM-DD>_<IMG_NAME>/`.
3. Add the four artifacts above. The simplest path: extend the helper at
   `/tmp/gen-notebook-fixtures.js` (or copy-paste-adapt it) — it builds all
   four artifacts from one `FIXTURES_SPEC` entry.
4. Run `cd src/agents/alerter && npx jest --config test/eval/ingestion/jest.config.js
   --runInBand test/eval/ingestion/notebook-2025.test.js` — must stay green.

## Live-LLM smoke (operator-on-demand)

Hermetic CI uses a mock Anthropic client that replays `mock-extraction.json`
verbatim. To spot-check that the live LLM produces the same drafts:

```
cd src/agents/alerter && ANTHROPIC_API_KEY=... npm run test:eval
```

Each live response is persisted to
`test/eval/ingestion/results/notebook-2025/<page-id>-<ISO>.json` (per memory
`[[feedback_persist_paid_results_default]]`).
