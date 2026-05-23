# 2026-03-23 inoc Santi -- photo-absent ask-back fixture (synthetic envelope, real labels)

```json
{
  "regression_guard": false,
  "synthetic": true,
  "capture_date": "2026-03-23",
  "event_date": "2026-03-23",
  "source_path": "/mnt/mossrock/shared/mushdatadump/mushroom_log.csv",
  "shape": "photo_absent_ask_back",
  "notes": "Phase 49 Plan 04 third corpus session. Real hand-labeled data from mushroom_log.csv rows for 2026-03-23 (entries 1-6); audio+photo capture envelope is synthetic. Exercises needs_input='starting_seq' ask-back path with NEEDS_SEQ sentinel child_block_names."
}
```

## Why this session was selected

Per CONTEXT.md Gray Area F, the third corpus session must exercise a
shape COMPLEMENTARY to the two existing named-regression fixtures:

| Fixture                                | Cardinality              | Photo  | Audio  | Shape feature                          |
| -------------------------------------- | ------------------------ | ------ | ------ | -------------------------------------- |
| `2026-05-22_inoc_santi`                | 5 groups, 11 children    | yes    | yes    | multi-parent, paper-log present        |
| `2026-05-12_inoc_santi`                | 5 groups, 12 children    | yes    | yes    | multi-parent + 2x NO_PARENT groups     |
| `2026-03-23_inoc_santi_photo_absent`   | 2 groups, 6 children     | absent | n/a    | photo-absent, ask-back via NEEDS_SEQ   |

The 2026-03-23 row in `mushroom_log.csv` is small (6 children) and
single-purpose (only ALM + WIN, both seeded from a single parent
each). This is the cleanest complementary shape available from the
broader `/mnt/mossrock/shared/mushdatadump/` corpus per Plan 04
selection criteria.

## Source data (real notebook rows)

From `/mnt/mossrock/shared/mushdatadump/mushroom_log.csv`, page_date
`2026-03-23`, entries 1-6:

```
2026-03-23,1,ALM,2-18-8,
2026-03-23,2,ALM,2-18-8,
2026-03-23,3,WIN,02-28-16,
2026-03-23,4,WIN,02-28-16,
2026-03-23,5,WIN,02-28-16,
2026-03-23,6,WIN,02-28-16,
```

Group-collapse (per Phase 47 SeedingSession shape lock):

| Notebook source code | Group                                                            |
| -------------------- | ---------------------------------------------------------------- |
| `2-18-8`             | parent=260218_ALM_8, species=ALM, qty=2, children NEEDS_SEQ x2   |
| `02-28-16`           | parent=260228_WIN_16, species=WIN, qty=4, children NEEDS_SEQ x4  |

## Why audio + photo are absent

Phase 38 transcribed the notebook directly into CSV; only the May-12
and May-22 sessions were intake-staged with paired audio+photo. The
broader corpus contains harvest photos and Signal screenshots but no
inoc-session audio narration beyond what is already fixtured.

Per CONTEXT Gray Area F, the documented fallback is a synthetic
fixture in the unnamed-corpus tier (regression_guard:false). The
ground-truth labels are still REAL -- only the capture envelope is
synthetic.

## Why this exercises a complementary path

The May-22 + May-12 fixtures both have paper-log photos, so their
ground-truth child_block_names are concrete B5 strings drawn from the
photo. This fixture has NO photo, so the extractor cannot infer
starting SEQ for either group. Per Phase 47 Gray Area 3 lock, the
extractor emits child_block_names as the `NEEDS_SEQ` sentinel and
sets top-level `needs_input='starting_seq'` to trigger the farmer
ask-back path. This exercises the schema's union-with-sentinel
branch (`ChildBlockNameOrSentinel`) which the May-22 + May-12
fixtures do not.

## Fixture artifacts

- `ground-truth.json` -- canonical hand-labeled draft (real labels)
- `mock-extraction.json` -- pre-recorded extractor response for hermetic mock-mode invocation
- `MANIFEST.md` -- this file
- NO `audio.*` or `paper-log.*` files (photo-absent shape is the whole point)

## CI gate behavior

`sessions.test.js` filters on `manifest.regression_guard === true`,
so this fixture is loaded by `sessions-loader.js` but excluded from
the named-regression equality-assertion gate. The named-regression
count remains 2 (May-22, May-12). This fixture is corpus-diversity
broadening only; if a future plan attaches a real captured audio+photo,
flip `regression_guard` to `true` and the gate will pick it up
automatically.

## Provenance shape

Per the Phase 47 seeding-session Zod schema, each field is
provenanced `{value, sources[]}`. All sources here are `audio` only
(no paper_log_photo because there is no paper-log photo). The
extractor would, in live capture, produce the same shape: parents
and species and qty from audio; child_block_names defaulted to
`NEEDS_SEQ` because no photo provides the SEQ.
