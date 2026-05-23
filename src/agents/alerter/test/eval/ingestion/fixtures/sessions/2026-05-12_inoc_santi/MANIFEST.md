# 2026-05-12 inoc Santi -- named regression guard

```json
{
  "regression_guard": true,
  "capture_date": "2026-05-12",
  "event_date": "2026-04-25",
  "source_path": "/mnt/mossrock/shared/mushdatadump-prod/2026-05-12_inoc_santi/",
  "notes": "Phase 49 Plan 02 named regression guard. Ground-truth derived from Phase 38 Plan-09 replay (audio narration for the 2026-04-25 inoc session)."
}
```

## Capture origin

This is the May-12-2026 capture by farmer1 (Santi) describing an inoculation
session that took place 2026-04-25. The raw artifacts (audio
`om01IyuHnLBohp1r_F_m.aac`, paper-log photo `YkBwglxBTAFiQE5JbRwr.jpg`) live
under `/mnt/mossrock/shared/mushdatadump-prod/2026-05-12_inoc_santi/`.

## Phase 38 Plan-09 ground-truth reuse

The session shape comes from the Phase 38 Plan-09 replay artifact
(`replay-output.txt` under the prod corpus) which exercised the live
extractor pipeline against the May-12 capture post-bug-fix
(image-wire fix + WIN vocab patch). Per-bag drafts from that replay
were collapsed into the seeding_session group-shape required by the
Phase 47 schema lock: bags sharing a parent + species collapse into
one group with `qty=N` and `child_block_names.value=[<N names>]`.

Group collapse mapping (audio-only, 12 children, 5 groups):

| Audio narration                                       | Group                                                         |
| ----------------------------------------------------- | ------------------------------------------------------------- |
| `1.1825` (118_25), SHI x3 (bag + 2 drippy-corn jars) | parent=260118_SHI_25, species=SHI, qty=3, children 1,2,3      |
| `1.187` (118_7), KOY x2 (1 drippy-corn + 1 bag)      | parent=260118_KOY_7, species=KOY, qty=2, children 4,5         |
| `3.23` (323_3), WIN x3 (grain+manure+oats)           | parent=260323_WIN_3, species=WIN, qty=3, children 6,7,8       |
| DT x3 (no parent named in audio; "9, 10, 11")        | parent=null, species=DT, qty=3, children 9,10,11              |
| Outdoor SHI x1 (no source ID, "some bark from logs") | parent=null, species=SHI, qty=1, children 12                  |

Two parent.value entries are null because the audio narration did not
name a parent for those groups -- a real-data shape the regression
guard preserves. The Phase 47 SeedingSession Zod schema accepts
nullable parent values per CONTEXT.md decision (parent is not always
present on every paper-log entry).

## Source-file caveat

Plan-01 symlinked `HOZad9ymvNJTXmRREgcW.m4a` (the actual inoc
narration audio per the prod-corpus MANIFEST.md) and
`XAbzzUidkLR3irhVmjea.jpg` (one of the paper-log pages) under the
2026-05-22 fixture. Plan-02 picks up the remaining audio file
(`om01IyuHnLBohp1r_F_m.aac` -- flagged as a butt-dial in the prod
MANIFEST) and the remaining paper-log photo (`YkBwglxBTAFiQE5JbRwr.jpg`)
for the May-12 symlinks. For hermetic CI runs this is fine: the
mock-extractor returns mock-extraction.json regardless of which file
sits behind the symlink. The EVAL_RUN_LIVE=1 ship-gate run (Plan 04
scope) must re-validate symlink targets before invoking the real
extractor.

## Expected session shape

5 groups, 12 children, event_date 2026-04-25:

- SHI x3 from `260118_SHI_25`   -> children `260425_SHI_1..3`
- KOY x2 from `260118_KOY_7`    -> children `260425_KOY_4..5`
- WIN x3 from `260323_WIN_3`    -> children `260425_WIN_6..8`
- DT x3  (no parent)            -> children `260425_DT_9..11`
- SHI x1 (outdoor, no parent)   -> children `260425_SHI_12`

## Why named regression

The May-12 session was Phase 38 Plan-09's first real-prod ship-gate
fixture (after the 2-curated-photo PASS proved structurally
insufficient). Phase 47 + Phase 49 must continue to handle this shape
correctly -- any regression on the WIN coding (Plan 09 vocab fix),
the parent-nullable groups (DT / outdoor SHI), or the group-collapse
shape must surface as a hard CI red.

## Provenance shape

Per the Phase 47 seeding-session Zod schema, each field is
provenanced `{value, sources[]}`. Equality assertions in
`sessions.test.js` key off
`{type, event_date, groups[].parent.value, groups[].species.value,
groups[].qty.value, groups[].child_block_names.value}` only;
confidence + sources arrays are not asserted (legitimately drift
across mock vs live runs).

## Fixture artifacts

- `audio.aac` -- symlink to the prod-corpus audio capture
- `paper-log.jpg` -- symlink to the prod-corpus paper-log photo
- `ground-truth.json` -- canonical hand-labeled draft
- `mock-extraction.json` -- pre-recorded extractor response for hermetic CI
- `MANIFEST.md` -- this file
