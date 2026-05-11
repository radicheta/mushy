
## Phase 37 Plan 03 — deferred items

### test/integration.test.js heartbeat_fires_and_bypasses_cap failure
- **Status:** pre-existing relative to Plan 03 start (introduced by commit 3bc11cb `fix(alerter): defer heartbeat when bridge summary is empty + null-safe rendering`)
- **Root cause:** That hotfix added "defer when bridge summary is empty" behavior; the integration test starts the alerter and immediately expects a heartbeat send without sending bridge data first.
- **Fix:** Either (a) push a bridge summary payload before waitFor, or (b) seed alerter state with a non-empty summary in the test. Out of scope for Plan 03 (does not relate to multi-farmer routing).

### test/config.test.js Test A — dashboardUrl drift
- **Status:** pre-existing (carried from Plan 37-01)
- **Root cause:** `config.js:87` default `http://100.96.10.66:8080/` no longer matches the test assertion `http://elder-plops-ts:8081/farmer`.
- **Fix:** One-line update — either fix the default or update the test. Bundle with next alerter PR.
