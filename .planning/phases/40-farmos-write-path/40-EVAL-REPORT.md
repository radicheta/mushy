# Phase 40 EVAL-REPORT -- farmOS Write Path

**Status:** PENDING_RUN (awaiting FARMOS_INTEGRATION=1 attestation against
live dev-farmOS).

This document records the pass/fail per integration scenario with concrete
on-disk artifact paths so verification can confirm ship-gate evidence is
present.

---

## Scenario coverage matrix

| # | Scenario             | Fixture path                                                      | Requirement(s)         | farmOS-side asserted                              | Alerter-side asserted                                     | Status      |
|---|----------------------|-------------------------------------------------------------------|------------------------|---------------------------------------------------|-----------------------------------------------------------|-------------|
| 1 | seeding-happy        | `test/farmos/fixtures/curated/seeding-happy.json`                 | FOS-02, FOS-03, FOS-04 | 2 assets (batch + block) + 1 seeding log + QR bind| status=committed; farmos_response.asset_ids.length==2     | PENDING_RUN |
| 2 | activity-water       | `test/farmos/fixtures/curated/activity-water.json`                | FOS-03, FOS-04         | 0 new assets + 1 activity log on existing asset   | status=committed; log_ids.length==1                       | PENDING_RUN |
| 3 | input-recipe         | `test/farmos/fixtures/curated/input-recipe.json`                  | FOS-03                 | 1 input log + ingredients-in-notes serialization  | status=committed; notes contains both ingredient lines    | PENDING_RUN |
| 4 | observation-photo    | `test/farmos/fixtures/curated/observation-photo.json`             | FOS-03, FOS-05         | 1 observation log + 1 file uploaded + log.file ref| status=committed; file_ids.length>=1                      | PENDING_RUN |
| 5 | harvest-multi-bag    | `test/farmos/fixtures/curated/harvest-multi-bag.json`             | FOS-02, FOS-03, FOS-04 | 1 batch + 3 bag assets + 1 harvest log            | status=committed OR commit_failed=missing_source_block    | PENDING_RUN |
| 6 | idempotency-replay   | `test/farmos/fixtures/curated/idempotency-replay.json`            | FOS-01                 | First call writes; second tickOnce zero POST      | farmos_response populated; cache short-circuits           | PENDING_RUN |
| 7 | unsupported-logtype  | `test/farmos/fixtures/curated/unsupported-logtype.json`           | FOS-01                 | NO farmOS POST issued                             | status=commit_failed; reason=unsupported_log_type         | PENDING_RUN |
| 8 | **SHIP GATE: prod**  | `test/farmos/fixtures/prod-confirmed-draft.json`                  | FOS-01..FOS-06         | batch + block + seeding log + QR bind             | status=committed; farmos_response populated; audit JSONL  | PENDING_RUN |

Scenario 8 is the load-bearing ship-gate witness per memory
`feedback_real_data_before_ship_gate_pass.md`. Curated-only PASS is
INSUFFICIENT.

Every FOS-* requirement (FOS-01..FOS-06) appears in at least one row above.

---

## Ship-gate criteria

All four of these must hold for status to flip from PENDING_RUN to PASS:

1. **All 8 scenarios run.** No describe.skip in the final report run.
2. **All 8 scenarios PASS.** Scenario 5 is allowed to PASS with the
   `commit_failed` branch when dev-farmOS lacks pre-existing source blocks;
   document which branch was exercised in section "Run record" below.
3. **Prod-fixture witness is non-skipped** and lands `commit_success` with
   asset_ids + log_ids populated.
4. **Operator-logged run output is pasted under "Run record"** -- includes
   the timestamp, the FARMOS_URL the run hit, and the jest pass/fail summary.

---

## Run record (filled in by verifier or operator at ship time)

```
Run timestamp:    <YYYY-MM-DDTHH:MM:SSZ>
FARMOS_URL:       <http://10.68.155.50:18080 or prod host>
asset_link module: <present | absent (fallback)>
Jest summary:     <e.g. Tests: 8 passed, 8 total>
Scenario 5 branch: <committed | commit_failed: missing_source_block>
Audit JSONL path: <e.g. /tmp/phase40-run-20260513-1430.jsonl>
Operator:         <name>
Sign-off:         <PASS | FAIL with notes>
```

---

## Audit JSONL snapshot recipe

Capture the per-event audit trail for the run-record artifact:

```bash
FARMOS_INTEGRATION=1 \
TIMESCALE_HOST=... TIMESCALE_PASSWORD=... \
FARMOS_USERNAME=... FARMOS_PASSWORD=... \
  npx jest test/farmos/integration.test.js 2>&1 \
  | grep -E '^\{' \
  > /tmp/phase40-run-$(date +%Y%m%d-%H%M).jsonl
```

Then `jq` over that file to verify per-event counts:

```bash
jq -r '.event' /tmp/phase40-run-*.jsonl | sort | uniq -c
# Expected: commit_attempt N, commit_success M, commit_failed K (with M+K==N)
```

---

## Deferred items

Carried over from `40-CONTEXT.md` `<deferred>` block:

- Prod-farmOS write switch (env-flip + RUNBOOK section 5; awaits
  `farmos_asset_link` install in prod)
- Mission Control telemetry topic (D-06b stretch goal)
- Asset attribute updates (rename, re-tag, re-parent) -- v1.8 question
- Bag QR pre-binding before harvest
- Bulk paper-log-mode commit (Phase 41 / v1.8)
- Farmer-side `/retry <draft_id>` command
- Cross-domain farmOS writes (livestock, trees)
- Per-write farmOS audit-trail dashboard (D-06a SQL recipe is the ship-gate)

Emerged during execution:

- `requeueForRetry` now PRESERVES `committed_at_attempt` (vs original Plan
  01 spec that nulled it). The watchdog pre-lock backoff gate (Plan 05)
  needs the previous-attempt timestamp; `releaseStaleLocks` is the sole
  NULLer (crash recovery only). Documented in commit-db header + Plan 05
  commit message.

---

## Provenance footer

Eval report initialized 2026-05-13 by `/gsd:execute-phase 40 --no-transition`.
Status: PENDING_RUN until the first `FARMOS_INTEGRATION=1` attestation is
recorded above.
