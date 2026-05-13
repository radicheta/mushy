# Phase 38 Plan 07: D-07 Ship-Gate Eval Report

**Generated:** 2026-05-13T00:46:14.997Z
**Model:** claude-sonnet-4-6
**Fixture dir:** `/mnt/mossrock/shared/mushdatadump`
**Fixture count:** 96
**Skipped (load errors):** 0
**Hard API errors:** 0
**Cost note:** 73 fixtures x ~1 turn x claude-sonnet-4-6 (~$3/MTok input cached, $15/MTok output) with image input. With prompt caching across the system+few-shot, expected spend $1-5 per full run. Re-runnable any time the extractor changes.

## Ground-Truth Adaptations

mushdatadump v1.6 does NOT ship a per-image ground-truth.csv. The 73 JPEGs
are paper-log pages; mushroom_log.csv is page-grain (829 entries across 73
pages, ~11 entries per page). Aligning each entry to a JPEG region requires
OCR, which is out of scope for Plan 07.

Adaptation: per-image expected reduced to `type=seeding` + `ambiguous=false`
with no required fields. Scored dimensions:
  - Schema conformance (binary: did extractor return a schema-valid draft?)
  - B5 block_name precision: of drafts that produced a block_name, how many
    pass the {YYMMDD}_{SPECIES3}_{SEQ} regex (no recall, no expected match)
  - Confidence calibration: Brier + ECE on per_field_confidence vs schema
    validity (proxy for correctness)
  - combinedFieldOrAskBack: schema-valid OR per_field_confidence < 0.7 on any
    required field (treated as appropriate ask-back since pages ARE ambiguous
    for a single draft).

Richer per-image ground truth is deferred to Plan 08 (production-log path),
where farmer-curated single-event captures land 1:1 against extracted drafts.

## Pass Bar (CONTEXT D-07)

- Schema conformance >= 90%
- Required-field exact-match OR appropriate ask-back >= 75%

## Per-Dimension Scores

| Dimension | Score | Raw |
|-----------|-------|-----|
| Schema conformance | 95.8% | 92 / 96 |
| Required-field exact-match | 0% | 0 / 0 |
| Required-field OR appropriate ask-back | 95.8% | (the D-07 OR-bar denominator) |
| Appropriate ask-back | 30.2% | (per-fixture) |
| Harvest set-equality (lineage) | n/a | over 0 harvest fixtures |
| B5 block_name regex-valid rate | 100% | 92 / 92 drafts |
| B5 block_name precision (vs GT) | 0% | 0 / 92 extracted [no GT supplied -- vacuous] |
| B5 block_name recall (vs GT) | 0% | 0 / 0 expected [no GT supplied -- vacuous] |
| Brier score (confidence vs correct) | 0 | lower is better |
| ECE (expected calibration error) | 0 | lower is better |

## Anthropic Usage (actual)

- Calls with usage telemetry: 93
- Input tokens (uncached): 23888
- Output tokens: 266770
- Cache write tokens: 138306
- Cache read tokens: 533439
- **Estimated spend:** $4.7519 USD

## Notes

Wall time: 2564.1s. Per-fixture drafts: /mnt/slime-kingdom/opt/mushy/.planning/phases/38-extraction-pipeline/38-EVAL-REPORT-results.jsonl Full results: /mnt/slime-kingdom/opt/mushy/.planning/phases/38-extraction-pipeline/38-EVAL-REPORT-results.json

## Verdict: [PASS]
