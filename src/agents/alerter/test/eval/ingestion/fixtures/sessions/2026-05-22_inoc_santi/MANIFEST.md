# 2026-05-22 inoc Santi -- named regression guard

```json
{
  "regression_guard": true,
  "capture_date": "2026-05-22",
  "source_path": "/mnt/mossrock/shared/mushdatadump-prod/2026-05-12_inoc_santi/",
  "notes": "Phase 49 Plan 01 named regression guard. Audio + paper-log photo are committed as symlinks to the prod corpus; ground-truth.json carries the canonical seeding_session shape."
}
```

## Capture origin

This is the May-22-2026 inoculation session captured by farmer1 (Santi). The
raw artifacts (audio `HOZad9ymvNJTXmRREgcW.m4a`, paper-log photo
`XAbzzUidkLR3irhVmjea.jpg`) live under
`/mnt/mossrock/shared/mushdatadump-prod/2026-05-12_inoc_santi/` even though
the capture itself is from May-22.

## Misfiled-under-May-12 caveat

During Phase 47 live-fire intake, the May-22 session got bundled into the
existing `2026-05-12_inoc_santi/` ingestion folder rather than getting its
own `2026-05-22_inoc_santi/` folder. Filename + folder content remain the
canonical paths -- ground-truth.json `meta.source_path` points at the
May-12 folder by design. The transcript content + paper-log photo confirm
the May-22 session shape (5 groups, 11 children, parents named below).

## Expected session shape

5 groups, 11 children, event_date 2026-05-22:

- SHI x1 from `260304_SHI_5`   -> child `260522_SHI_1`
- SHI x1 from `260118_SHI_23`  -> child `260522_SHI_2`
- SHI x1 from `260118_SHI_26`  -> child `260522_SHI_3`
- KOY x4 from `260118_KOY_12`  -> children `260522_KOY_4..7`
- KOY x4 from `260425_KOY_4`   -> children `260522_KOY_8..11`

## Why named regression

Phase 49's ship-gate is the May-22 reprocess. If the eval pipeline ever
fails to reconstruct this exact shape, CI must fail hard -- the live
ship-gate has already attested this shape against farmOS dev.

## Provenance shape

Per the Phase 47 seeding-session Zod schema, each field is provenanced
`{value, sources[]}`. Equality assertions in downstream plans key off
`{value, sources}` only; confidence is omitted from the truth file.

## Fixture artifacts

- `audio.m4a` -- symlink to the prod-corpus capture (do not copy raw bytes
  into the repo)
- `paper-log.jpg` -- symlink to the prod-corpus photo
- `ground-truth.json` -- canonical hand-labeled draft
- `MANIFEST.md` -- this file
