---
phase: 40-farmos-write-path
extracted: 2026-05-13
status: code-complete pending live attestation; dev-smoke FAIL surfaced 3 blockers, 2 fixed live, 1 (taxonomy seeding) operator-owned
---

# Phase 40 Learnings -- FarmOS Write Path

## Decisions made

- **D-01 / D-01a / D-01b:** New JS client in the alerter codebase (not the Python farmos-agent). Same session-cookie auth + X-CSRF-Token + 10s timeout shape as the Python client; credentials reuse the existing `FARMOS_URL / FARMOS_USERNAME / FARMOS_PASSWORD` env triple.
- **D-02 / D-02a / D-02b:** Idempotency key = `signal_draft.id` (deterministic sha256 from Phase 38). Read-back-first commit pattern: check `signal_draft.farmos_response IS NOT NULL` before any POST. NO farmOS-side dedup query during commit -- local cache is source-of-truth.
- **D-03 / D-03a / D-03c:** One JS file per B7 log type (`commit-seeding.js`, `commit-activity.js`, `commit-input.js`, `commit-observation.js`, `commit-harvest.js`). Dispatch via `commit-router.js`. Assets created lazily during log commit (no separate asset registry). Native-type-only enforcement is defense-in-depth.
- **D-04 / D-04a:** Bind QR via `farm_id_tag` field. Probe `/api/asset_link/farmos_asset_link` once at startup; on 404, log WARN and use fallback `filter[farm_id_tag.qr_code]` path. **`farmos_asset_link` module install is operator-deferred** -- fallback is the live path on dev.
- **D-05 / D-05a / D-05b:** Two-step file-entity upload (POST file -> PATCH log with relationship). Skip on missing files (WARN, do not fail commit). No re-encoding, no thumbnailing -- bytes as-is.
- **D-06 / D-06a:** Audit = one JSONL line per commit (13 keys) + `signal_draft_event` row + canonical SQL recipe in RUNBOOK. No new dashboard.
- **D-07 / D-07a / D-07b:** Status transitions `confirmed -> committing -> committed | commit_failed`. Retry 3x exponential (1s/4s/16s) on 5xx + network errors; 4xx is terminal. `commit_failed` rows are recoverable via SQL flip back to `confirmed`.

## Lessons learned

- **Smoke v1 caught what 92 unit tests didn't: `fungi_type` is a required *relationship* on `asset--fungi` and was missing entirely.** This is the third concrete instance of `feedback_real_data_before_ship_gate_pass` paying off. 92/92 unit-PASS did not mean the dev-farmOS would accept the payload.
- **Two sub-bugs in one HTTP 422:** (a) `createFungiAsset` never set `fungi_type`. (b) `fungi_type` is a relationship to `taxonomy_term--fungi_type`, NOT an attribute. The first JSON:API error masked the second; manual repro via `node -e ...` was needed to see the full response body.
- **Dev-farmOS taxonomy was underseeded** -- a real blocker the schema lock document had not surfaced. `species` bundle was a 404; `fungi_type` had only the misplaced "SHI" term. **Lesson: locking a schema in a strawman doc is not the same as locking it in the live instance.** A future phase-pattern should include a "taxonomy seed protocol" in the Phase boundary doc -- check the instance, not the spec, before code-complete.
- **Misleading error-code:** `species-cache.js` would never have returned `species_not_found` on dev-farmOS because the GET returns HTTP 404 from routing (bundle absent), which client classified as `http_404`. "Not-found row" vs "not-found bundle" needed disambiguation. Backlog C fix landed live.
- **Smoke v2 (post-fix) surfaced the next legitimate blocker cleanly.** `fungi_type_not_found` precision error showed the new code path works; only the dev-farmOS data-state remains. Iterative smoke is the loop.
- **Retry classifier wasted cycles on deterministic failures.** `fungi_type_not_found`, `species_not_found`, and `missing_fungi_type_name` retried 3x despite being non-retryable. Filed as future optimization (non-urgent).
- **Live-API smoke surfaced bugs in *7 minutes* that unit tests would not have caught at any spend level.** Reinforces the "smoke before paid batch" + "real-data ship-gate" two-step.

## Patterns worth reusing

- **Read-back-first commit (local idempotency cache).** Don't re-query the remote system for dedup; cache the response locally and short-circuit. Cheaper, faster, survives remote-schema changes.
- **`committing` intermediate state to prevent parallel double-commits.** Set atomically with `committed_at_attempt`. A watchdog or duplicate trigger cannot launch a second chain.
- **Stale-lock release with timeout SQL guard:** `committed_at_attempt < now() - $1 minutes` releases stuck `committing` rows. Tested in `commit-watchdog.test.js` "stale lock release emits commit_stale_released audit per id".
- **Feature-probe-and-fallback at startup.** `farmos_asset_link` lazy probe -- one HTTP call, cached, switches client behavior globally. Pattern reusable for any optional module-presence detection.
- **Plan-as-atomic-commit naming:** `plan(40-NN task M): <summary>`. Bisectable.
- **Per-log-type module + dispatch router.** Closed set of 5 B7 types -> 5 commit modules + 1 router with static-guard. Easy to test in isolation, easy to extend.
- **Reverse-reproduce 422 via `docker compose exec alerter node -e ...` using the alerter's own client.** Faster than logging-everywhere; reuses production auth + retry classifier.

## Surprises

- **All 9 Phase 40 env vars added to compose passthrough on first commit.** The `feedback_compose_env_passthrough_not_envfile` lesson (Phase 36 hourly-false-alarm bug) is now muscle memory.
- **No em-dashes in any of Plan 40-01..08 source / RUNBOOK / EVAL-REPORT.** Em-dash grep returns 0 across the phase. Style-pin compliance from the start of the autonomous run.
- **Dev-farmOS instance state was further from the spec than the schema lock implied.** Operator (or farm team) has dev-farmOS provisioned but not seeded. Spec lock at 2026-05-11 + dev-instance reality at 2026-05-13 had drifted.
- **Live attestation was the *first* thing to flush bugs out of the code-complete phase**; unit-level was 92/92 PASS with no signal that anything was wrong. Without the dev smoke, ship-gate would have been declared and prod-flip would have hit the same wall.

## Open threads

- **Backlog B (operator-side):** dev-farmOS taxonomy seeding -- create `species` bundle; populate `fungi_type` with `batch`/`block`/`bag`; populate `substrate_type` from schema lock. Sole remaining ship-gate blocker per smoke v2.
- **Live FARMOS_INTEGRATION=1 dev-farmOS run** -- 8 integration scenarios incl. scenario 8 SHIP GATE prod-fixture. Requires operator credentials + dev-farmOS reachable + scenario-5 QR pre-seeds.
- **Live-farmer UAT** -- Signal-to-farmOS round-trip, same operator-deferred pattern as Phase 25/37/39.
- **Prod-farmOS env-flip** -- gated on farm team installing `farmos_asset_link` in prod.
- **Retry classifier optimization** -- treat `*_not_found` reasons as non-retryable to skip wasted cycles. Non-urgent.

## Commits referenced

- `c12c94c` (Plan 01) -- commit-db schema + config + compose env passthrough
- `e2fdddd` (Plan 02) -- farmos/client.js auth + retry + 401 reauth + asset_link probe
- `a085c32` (Plan 06) -- startup wiring + capturePathsFor + smoke
- `7d5fd78` (Plan 08) -- 40-RUNBOOK + 40-EVAL-REPORT scaffolds
- `6b8f1a9` -- Backlog A + C fixes (fungi_type plumbing + 404 classification) shipped live mid-smoke
