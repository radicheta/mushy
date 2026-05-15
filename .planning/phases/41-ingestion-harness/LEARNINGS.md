---
phase: 41-ingestion-harness
extracted: 2026-05-13
status: shipped (ship-gate met on synthetic + paper-log v1.6; INGEST-03/04 stretch human_needed)
---

# Phase 41 Learnings -- Ingestion Harness

## Decisions made

- **D-01 / D-01a / D-01b:** Single harness binary `run-harness.js --corpus <name>`. Three named corpora: synthetic, paper-log, audio. Single results JSONL per run at `tests/eval/ingestion/results/<corpus>-<timestamp>.jsonl` (append-only). Reuses Phase 38 scorer unchanged; cross-stream-consistency is a new dimension column.
- **D-02 / D-02a / D-02b:** Synthetic fixtures hand-crafted in `<seq>-<log_type>-<modality>/` directories with `input.json + attachment.{jpg,m4a} + expected.json`. Minimum 5 log_types x 3 modalities = 15 fixtures (corpus actually shipped at 25). CI-runnable on MOCKED LLM, no paid API in CI.
- **D-03 / D-03c:** Two paper-log sources: mushdatadump v1.6 (reuse existing CSV ground truth, do NOT re-hand-label) + mushdatadump-prod (operator hand-labeling required). Ship-gate at >=80% per-field exact-match on paper-log corpus.
- **D-04:** Audio fixture path is operator-supplied (path TBD at planning time); whisper via existing client.
- **D-05 / D-05b:** Paired fixtures share `session_id`. Cross-stream score = % of paired sessions producing identical writes mod whitespace. Ship-gate floor = >=1/2 (low bar by design; v1.8 raises it).
- **D-06 / D-06b:** Single Markdown report per run; append-only sibling to JSONL. Regression diff via `compare-runs.js` flags PASS->FAIL or >5% score drop.
- **D-07 / D-07a / D-07b:** Smoke-before-batch via `--smoke` flag (Phase 38 Plan 09 lesson). Budget cap `EVAL_COST_CAP_USD=20`. JSONL append-only per-call unique paths.
- **D-09a:** Phase ships on synthetic-PASS + paper-log-PASS. Audio + cross-stream are stretch; document missing operator-supplied corpora as `human_needed`, not `gaps_found`.

## Lessons learned

- **Most of the phase work is fixture curation, not code.** Harness runner is ~200 LOC; the heavy lift is hand-labeling. Phase scope estimation must weight fixture-gathering at operator-time, not engineer-time.
- **Reusing Phase 38 scorer unchanged was a clean win.** No new scorer code; cross-stream is a separate module per CONTEXT D-01b. Phase 38 Plan 09 PASS attestation byte-identically inherited.
- **Stretch goals collapsed cleanly to `human_needed`.** INGEST-03 (audio) and INGEST-04 (paired sessions) both ship as wired harness + skipped test honoring an env var. Operator can promote them later by supplying corpus; if not, they enter v1.8 backlog. No blocker.
- **No re-hand-labeling rule (D-03) saved hours.** mushdatadump v1.6 ground truth is reused via `loadPaperLogCorpus`; the harness adapter is a wrapper, not a new dataset.
- **`EVAL_RUN_LIVE=1` un-skip pattern** for live-API tests keeps CI cheap while preserving the operator path. Same shape as Phase 38 `npm run eval:extraction`.

## Patterns worth reusing

- **`--smoke` flag = 5-fixture canary before full batch.** Phase 38 Plan 09 forged the cost-domain-agnostic rule; Phase 41 adopted it as a first-class harness mode.
- **JSONL append-only per-run unique paths via shared `jsonl-writer.js` helper.** Centralizes the `feedback_persist_paid_results_default` rule so no future caller can accidentally overwrite.
- **`EVAL_COST_CAP_USD` runtime budget cap.** Defensive backstop in case smoke didn't catch a runaway extractor.
- **Symlink-or-gitignore corpus mounts.** Don't vendor multi-GB fixture corpora; symlink `/mnt/mossrock/shared/mushdatadump-prod/` and gitignore.
- **Coverage-matrix planning at fixture level:** 5 log_types x N modalities. Makes gaps in test surface legible.
- **Stretch-goal-as-skipped-test wiring.** Test file exists, env-var-honored, marked skipped-by-default. Promotes to operator-runnable without code change.

## Surprises

- **37 PASS / 5 skipped / 0 failed in CI** with zero live-API spend. Phase 41's CI shape is the cleanest of the v1.7 phases because the cost-isolation discipline was inherited from Phase 38, not re-invented.
- **Operator-supplied corpora ended up being the entire critical path.** The phase delivered everything except the data it can't generate. Genuine human-needed, not engineering-needed.
- **No new scorer code needed.** The Phase 38 scorer was general enough; cross-stream is a deep-equal-mod-whitespace assertion plus a session-id group-by, ~30 LOC.

## Open threads

- **Hand-label `mushdatadump-prod/2026-05-12_inoc_santi/`** (~24 drafts) -- required for full INGEST-02. Operator.
- **Supply audio corpus path + hand-label >=5 recordings** -- required for INGEST-03. Operator.
- **Supply >=2 paired-session inputs** (same event captured as paper-log photo AND audio) -- required for INGEST-04. Operator.
- **Run `--live` paper-log smoke + full** (paid; ~$2-5 expected) per RUNBOOK section 2.
- **All four items defer to v1.8 if unsupplied by v1.7 ship.**
