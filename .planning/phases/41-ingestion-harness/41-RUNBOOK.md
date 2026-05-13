# Phase 41 RUNBOOK

Operator instructions for the ingestion harness. Covers smoke-before-full,
live paper-log eval, hand-labeling mushdatadump-prod, audio corpus discovery,
paired-session inputs, and reading the eval report.

## 1. Smoke before full

Always run the harness with `--smoke` first. Only run the full corpus on a
green smoke. Per `feedback_smoke_before_expensive_batch`.

## 2. Live paper-log eval (operator-only)

### 2a. Smoke

```
ANTHROPIC_API_KEY=... EVAL_RUN_LIVE=1 EVAL_SMOKE_SIZE=5 \
  node src/agents/alerter/test/eval/ingestion/run-harness.js \
  --corpus paper-log --smoke --live --cap-usd 5
```

### 2b. Full

```
ANTHROPIC_API_KEY=... \
  node src/agents/alerter/test/eval/ingestion/run-harness.js \
  --corpus paper-log --live --cap-usd 20
```

JSONL lands at `src/agents/alerter/test/eval/ingestion/results/paper-log-<ts>-<runid>.jsonl`.
Markdown report (Plan 06/07) lands at `.planning/phases/41-ingestion-harness/41-EVAL-REPORT-paper-log-<ts>.md`.

## 3. Operator action: hand-label mushdatadump-prod

`/mnt/mossrock/shared/mushdatadump-prod/2026-05-12_inoc_santi/` contains
roughly 24 drafts that require hand-labels for the INGEST-02 prod ship-gate.

### 3a. Per-session expected.json schema

Create one file per session subdir at `<session>/expected.json`:

```
{
  "type": "seeding",
  "requiredFields": ["block_name", "species", "qty"],
  "fields": {
    "block_name": "260512_SHI_4",
    "species": "SHI",
    "qty": 1,
    "substrate": "sawdust",
    "parent_batch_name": "BATCH-2026-05-12-001"
  },
  "ambiguous": false,
  "session_id": null,
  "provenance": {
    "source": "operator hand-label",
    "labeled_by": "santi",
    "labeled_at": "2026-05-NN"
  }
}
```

### 3b. Bootstrap tool (build only if hand-labeling past fixture 5 hurts)

If filling each `expected.json` by hand takes more than 2 minutes per fixture,
write a small `src/agents/alerter/test/eval/ingestion/tools/label-bootstrap.js`
(~50 LOC) that runs the live extractor once per session, dumps `actual.draft`
as a draft `expected.json` sidecar, and lets the operator edit-in-place to
correct. Run this AFTER fixture 5 only if the bootstrap saves time.

## 4. Operator action: supply audio corpus path (INGEST-03)

If `AUDIO_FIXTURE_DIR` is unset at Phase 41 close, INGEST-03 ships as
`human_needed` in 41-VERIFICATION.md.

### 4a. If recordings exist

Set `AUDIO_FIXTURE_DIR` and lay out one `expected.json` per session subdir
(same schema as section 3a but `type` may be observation / activity / etc).

```
AUDIO_FIXTURE_DIR=/path/to/recordings \
ANTHROPIC_API_KEY=... \
WHISPER_URL=http://elder-plops:8090 \
EVAL_RUN_LIVE=1 EVAL_SMOKE_SIZE=5 \
npm run test:eval-ingestion -- -t audio.*smoke
```

Then full corpus (after smoke is green):

```
AUDIO_FIXTURE_DIR=... ANTHROPIC_API_KEY=... WHISPER_URL=... EVAL_RUN_LIVE=1 \
npm run test:eval-ingestion -- -t audio.*full
```

### 4b. If recordings do not exist yet

Record one inoc session narrated end-to-end (smallest first capture). Drop the
file at `src/agents/alerter/test/eval/ingestion/fixtures/audio/<session>/recording.m4a`
plus a hand-labeled `expected.json`. Re-run 4a smoke; iterate from one fixture
upward.

### 4c. Incremental add

Adding one new audio fixture: drop the audio + `expected.json` in a new subdir.
The loader picks it up on the next harness invocation. Re-run smoke (covers it
if within the first 5; else run full). JSONL is append-only per run; old runs
preserved.

## 5. Operator action: paired-session inputs (INGEST-04)

Two paired sessions ship in v1.7:
- `shi-inoc-2026-05-12-d07` (paper-log photo + audio of same inoc)
- `obs-colonizing-<date>` (paper-log photo + audio of same observation)

Both `expected.json` files must carry the SAME `session_id` key. The harness
groups by that key and asserts the writes match modulo whitespace + confidence
drift.

## 6. Live farmer UAT

Deferred to post-Phase 41 per CONTEXT D-08c. Same operator-deferred pattern as
Phase 25 / 37 / 39.

## 7. Reading the EVAL-REPORT + comparing runs

### 7a. Grep the verdict

```
grep '^## Verdict:' .planning/phases/41-ingestion-harness/41-EVAL-REPORT-*.md
```

Each run is its own file. Newest = canonical.

### 7b. Compare two runs for regressions

```
node src/agents/alerter/test/eval/ingestion/compare-runs.js \
  src/agents/alerter/test/eval/ingestion/results/paper-log-<older>.jsonl \
  src/agents/alerter/test/eval/ingestion/results/paper-log-<newer>.jsonl
```

Exit code 0 -> no regressions. Exit code 1 -> regression table printed to
stdout; fixture-by-fixture deltas.

### 7c. human_needed entries

The report prints `human_needed (operator action: see 41-RUNBOOK.md section N)` for:
- audio corpus when `AUDIO_FIXTURE_DIR` unset / empty (section 4)
- cross-stream when paired-session peers absent (section 5)
- mushdatadump-prod when hand-labels unsupplied (section 3)

These are stretch goals; Phase 41 ships on synthetic + paper-log v1.6.
