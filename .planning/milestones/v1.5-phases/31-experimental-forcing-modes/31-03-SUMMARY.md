# Plan 31-03 Summary — Bridge wiring: experiment endpoints + DB migration + topic subscriber

**Status:** code complete, jest 48/48 GREEN. Task 4 (end-to-end live smoke) deferred to deploy.

## What was built

### `src/mission-control/bridge/src/control_experiment.js` (NEW)

Single module owning the entire bridge surface for Phase 31:

- **HTTP layer:**
  - `validate(name, duration_minutes)` — name allowlist {force-condensation, force-evaporation}; duration must be Number.isInteger in [1, 120]; defaults to 15 when omitted (CONTEXT D-14).
  - `makeStartHandler(rosNode, opts)` — POSTs body through validator, calls `/fc_controller/start_experiment` via `_callService` (Promise + timeout). Maps controller `ok:true` → 200 with `{ok, started_at_iso, reverts_at_iso, prior_mode}`; `ok:false` → 400 with `{ok:false, error}`. Timeout → 504, createClient throw → 500, null rosNode → 503.
  - `makeCancelHandler(rosNode, opts)` — same shape; CancelExperiment has empty request body. `no_experiment_active` → 400.
  - `makeStateHandler(opts)` — GET handler returning `{active:false}` when cached event is null/non-`started`, else `{active:true, experiment, prior_mode, started_at_iso, reverts_at_iso, requested_minutes, seconds_remaining}` with server-computed `seconds_remaining = max(0, floor((reverts_ms - now)/1000))`.

- **DB layer:**
  - `migrateExperimentSchema(pool)` — issues idempotent `CREATE TABLE IF NOT EXISTS fc_experiments` (11 columns matching CONTEXT D-21 verbatim) + `CREATE INDEX IF NOT EXISTS idx_fc_experiments_started_at ON fc_experiments(started_at DESC)`.
  - `makeExperimentEventHandler({pool, getLastRh, setLastEventCache, broadcast, logger})` — async handler routes JSON payloads:
    - `started` → INSERT row with baseline_rh = getLastRh() (NULL-safe).
    - `ended | cancelled | truncated` → SELECT most-recent open row (`ended_at IS NULL ORDER BY started_at DESC LIMIT 1`), UPDATE with `ended_at=NOW()`, `actual_min`, `final_rh = getLastRh()`, `delta_rh = final_rh - baseline_rh` (NULL-safe per D-23), `end_reason` from `END_REASON_MAP`.
    - Unknown event / null payload / DB throw → log warn, never propagate (subscription thread crash-resistance).
  - `END_REASON_MAP = {ended: 'timeout', cancelled: 'cancelled', truncated: 'truncated_by_restart'}`.

### `src/mission-control/bridge/src/index.js`

Pure wiring (no new logic):

- `require('./control_experiment')` import next to control_param + control_persist.
- `lastExperimentEventBroadcast` cache var declared next to `lastModeBroadcast` family.
- WS `connection` block pushes the cached event after the alerter family blocks.
- Three endpoint registrations next to `/control/persist`: POST `/control/experiment`, POST `/control/cancel-experiment`, GET `/control/experiment`. All three hit lazy handler-factory wrappers + return 503 if rosNode null. State handler unwraps the `{topic, value}` envelope to feed inner JSON to `makeStateHandler`.
- `initDb()` calls `await control_experiment.migrateExperimentSchema(pool)` after the snapshots index DDL.
- rclnodejs subscription on `/fc1/control/experiment_event` (`std_msgs/msg/String`, TRANSIENT_LOCAL via reused `humidifierQos`). Handler factory wired with `getLastRh: () => (latestTelemetry.humidity != null ? latestTelemetry.humidity.value : null)` (note: bridge stores RH as percent already from the humidity subscriber × 100). `setLastEventCache` writes the wrapped envelope to `lastExperimentEventBroadcast`. `broadcast` fans out via the existing `broadcast()` helper.

## Tests (NEW)

- `test/control_experiment.test.js` — 32 tests covering `validate`, `makeStartHandler`, `makeCancelHandler`, `makeStateHandler`. All shapes from the plan: happy-path, default duration, invalid inputs (name + duration), controller rejection propagation, timeout → 504, createClient throw → 500, null rosNode → 503, idle/active state derivation, seconds_remaining floor.
- `test/experiment_event_subscriber.test.js` — 16 tests covering migration idempotency, INSERT-on-started (baseline_rh, NULL-safe), UPDATE-on-{ended,cancelled,truncated} with end_reason mapping, NULL-safe delta_rh in both directions, no-open-row warn-only path, malformed payload defenses, DB-throw swallow.

**Result: 48/48 PASS.** Full bridge `npx jest` — 234/236 PASS; the 2 failures are pre-existing burn_bar/jimp library issues unrelated to Phase 31 (verified by checking the error trace points to `node_modules/@jimp/core/src/index.ts:345`).

## Verification

- jest: 48 new + 186 existing = 234 PASS, 2 pre-existing burn_bar failures (unrelated).
- `node --check src/index.js` — syntax OK.
- Static greps satisfied: `control_experiment` in index.js = 6 (require + 3 endpoint factories + migrate + makeExperimentEventHandler), `fc_experiments` in module = 8, `fc1/control/experiment_event` in index.js = 4.

## Deferred — Task 4 (live smoke)

End-to-end smoke against fc1 + bridge container is a deploy gate. Steps captured in 31-03-PLAN.md §Task 4:
1. `colcon build --packages-select fc_msgs fc_core` on fc1, restart fc-core.
2. `docker-compose up -d --build bridge` from repo root on elder-plops.
3. `docker-compose exec timescale psql ... -c "\d fc_experiments"` confirms 11-column schema.
4. `curl -X POST http://localhost:8080/control/experiment -d '{"name":"force-condensation","duration_minutes":1}'` → 200 ok, then `curl http://localhost:8080/control/experiment` shows `active:true` with seconds_remaining > 0; wait 70s and confirm DB row updated with end_reason='timeout', actual_min ≈ 1.0, baseline_rh / final_rh / delta_rh populated.
5. Cancel-mid-flight + validation reject curl checks per Task 4.

This is a blocking human checkpoint per phase posture (operator preflight required before any fc1 remote action).

## Hand-off to Plan 31-04

Bridge endpoints are stable:
- `POST /control/experiment` `{name, duration_minutes}`
- `POST /control/cancel-experiment` `{}`
- `GET /control/experiment`

Plan 31-04's Signal command parser POSTs to these via the existing bridge HTTP transport (alerter already proxies through bridge for WS broadcast).
