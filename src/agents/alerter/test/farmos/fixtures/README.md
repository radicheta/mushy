# Phase 40 farmOS-write fixtures

## Layout

- `curated/*.json` -- 7 hand-crafted scenarios covering all 5 B7 log types
  + idempotency replay + unsupported log_type. No `_provenance` block.
- `prod-confirmed-draft.json` -- the **ship-gate witness** (single fixture).

## prod-confirmed-draft.json

Real-prod confirmed draft snapshot derived from
`/mnt/mossrock/shared/mushdatadump-prod/2026-05-12_inoc_santi/`. This is
the Phase 40 ship-gate witness per memory
`feedback_real_data_before_ship_gate_pass.md`.

Phase 38 was re-opened on 2026-05-12 after a "curated-only PASS" was
retracted the same hour when real prod data ran 0/4 through the live
pipeline (whisper 500 + schema_invalid). Phase 40 will not repeat that
mistake: at least one integration-test scenario in this directory MUST
trace back to a real session under `/mnt/mossrock/shared/mushdatadump-prod/`
and drive the same commit pipeline that production drives.

### Relationship to the Phase 39 fixture

The Phase 39 fixture `src/agents/alerter/test/confirm/fixtures/prod-draft-awaiting.json`
is the same source session but in `status=awaiting_farmer` (the Phase 39
input contract). The Phase 40 fixture above is in `status=confirmed` (the
Phase 40 input contract). Conceptually it represents the same draft
after Phase 39 confirms.

### Field substitution policy

Real phone numbers are replaced with the synthetic `+15550001234` form.
Capture ULIDs are replaced with `cap-prod-fixture-*` prefixes. Production
identifier strings (batch names, block names, QR codes) are preserved
because they are not PII -- they are operational identifiers required to
make the integration test exercise the real commit path. Farmer
free-text notes are redacted of names.

### Refresh procedure

When a newer prod session becomes the canonical reference, the operator
pulls a fresh confirmed row from Timescale, applies the same redaction,
and commits a new fixture with a date suffix (e.g.
`prod-confirmed-draft-2026-06.json`) rather than overwriting the existing
one (memory: `feedback_keep_paper_trail_of_intermediates`).

SQL recipe to regenerate from the prod alerter DB:

```sql
SELECT row_to_json(d) FROM signal_draft d
 WHERE status='confirmed'
   AND confirmed_at > '2026-05-12'
   AND log_type='seeding'
 ORDER BY confirmed_at LIMIT 1;
```

Save output to a `.json` file, then manually:
1. Replace `sender_e164` with `+15550001234`
2. Replace `source_capture_ids` array with `cap-prod-fixture-*` prefixes
3. Add a `_provenance` block at the top documenting the substitutions
4. Re-encode names in `notes` if needed

## Memory pins

- `feedback_real_data_before_ship_gate_pass.md`
- `project_phase38_production_logs_available.md`
- `feedback_keep_paper_trail_of_intermediates.md`
- `feedback_persist_paid_results_default.md` (applies to any live-LLM
  workflow that touches the integration suite; v1 commit pipeline does
  not call paid LLMs but Phase 41 cross-stream replay might)
