---
name: 999.51-mechanical-bridge-srvname-fix
quick_id: 260518-tcj
date: 2026-05-19
status: complete
backlog_ref: 999.51 (partial — mechanical fixes only)
---

# Quick Task 260518-tcj: 999.51 mechanical bridge srvName fix

## What

Pay down 2 of 6 stale test-debt failures from backlog 999.51 by re-aligning
`src/mission-control/bridge/test/control_experiment.test.js` with the live
un-namespaced service paths the bridge actually calls (per 2026-05-09 workaround
at `control_experiment.js:92-94`).

## Result

| Failure | Fix | Status |
|---|---|---|
| `makeStartHandler > happy path` srvName | `/fc_controller/start_experiment` -> `/start_experiment` | green |
| `makeCancelHandler > happy path returns 200 ok:true` srvName | `/fc_controller/cancel_experiment` -> `/cancel_experiment` | green |

`npx jest test/control_experiment.test.js` -- 31/31 passed.
Full bridge suite -- 234/236 passed; 2 remaining failures are pre-existing in
`burn_bar.test.js` (jimp v1 ESM dynamic-import / `--experimental-vm-modules`
config issue), unrelated to this change.

## Stale 999.51 entries discovered

While verifying scope, two of the 6 failures the backlog entry filed on
2026-05-11 were NOT reproducible against current main:

1. **alerter `test/config.test.js` (1 failure)** -- backlog claims `config.js:67`
   defaults to `http://100.96.10.66:8080/` but live `config.js:93` already has
   `http://elder-plops-ts:8081/farmer`, which is what the test expects.
   `npx jest test/config.test.js` -- 32/32 green. Likely fixed in a later
   commit between 2026-05-11 and 2026-05-19.

2. (Investigation not run) The 3 `alerter test/integration.test.js` failures
   the backlog attributes to Phase 29 mode-config drift could not be confirmed
   this session because the suite hangs past 120s (separate latent issue --
   process never returns; not the assertion-failure shape the backlog described).
   Needs supervised diagnosis: is the hang the same root cause as the original
   3 failures, or is it new since 2026-05-11?

## 999.51 status after this task

- 2 of 6 stale failures: paid down (this commit)
- 1 of 6: was already moot (alerter config -- no work needed)
- 3 of 6: blocked on diagnosing the alerter integration-suite hang; deferred
  for supervised pass

Backlog entry 999.51 should be re-scoped or partially closed -- see followup.

## Files changed

- `src/mission-control/bridge/test/control_experiment.test.js` (2 assertion
  updates + explanatory comments pointing at the live workaround)
