# Phase 41 Research: Ingestion Harness

**Researched:** 2026-05-13
**Status:** Ready for planning
**Inputs:** 41-CONTEXT.md (D-01..D-09a), Phase 38 eval harness (`src/agents/alerter/test/eval/extraction/`), Phase 39 confirm-loop semantics, Phase 40 farmOS write path, `feedback_persist_paid_results_default`, `feedback_smoke_before_expensive_batch`, `feedback_real_data_before_ship_gate_pass`.

## 0. Path Correction (versus CONTEXT.md)

CONTEXT.md references `tests/eval/extraction/` as the "existing Phase 38 harness". The actual location is `src/agents/alerter/test/eval/extraction/` (Jest project rooted inside the alerter package). All Phase 41 references below resolve to the real path. The Phase 41 harness lives alongside at `src/agents/alerter/test/eval/ingestion/`.

This is a docs-only mismatch; no code lives at the CONTEXT.md path. Plans use the real path.

## 1. Existing Phase 38 Harness Shape (reuse surface)

Directory layout (`src/agents/alerter/test/eval/extraction/`):

- `fixtures-loader.js` -- two loaders: `loadFixtures(dir)` for curated mushdatadump v1.6 (jpeg + page-grain CSV), and `loadProdFixtures(dir, {skipNames})` for `mushdatadump-prod/`. Returns array of `{name, imagePath | imagePaths, audioPaths?, expected, isProd?}`.
- `scoring.js` -- exports `schemaConformance`, `exactFieldMatch`, `appropriateAskBack`, `setEqualityArrays`, plus B5 regex + Brier/ECE. Inputs are arrays of `{fixture, actual}`. Reusable as-is.
- `report.js` -- exports `writeReport(reportPath, scores, fixtureCount, verdict, meta)`. Already uses `fmtNum`, already no em-dashes, already grep-parseable verdict line. Reusable as-is; Phase 41 adds a thin wrapper that injects ingestion-specific dimensions (per-corpus tables, cross-stream consistency column).
- `mushdatadump.test.js` -- Jest entrypoint. Writes JSONL to `<report>-results.jsonl`. Truncates on each run (Phase 41 will NOT truncate -- see Section 5).
- `scoring.smoke.test.js` -- pure-JS unit tests for the scoring module (no API key, no fixtures). Stays untouched.
- `jest.config.js` -- isolated Jest project so eval tests don't run in the default `jest` invocation.

**Reusable as-is:** `scoring.js`, `report.js`, `fixtures-loader.js` (extended via composition, not modification).

**Reuse with thin wrapper:** harness driver pattern (extractor + transcribe-client + per-fixture loop with elapsed-time logging + JSONL writer).

## 2. Existing Pipeline Surface (harness call target)

The harness must drive the same code path as a live Signal message without invoking Signal-cli. Entry point: `src/agents/alerter/src/extraction/pipeline.js` exposes `loadImageBlocks(paths, logger)` and the orchestration function used by `capture.js`. For Phase 41 the harness will call the same orchestration directly with a synthetic Signal envelope (no signal-cli round trip; no confirm loop).

Confirm-loop fakery: harness presets `signal_draft.status = 'confirmed'` directly via `confirm-db.js` (skips the YES farmer reply). For full E2E (farmOS read-back assertion path), harness then invokes the Phase 40 commit chain (`farmos/commit-router.js`) and queries dev-farmOS to assert the write. This is the "harness fakes a YES on every fixture" mode.

Whisper integration: `src/agents/alerter/src/transcribe-client.js` is already factory-shaped (`createTranscribeClient({apiUrl})`). Phase 41 audio fixtures pass through this client at the same `WHISPER_URL` the live alerter uses (`http://host.docker.internal:8090` per Phase 38 default).

## 3. Fixture Loader API (Phase 41 extensions)

New loader at `src/agents/alerter/test/eval/ingestion/fixtures-loader.js`. Composition over the Phase 38 loaders:

```js
// Synthetic corpus loader: directory tree under fixtures/synthetic/
//   <seq>-<log_type>-<modality>/
//     input.json         -- Signal envelope (sender, body text, attachment paths)
//     attachment.jpg     -- optional image
//     attachment.m4a     -- optional audio
//     expected.json      -- target signal_draft body + session_id + per_field provenance
//
// Returns: { name, kind:'synthetic', envelope, expected, attachments[] }

function loadSyntheticCorpus(dir) { ... }

// Paper-log corpus loader: reuses Phase 38 loadFixtures for mushdatadump (CSV ground truth)
// + a new per-JPEG sidecar loader for mushdatadump-prod hand-labels:
//   /mnt/mossrock/shared/mushdatadump-prod/<session>/<image>.jpg
//   /mnt/mossrock/shared/mushdatadump-prod/<session>/<image>.expected.json   <-- new sidecar
//
// Returns: same shape, kind:'paper-log'

function loadPaperLogCorpus(dir, { handLabeled }) { ... }

// Audio corpus loader: directory tree
//   fixtures/audio/<session>/
//     recording.m4a
//     expected.json
// Operator may symlink an external corpus dir via AUDIO_FIXTURE_DIR env.

function loadAudioCorpus(dir) { ... }
```

All loaders return a uniform fixture shape:

```ts
type Fixture = {
  name: string,
  kind: 'synthetic' | 'paper-log' | 'audio',
  session_id?: string,        // shared across paired fixtures (D-05)
  envelope: SignalEnvelope,
  attachments: { type:'image'|'audio', path:string }[],
  expected: {
    type: B7LogType,
    fields: Record<string, any>,
    requiredFields: string[],
    ambiguous: boolean,
    provenance?: { source:string, labeled_by:string, labeled_at:string },
  },
};
```

## 4. Scorer Extension Points

Phase 38 scorer is reused unchanged for: schema conformance, exact-field match, appropriate-ask-back, set-equality, B5 regex, Brier, ECE. Phase 41 adds ONE new dimension:

```js
// New: groupBySession(results) -> Map<session_id, results[]>
// Then for each pair, deepEqualModWhitespace(a.actual.draft, b.actual.draft)
//   ignoring: per_field_confidence drift, whitespace normalization in string fields,
//   draft.id (deterministic but corpus-prefixed), source_capture_ids
function crossStreamConsistency(results) {
  // returns { aggregate: pct, totalPairs, identicalPairs, divergences: [...] }
}
```

The deep-equal-mod-whitespace helper normalizes strings via `s.trim().replace(/\s+/g,' ').toLowerCase()` and ignores keys listed above. Returned as a separate column in the report; not folded into the per-field score.

## 5. JSONL Append-Only Discipline (departure from Phase 38)

Phase 38 truncates the JSONL on each run (single-purpose harness, one report). Phase 41 violates this on purpose -- per `feedback_persist_paid_results_default`, every paid run must be preserved.

Implementation:
- Result file path is `tests/eval/ingestion/results/<corpus>-<UTC-iso>-<run-id>.jsonl`. Per-run unique. Never overwrites.
- Report path is `.planning/phases/41-ingestion-harness/41-EVAL-REPORT-<corpus>-<UTC-iso>.md`. Per-run unique. Never overwrites.
- Last-successful PASS report is symlinked or just listed as the canonical artifact via git log; no `41-EVAL-REPORT.md` short-name overwrite.

This pattern is captured in `compare-runs.js` (Plan 06): given two `*.jsonl` paths, diff per-fixture results and flag regressions.

## 6. Smoke-Before-Batch Pattern (Phase 38 Plan 09 reuse)

Phase 38 used `EVAL_MAX_FIXTURES=N` env to cap fixtures during smoke. Phase 41 promotes this to a first-class CLI flag:

- `--smoke` -- runs first 5 fixtures of the selected corpus (configurable via `EVAL_SMOKE_SIZE`, default 5).
- `--live` -- enables real Anthropic + Whisper calls. Default is mocked LLM (deterministic per-fixture-id JSON returns).
- `--corpus <synthetic|paper-log|audio|all>` -- selects loader(s).
- `--cap-usd <N>` -- aborts run when accumulated cost crosses N USD (default $20 per D-07).

The CLI lives at `src/agents/alerter/test/eval/ingestion/run-harness.js`. Invocation via `node run-harness.js --corpus paper-log --smoke --live`. Jest tests wrap the harness for CI (synthetic corpus only, mocked LLM).

## 7. Hand-Labeling Helper Feasibility

Operator must produce `expected.json` sidecars for ~24 `mushdatadump-prod/2026-05-12_inoc_santi/` drafts + 5 audio recordings. The pain is filling B7 log fields by hand for every fixture.

Two options:

**Option A: hand-write JSON.** Operator writes `expected.json` manually. ~5 min per fixture; total ~2.5 hours for 30 fixtures. No new code.

**Option B: bootstrap from a draft extraction + human review.** Operator runs the (paid) extractor once per fixture, hand-edits the JSON to correct errors, saves as `expected.json`. ~2 min per fixture if extractor is mostly right; pays for itself at 15+ fixtures.

Plan recommendation: ship Option A in Plan 04/05; Option B is a 50-line `tools/label-bootstrap.js` script captured as a "build only if it pays off" item in the RUNBOOK. The first ~5 hand-labels will reveal whether the extractor's output is close enough to bootstrap from.

## 8. Paired-Session Cross-Stream Pattern

Two paired sessions ship in v1.7 (D-05a):

1. **SHI inoc paired set:**
   - paper-log fixture: a JPEG of the operator's notebook page for a SHI inoc session (from `mushdatadump-prod/2026-05-12_inoc_santi/`, e.g. draft 7).
   - audio fixture: a recording of the operator narrating the same session at inoc time.
   - Both `expected.json` carry `session_id: "shi-inoc-2026-05-12-d07"`.

2. **Generic observation paired set:**
   - paper-log fixture: a JPEG of a colonizing observation log entry.
   - audio fixture: a recording of the operator describing the same observation.
   - Both `expected.json` carry `session_id: "obs-colonizing-<date>"`.

The harness groups results by `session_id`, normalizes drafts (strip `id`, `source_capture_ids`, `per_field_confidence`, whitespace in string fields), and deep-equals. Cross-stream score = `identicalPairs / totalPairs`. Ship-gate (D-05b): >= 1/2 pairs PASS.

## 9. Mocked LLM Mode (CI)

For CI without paid API:

```js
// fixtures/synthetic/<seq>-...-/mock-response.json   <-- optional sidecar
// If present, mocked extractor returns this verbatim.
// If absent, mocked extractor returns expected.json directly (trivial PASS).
// The point of mocked mode is to exercise the harness wiring + scorer + report
// generator, NOT to validate the extractor. Real validation runs under --live.
```

Mock-mode injects a fake `createExtractor` via dependency injection (harness already accepts factory). Same seam works for transcribe-client.

## 10. Cost Budgeting (D-07)

Phase 38 Plan 09 spent ~$1-5 per full mushdatadump run (Sonnet 4.6, prompt caching, image input). Phase 41 paper-log corpus same shape; expect $1-5 per `--corpus paper-log --live` run on mushdatadump v1.6 + mushdatadump-prod (~24 fixtures added => ~$2-3 extra). Audio corpus adds Whisper latency but no Anthropic cost on Whisper itself (Whisper is local GPU on elder-plops); extraction call on the transcript is the same Sonnet shape.

Cap default `$20` is comfortably above any single run; the cap exists to catch infinite-loop bugs, not to gate budget.

## 11. CI Integration

`src/agents/alerter/test/eval/ingestion/synthetic.test.js` -- Jest test in the same jest project as the extraction eval. Runs in CI on every push (no `ANTHROPIC_API_KEY` required because synthetic mode is mocked). PASS criterion: synthetic corpus runs end-to-end + scorer passes ship-gate.

`paperlog.test.js`, `audio.test.js`, `crossstream.test.js` -- present but skipped in CI (`describe.skip(...)`) because they require live API. Operator runs them on-demand from a shell with API keys + corpus paths set.

## 12. Validation Architecture (Nyquist)

(Surfaced for VALIDATION.md generation per workflow step 5.5.)

- **Sampling:** every harness run samples N fixtures across corpora. Synthetic = full corpus (~25 fixtures). Paper-log = full mushdatadump v1.6 (73) + mushdatadump-prod (~24). Audio = ~5 operator-supplied. Cross-stream = 2 paired sessions.
- **Signal floor:** sub-second per-fixture latency is not a Phase 41 concern; harness is offline.
- **Replay determinism:** mocked mode is fully deterministic. Live mode has Anthropic non-determinism; report carries model + timestamp + run-id so two runs against the same corpus are comparable via `compare-runs.js`.
- **Regression detection:** `compare-runs.js` diffs JSONL pairs and flags any fixture whose score dropped >5% or transitioned PASS->FAIL.

## 13. Risk Surface

- **Hand-labeling toil dominates the schedule.** Plan 04/05 specify "operator-deferred via RUNBOOK"; the harness ships ready to consume sidecars whenever they land. Phase 41 ship-gate is met when synthetic + mushdatadump v1.6 (already labeled) PASS; mushdatadump-prod is a stretch goal that gates the additional D-08a-equivalent criterion.
- **Audio corpus path is unknown.** RUNBOOK asks the operator both "where are the recordings" and "if there are none, what's the smallest first capture you can produce". If the answer is "no recordings exist yet", INGEST-03 ships as `human_needed`.
- **Cross-stream is the most ambitious bar.** Even 1/2 paired sessions is a v1 win. The harness produces a useful "divergence diff" output even when pairs FAIL, so the cross-stream report doubles as a debugging tool for the operator.
- **CONTEXT.md path mismatch** (Section 0) is the only material divergence from CONTEXT.md. No replanning required -- plans cite the corrected path.

## 14. Open Questions Resolved by Claude's Discretion

- **Test runner:** Jest, same project as Phase 38 (`jest.config.js` extension). New tests slot in alongside existing `mushdatadump.test.js`.
- **Hand-labeling tool:** Defer Option B (Section 7); ship Option A in Plan 04 + capture Option B as a 50-line script in the RUNBOOK if hand-labeling proves painful past fixture 5.
- **`expected.json` schema:** mirrors Phase 38 `signal_draft.draft` JSON plus the new keys `session_id?`, `provenance?` from Section 3.
- **mushdatadump-prod vendoring:** symlink + `.gitignore` (corpus dir is a `/mnt/mossrock/shared` mount; not in the repo).
- **Scorer changes for cross-stream:** new helper at `src/agents/alerter/test/eval/ingestion/cross-stream.js`; Phase 38 scorer untouched.

## 15. Wave Shape (informs planner)

- **Wave 0** (sequential, foundation): harness scaffolding + run-harness.js + dependency-injection seams + JSONL append-only writer + Jest project wiring.
- **Wave 1** (parallel-safe): synthetic corpus authoring + synthetic mock-mode test; paper-log loader integration (reuses Phase 38 fixtures-loader; new sidecar reader for mushdatadump-prod).
- **Wave 2** (parallel-safe): audio corpus loader + Whisper integration + smoke test; cross-stream consistency scorer + paired-session loader pairing logic.
- **Wave 3** (sequential, gates close): EVAL-REPORT generator with per-corpus tables + cross-stream column; compare-runs.js regression detector; RUNBOOK with operator hand-labeling instructions + audio-corpus discovery prompt + cost cap recipe.

## RESEARCH COMPLETE

Phase 41 is fixture-collection + harness scaffolding plus one new scorer dimension. The hardest engineering item is the cross-stream deep-equal-mod-whitespace helper (~50 LOC). The hardest operator item is hand-labeling, which is RUNBOOK-deferred. Existing Phase 38 scorer + report writer + fixture-loader patterns are reusable as-is. CONTEXT.md `tests/eval/extraction/` references should be read as `src/agents/alerter/test/eval/extraction/`.
