
## Phase 37 Plan 03 — deferred items

### ~~test/integration.test.js heartbeat_fires_and_bypasses_cap failure~~ — RESOLVED
- Originally introduced by commit 3bc11cb (heartbeat deferral on empty bridge summary).
- **Resolved post-Plan-03:** test now dispatches `heartbeat_tick` directly with a populated summary, matching the test's actual intent (validate cap=0 doesn't suppress heartbeat sends). Suite back to 268/269 with only the dashboardUrl drift remaining.

### test/config.test.js Test A — dashboardUrl drift
- **Status:** pre-existing (carried from Plan 37-01)
- **Root cause:** `config.js:87` default `http://100.96.10.66:8080/` no longer matches the test assertion `http://elder-plops-ts:8081/farmer`.
- **Fix:** One-line update — either fix the default or update the test. Bundle with next alerter PR.
