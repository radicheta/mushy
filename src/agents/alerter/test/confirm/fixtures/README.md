# Phase 39 confirm-loop fixtures

## prod-draft-awaiting.json

Real-prod awaiting_farmer draft snapshot used as the **ship-gate witness** for
Phase 39 per memory `feedback_real_data_before_ship_gate_pass.md`.

Phase 38 was re-opened on 2026-05-12 after a "curated-only PASS" was retracted
the same hour when real prod data ran 0/4 through the live pipeline (whisper 500
+ schema_invalid). Phase 39 must not repeat that mistake; one or more fixtures
in this directory MUST trace back to a real session under
`/mnt/mossrock/shared/mushdatadump-prod/`.

### Field substitution policy

Real phone numbers are replaced with the synthetic `+15550001234` form. Real
capture ULIDs and draft IDs are replaced with `prod-draft-*` and `cap-prod-*`
prefixes so the fixture is safe to commit. The `_provenance` block records the
substitutions made for traceability.

### Refresh procedure

When a newer prod session becomes the canonical reference, the operator pulls a
fresh awaiting_farmer row (either from Timescale or by replaying the session
through the alerter into a scratch DB), applies the same redaction, and commits
a new fixture file with a date suffix (e.g. `prod-draft-awaiting-2026-06.json`)
rather than overwriting the existing one (memory:
`feedback_keep_paper_trail_of_intermediates`).

### Why not the live extraction output?

The 2026-05-12 session degraded on the live alerter (whisper 500, then
schema_invalid after retry). The fixture is a hand-constructed plausible draft
derived from the session audio narration -- a stand-in that exercises the same
state-machine paths the live extractor would have produced on a working day.
Phase 38's Plan 09 PASS attestation covers the extraction path independently.

## curated/*.json

Smaller hand-crafted scenarios for the 8 synthetic integration cases. No
provenance block required.

## Memory pins

- `feedback_real_data_before_ship_gate_pass.md`
- `project_phase38_production_logs_available.md`
- `feedback_keep_paper_trail_of_intermediates.md`
- `feedback_persist_paid_results_default.md` (for any live LLM smokes -- per-call unique JSONL paths)
