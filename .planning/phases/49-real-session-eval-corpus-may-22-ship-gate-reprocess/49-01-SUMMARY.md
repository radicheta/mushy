---
phase: 49-real-session-eval-corpus-may-22-ship-gate-reprocess
plan: 01
subsystem: alerter/extraction-db + alerter/test/eval/ingestion
tags: [schema-migration, eval-corpus, regression-guard, sessions-loader]
requires:
  - signal_draft table from Phase 38
  - test/eval/ingestion/ harness from Phase 41
provides:
  - signal_draft.discarded_reason + .discarded_at columns (idempotent migration)
  - test/eval/ingestion/fixtures/sessions/ corpus root
  - first named regression fixture: 2026-05-22_inoc_santi
  - sessions-loader.js (sibling of fixtures-loader.js)
affects:
  - alerter boot (initDb runs the two new ALTERs)
tech_stack:
  added: []
  patterns:
    - "ALTER TABLE ... ADD COLUMN IF NOT EXISTS pattern from Phase 38 D-02a"
    - "fixtures-loader.js iteration pattern (Phase 41) carried into sessions-loader.js"
key_files:
  created:
    - src/agents/alerter/test/eval/ingestion/sessions-loader.js
    - src/agents/alerter/test/eval/ingestion/sessions-loader.test.js
    - src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-05-22_inoc_santi/ground-truth.json
    - src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-05-22_inoc_santi/MANIFEST.md
    - src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-05-22_inoc_santi/audio.m4a (symlink)
    - src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-05-22_inoc_santi/paper-log.jpg (symlink)
  modified:
    - src/agents/alerter/src/extraction/extraction-db.js
    - src/agents/alerter/test/extraction/extraction-db.test.js
decisions:
  - "Audio + paper-log photo committed as symlinks (mode 120000) to /mnt/mossrock/shared/mushdatadump-prod/2026-05-12_inoc_santi/, not as copied bytes -- avoids ballooning repo clone size"
  - "MANIFEST.md carries the manifest as a fenced ```json``` block; loader extracts the first such block (Gray Area A lock)"
metrics:
  duration_minutes: ~15
  completed_date: 2026-05-23
---

# Phase 49 Plan 01: Schema + corpus foundation Summary

Two atomic primitives shipped that unblock Plans 02-04: (1) `signal_draft` gains
the `discarded_reason text` + `discarded_at timestamptz` columns the Plan 03
discard-drafts script will write to; (2) `test/eval/ingestion/fixtures/sessions/`
subdir is created with the first named regression fixture (`2026-05-22_inoc_santi/`)
and a `sessions-loader.js` sibling of `fixtures-loader.js` that iterates the
corpus and yields normalized entries.

## What was built

### 1. signal_draft schema delta (Task 1)

Two new columns appended to `initDb` in `extraction-db.js`, matching the
existing idempotent-ALTER pattern:

```sql
ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS discarded_reason text;
ALTER TABLE signal_draft ADD COLUMN IF NOT EXISTS discarded_at timestamptz;
```

Both nullable; existing inserts (which omit these columns) remain valid. The
only writer is Plan 03's discard-drafts script. `extraction-db.test.js` was
extended:

- Query count assertion bumped from 4 -> 6 on first init, 8 -> 12 on second
  (idempotency).
- Explicit regex assertions on both new columns.
- New `Phase 49: discard columns added idempotently` test.

Test result: 18 passed, 0 failed.

### 2. Sessions corpus + loader (Task 2)

New directory tree:

```
src/agents/alerter/test/eval/ingestion/fixtures/sessions/
  2026-05-22_inoc_santi/
    audio.m4a       -> symlink to /mnt/mossrock/shared/mushdatadump-prod/2026-05-12_inoc_santi/HOZad9ymvNJTXmRREgcW.m4a
    paper-log.jpg   -> symlink to /mnt/mossrock/shared/mushdatadump-prod/2026-05-12_inoc_santi/XAbzzUidkLR3irhVmjea.jpg
    ground-truth.json
    MANIFEST.md
```

`ground-truth.json` is a literal `seeding_session` draft per the Phase 47-04
Zod schema:

- `type: 'seeding_session'`, `event_date: '2026-05-22'`
- 5 groups, 11 children:
  - SHI x1 from `260304_SHI_5`  -> `260522_SHI_1`
  - SHI x1 from `260118_SHI_23` -> `260522_SHI_2`
  - SHI x1 from `260118_SHI_26` -> `260522_SHI_3`
  - KOY x4 from `260118_KOY_12` -> `260522_KOY_4..7`
  - KOY x4 from `260425_KOY_4`  -> `260522_KOY_8..11`
- Per-field provenance shape `{value, sources[]}` (confidence omitted -- Plan 02 equality assertions key off `{value, sources}` only)
- `meta: { capture_date, source_path, regression_guard: true, notes }`

`MANIFEST.md` opens with a fenced ```json``` block holding
`{regression_guard, capture_date, source_path, notes}`, followed by prose
documenting the misfiled-under-May-12 caveat.

### 3. sessions-loader.js

Mirrors `fixtures-loader.js` style (CJS, `fs.readdirSync`, never-throw on
file-missing -- warn + skip; throw only on JSON parse failure):

```
loadSessionsCorpus(dir, { logger = console } = {})
  -> Array<{ name, dir, manifest, groundTruth, audioPath, photoPath }>
```

Discovery rules:
- One entry per direct child subdir containing BOTH `ground-truth.json` AND `MANIFEST.md`.
- `manifest` = parsed first ```json``` fenced block from MANIFEST.md (null + warn if missing or unparseable; entry still surfaced).
- `audioPath` set to absolute path when `audio.{m4a,aac,wav,mp3,ogg,opus}` exists, else null.
- `photoPath` set to absolute path when `paper-log{,.*}.{jpg,jpeg,png}` exists, else null.

Test result (`sessions-loader.test.js`): 8 passed, 0 failed.

## Verification (from plan)

- `npx jest test/extraction/extraction-db.test.js` -- 18 passed
- `npx jest --config test/eval/ingestion/jest.config.js test/eval/ingestion/sessions-loader.test.js` -- 8 passed
- `ls fixtures/sessions/2026-05-22_inoc_santi/` -- audio.m4a, paper-log.jpg, ground-truth.json, MANIFEST.md
- `jq '.groups | length' ground-truth.json` -- 5
- `jq '[.groups[].child_block_names.value[]] | length' ground-truth.json` -- 11

All verifications green.

## Source-path correction note

The May-22 audio + paper-log photo physically live under the
`2026-05-12_inoc_santi/` directory in mushdatadump-prod, not under a
`2026-05-22_inoc_santi/` directory. This is documented in both
`ground-truth.json` `meta.notes` and `MANIFEST.md`'s "Misfiled-under-May-12
caveat" section. The fixture references those source paths via symlink (do
not copy raw bytes into the repo) per the operator instruction on this run.

The May-12 transcript (`transcript-HOZad9ymvNJTXmRREgcW.txt`) was inspected
to confirm the audio capture; content references the SHI / KOY parent
batches consistent with the Phase 47 CONTEXT-locked May-22 shape.

## Loader contract documentation

For Plan 02's `sessions.test.js`:

```js
const path = require('path');
const { loadSessionsCorpus } = require('./sessions-loader');

const SESSIONS_DIR = path.resolve(__dirname, 'fixtures/sessions');
const ALL = loadSessionsCorpus(SESSIONS_DIR);
const NAMED = ALL.filter((s) => s.manifest && s.manifest.regression_guard === true);

describe.each(NAMED)('named session $name (regression guard)', (session) => {
  // build pipeline input from session.audioPath + session.photoPath
  // assert against session.groundTruth.groups[]
});
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking decision] Symlink instead of copy for audio + photo**
- **Found during:** Task 2 file-copy step.
- **Issue:** Plan action #2 says "Copy" but the user instruction on this run was "Reference the prod path in the fixture (do not copy the audio file itself -- reference it)." The plan-behavior assertions (audioPath !== null, photoPath !== null) still need real files at those paths for the loader test to pass.
- **Fix:** Used filesystem symlinks (`ln -sfn`) committed as git `mode 120000` symlink entries. Loader treats them identically to regular files (no symlink check needed); the resolved path is what the loader returns. Repo clone size stays small.
- **Files modified:** the two symlinks under `fixtures/sessions/2026-05-22_inoc_santi/`
- **Commit:** `aa7ddb1`

### Authentication Gates

None.

### Threat Flags

None new -- the plan's threat register T-49-01-01 (information disclosure via audio) is mitigated by the symlink approach: raw audio bytes never enter the repo, only path references do. T-49-01-03 (clone size DoS) similarly mitigated.

## Known Stubs

None.

## Self-Check: PASSED

Files verified to exist:
- FOUND: src/agents/alerter/src/extraction/extraction-db.js
- FOUND: src/agents/alerter/test/extraction/extraction-db.test.js
- FOUND: src/agents/alerter/test/eval/ingestion/sessions-loader.js
- FOUND: src/agents/alerter/test/eval/ingestion/sessions-loader.test.js
- FOUND: src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-05-22_inoc_santi/ground-truth.json
- FOUND: src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-05-22_inoc_santi/MANIFEST.md
- FOUND: src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-05-22_inoc_santi/audio.m4a (symlink)
- FOUND: src/agents/alerter/test/eval/ingestion/fixtures/sessions/2026-05-22_inoc_santi/paper-log.jpg (symlink)

Commits verified:
- FOUND: a0069b7 (Task 1: schema columns)
- FOUND: aa7ddb1 (Task 2: corpus + loader)
