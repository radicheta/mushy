# Phase 63 — Plan 08 Summary

**Status:** COMPLETE
**Date:** 2026-07-25
**Branch:** `feat/phase-63-chamber-alerter`

---

## What shipped

### Task 1 — ChamberService + composite-dispatch factory
**Commit:** `5e58d31` — `feat(63): compose the chamber service and the D-05 composite dispatch`

- `farm_agent/chamber/service.py`: `ChamberService` (`handle_event`, `perform`,
  `on_event`, `apply_snooze`, `get_summary`, `start`, `stop`) plus the standalone
  `make_composite_dispatch` factory and `EVAL_TICK_INTERVAL_S`.
- `tests/chamber/test_service_wiring.py`: 12 tests.

**RED observed:**
```
ImportError while importing test module '.../tests/chamber/test_service_wiring.py'.
E   ImportError: cannot import name 'service' from 'farm_agent.chamber'
```

### Task 2 — boot.py wiring
**Commit:** `c6f2dc0` — `feat(63): wire the chamber alerter into boot`

- `chamber_config = load_chamber_config(os.environ, tenant_config=config)`
- `SignalClient(..., get_max_sends_per_hour=lambda: chamber_config.max_sends_per_hour)`
- `ChamberService` + `make_composite_dispatch` constructed before the loop;
  `ReceiveLoop(..., dispatch=chamber_dispatch)` — still exactly one of each.
- `await chamber_service.start()` after `receive_loop.start()`;
  `await chamber_service.stop()` first in the shutdown block.
- One lifecycle-only log line: `"chamber alerter live"`.
- 5 further tests appended (17 total).

**RED observed** — exactly the three the plan predicted, with the D-05 regression
guard already green:
```
test_boot_constructs_exactly_one_receive_loop            PASSED  (regression guard)
test_boot_wires_the_rate_cap_hook                        FAILED
test_boot_uses_the_composite_dispatch_not_the_bare_pipeline FAILED
test_boot_cancels_chamber_tasks_on_shutdown              FAILED
test_boot_does_not_log_chamber_config_fields             PASSED
```

---

## Verification (the four items the plan asked this summary to record)

### 1. Did `tests/test_boot.py` run or skip?

**It RAN, and passed 4/4** — not skipped. Rather than accept the skip, I started an
ephemeral `postgres:14` on port 5434 with the credentials `tests/conftest.py`
expects (`POSTGRES_PASSWORD=test`, `POSTGRES_DB=test_farm_agent`; my first attempt
used the wrong password and failed auth):

```
tests/test_boot.py::test_boot_completes_in_5s                                PASSED
tests/test_boot.py::test_boot_logs_no_secrets                                PASSED
tests/test_boot.py::test_boot_commit_watchdog_created_when_farmos_integration_true  PASSED
tests/test_boot.py::test_boot_commit_watchdog_not_created_when_farmos_integration_false PASSED
4 passed in 20.60s
```

This matters more than a green unit test: `test_boot_completes_in_5s` actually
runs `boot.main()` end to end, so the chamber wiring (ChamberConfig load,
ChamberService construction, `chamber_service.start()` spawning three tasks, and
`chamber_service.stop()` on shutdown) is proven to boot and shut down cleanly
inside the real daemon — and `test_boot_logs_no_secrets` proves the new log line
leaks nothing. The container was removed afterwards.

### 2. Full-suite counts

| Run | Result |
|-----|--------|
| **Canonical (no test DB — the normal CI path)** | **842 passed, 36 skipped, 0 failed** |
| With the ephemeral DB up | 872 passed, 3 skipped, **3 failed** (all pre-existing, see below) |
| `tests/chamber/` | 150 passed |
| `tests/chamber/test_service_wiring.py` | 17 passed |

### 3. Was `lint-imports` non-vacuous?

**Yes.** `farm_agent/chamber/` now exists on disk (confirmed by `ls -d`), so the
`forbidden_modules = farm_agent.chamber` contract has a real target for the first
time. Final run: **`Contracts: 1 kept, 0 broken`**. The Plan 01 gate is now doing
non-vacuous work, and it stayed green with `chamber/` importing `tenancy`,
`signal_io` and the rest — confirming the D-00 direction (Foray ↛ chamber).

### 4. Remaining manual leg

**Live pi-offline Signal alert to f1 on fc-core stop** (63-VALIDATION.md §
Manual-Only Verifications) is **NOT done** — it needs live fc1 plus the Signal
container and cannot gate CI. The automated leg
(`test_bridge_disconnect_fires_pi_alert`) proves the FSM timing and message body
against a fake client; the live send is prod-readiness confirmation only.

---

## ⚠ Pre-existing failures surfaced (NOT caused by Phase 63)

Starting a test DB revealed **3 latent failures** that are normally invisible
because those tests skip when no DB is reachable:

```
tests/confirm/test_confirm_repo.py::test_update_draft_after_edit_status_guard
tests/confirm/test_confirm_repo.py::test_expire_draft_event_names
tests/test_persistence.py::test_migrations_origin_and_commit_columns
  E psycopg.ProgrammingError: the query has 0 placeholders but 1 parameters were passed
```

**Verified pre-existing:** I re-ran them with all Phase 63 work `git stash`ed and
the same three failed identically. They are psycopg parameter-binding bugs in
DB-backed tests, in packages this phase never touched (`confirm/`, `persistence/`).

Not fixed here — out of scope for Phase 63 and it would muddy the diff. **Worth a
backlog item**: these tests are effectively dead in CI (always skipped), so the
bugs could sit indefinitely. Flagging rather than silently leaving them.

---

## Acceptance criteria

| Criterion | Result |
|-----------|--------|
| `grep -c "ReceiveLoop(" boot.py` == 1 | ✅ 1 |
| `grep -c "SignalClient(" boot.py` == 1 | ✅ 1 |
| `grep -c "get_max_sends_per_hour" boot.py` >= 1, wired to chamber_config | ✅ 1 |
| `grep -c "make_composite_dispatch" boot.py` >= 1 | ✅ 2 (import + call) |
| no `dispatch=pipeline["handle"]` remains | ✅ |
| `await chamber_service.stop()` in shutdown | ✅ 1 |
| `grep -Ec "SignalClient\(\|httpx.AsyncClient\(\)\|ReceiveLoop\(" service.py` == 0 | ✅ 0 |
| `grep -c "class ChamberService"` == 1 | ✅ 1 |
| SC1 automated leg passes | ✅ |
| snooze-routes / ordinary-text-falls-through both pass | ✅ |

---

## Deviations

1. **`grep -Ec "pool|INSERT|persist" service.py` reads 1, not 0.** The sole hit is
   the module docstring line stating the D-06 constraint ("nothing here touches
   the pool, and no alert state is persisted"). No such code exists. Same
   naive-grep pattern as Plans 04-06; the comment was kept because it documents
   the invariant.

2. **`_dispatch_*` callbacks wrap `on_event` in `create_task`.** `WsClient` and
   `heartbeat_loop` both take **synchronous** callbacks (`on_message`,
   `on_liveness`, `dispatch`), but `on_event` is a coroutine. The callbacks
   therefore schedule tasks and retain them on `self._tasks` so `stop()` cancels
   them. Not spelled out in the plan; it falls out of the Plan 05/06 signatures.

3. **`EVAL_TICK_INTERVAL_S = 30.0`.** The plan required a periodic `tick` task but
   named no interval. 30s chosen to match the chamber-dark granularity (the
   `FC1_DARK_THRESHOLD_MS` is 3 min, so a 30s tick detects within ~1 tick).

4. **Started a test DB rather than reporting a skip.** The plan permitted reporting
   the skip honestly; running them was strictly better and caught nothing broken in
   the chamber wiring while surfacing the 3 pre-existing failures above.

---

## Plan assertions checked against source

All verified true: `boot.py` was at `farm_agent/boot.py` (not `src/farm-agent/boot.py`);
`SignalClient` was constructed with no rate-cap hook; `ReceiveLoop` took
`dispatch=pipeline["handle"]`; the shutdown block had the
`.cancel()` / `await` / `except CancelledError` shape; `router.classify_envelope`
returns a `dm` entry read via the dual-shape `_read_dm`. Nothing turned out false.
