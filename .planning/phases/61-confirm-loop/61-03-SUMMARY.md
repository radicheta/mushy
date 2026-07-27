---
phase: 61-confirm-loop
plan: "03"
subsystem: confirm-loop
tags: [watchdog, strain-ask-back, dispatch, boot-wiring, asyncio, tdd]
dependency_graph:
  requires: [61-01-confirm_repo, 61-02-state_machine]
  provides: [watchdog-loop, strain-ask-back-resolver, dispatch-route-confirm-reply, boot-confirm-task, SC-4-tests]
  affects: [farm_agent.confirm.watchdog, farm_agent.confirm.strain_ask_back, farm_agent.confirm.dispatch, farm_agent.boot, tests.confirm]
tech_stack:
  added: []
  patterns: [immediate-then-sleep-loop, asyncio-lock-belt-and-suspenders, tdd-red-green, never-throws-per-row, levenshtein-dp-no-external-dep]
key_files:
  created:
    - src/farm-agent/farm_agent/confirm/strain_ask_back.py
    - src/farm-agent/farm_agent/confirm/watchdog.py
    - src/farm-agent/farm_agent/confirm/dispatch.py
    - src/farm-agent/tests/confirm/test_strain_ask_back.py
    - src/farm-agent/tests/confirm/test_watchdog.py
  modified:
    - src/farm-agent/farm_agent/boot.py
decisions:
  - "Levenshtein DP ported verbatim from strain-resolver.js (no external dep); nearest_known is display-only (NEVER auto-remap) -- T-61-09 / Pitfall 7 / POY-as-KOY bug"
  - "strain intercept unknown reply falls through (no confirm, no re-ask) -- RESEARCH correction over CONTEXT"
  - "dispatch.route_confirm_reply takes injected repo= for tests; defaults to real confirm_repo"
  - "tick_once takes injected repo= for tests; lock created once per confirm_watchdog_loop invocation"
  - "Phase 61 commit boundary: NO farmOS HTTP call in confirm/ -- commit-trigger marker emitted as signal_draft_event (event='commit_trigger'); Phase 62 reads it"
  - "Edit reextraction is a Phase 62 stub (log.info only) per RESEARCH A2 / Open Question 2"
  - "bare 'no' token excluded from CODE_RE Path 3 (it's a refusal word without a code suffix -> unknown)"
metrics:
  duration: "~30 minutes"
  completed: "2026-06-28"
  tasks_completed: 3
  tasks_total: 3
  files_created: 5
  files_modified: 1
---

# Phase 61 Plan 03: Watchdog + Strain Ask-Back + Dispatch + Boot Wiring Summary

Async confirm-loop watchdog (nudge/expire), strain-ask-back resolver + reply parser, YES/NO/EDIT + strain-intercept dispatch, boot wiring, and SC-4 curated-set intercept tests. Phase 61 stops at confirmed + commit-trigger marker; no farmOS HTTP call.

## What Was Built

**strain_ask_back.py** -- Port of strain-ask-back.js + strain-resolver.js:

- `CURATED_14`: default list of 14 strain codes (SHI SH2 KOY MAI MALI KOS DT CAS CAZ WIN ALM MOR BP LIMA)
- `levenshtein(a, b)`: DP port verbatim from Node (no external dependency)
- `nearest_known(code, curated_set)`: Levenshtein min-distance, first-wins tie-break; DISPLAY ONLY (T-61-09)
- `resolve_strain(code, curated_set)`: exact-match only; None/non-str/empty -> {known:False, code:None}; unknown -> {known:False, code:norm, nearest:...}
- `CONFIRM_SET` = {'yes','y','ok','si','confirm','new'}; `CODE_RE` = `^[A-Za-z][A-Za-z0-9]{1,3}$`
- `parse_strain_ask_back_reply(text)`: four routing paths (confirm_new/correction/unknown); bare 'no' -> unknown
- `render_strain_ask_back(seen_code, nearest)`: ASCII-only, -- not em-dash, no emoji; 3-line with nearest, 2-line without

**watchdog.py** -- Port of watchdog.js; mirrors retention.py immediate-then-sleep pattern:

- `tick_once(pool, signal_client, config, *, lock, repo)`: acquires Lock; finds nudge candidates (nudge_min = round(timeout * fraction)); for each: mark_nudge_sent SQL guard (rowcount=1 -> send + append nudge_sent event; rowcount=0 -> skip); then expire candidates via expire_draft; per-row try/except (one failure does not abort tick); mask_number() on e164 logs (T-61-13)
- `confirm_watchdog_loop(pool, signal_client, config)`: asyncio.Lock created once; immediate tick (try/except Exception WARNING); while True: sleep(interval); tick; except CancelledError: raise; except Exception: WARNING

**dispatch.py** -- YES/NO/EDIT routing + strain intercept:

- `route_confirm_reply(pool, signal_client, config, draft_row, text, *, repo)`: injected repo for tests
- Strain intercept (needs_review_reason == 'strain_unknown_pending_confirm'): parse_strain_ask_back_reply -> confirm_new (confirm + ack + commit-trigger marker); correction+known (rewrite species_code + confirm + ack + commit-trigger marker); correction+unknown (re-ask); unknown (fall_through sentinel, no send)
- Standard YES/NO/EDIT: FSM transition() -> side effects; commit-trigger only on rowcount==1 (T-61-12); idempotent ack on rowcount==0
- Edit reextraction: Phase 62 stub (log.info only)
- no-silent-failure: every terminal state attempts ack; failures log WARNING (T-61-10)

**boot.py** -- confirm_task wiring:

- Import `confirm_watchdog_loop` from `farm_agent.confirm.watchdog`
- `confirm_task = asyncio.create_task(confirm_watchdog_loop(pool, signal_client, config))` after retention_task
- Shutdown: `confirm_task.cancel()` + await with CancelledError swallow (mirrors retention_task pattern)

**test_strain_ask_back.py** -- 38 tests, all pure-function (no DB):

- TestResolveStrain (9): exact-match, lowercase normalization, whitespace, unknown, None/non-str/empty, empty curated set, all-14 loop
- TestNearestKnown (4): distance, exact match, empty set, tie-break
- TestParseStrainAskBackReply (15): all CONFIRM_SET tokens, 'no, code' variants, bare CODE, garbage, 'no' alone -> unknown
- TestRenderStrainAskBack (6): 3-line / 2-line variants, ASCII-only, no em-dash, uppercasing
- SC-4 async dispatch tests (4): known curated code confirms (no ask-back), unknown code re-asks, nonsense falls through, YES on strain_unknown confirms

**test_watchdog.py** -- 8 tests:

- tick_once nudge: rowcount=1 sends one nudge; rowcount=0 skips
- tick_once expire: rowcount=1 sends expire note; rowcount=0 skips
- tick_once appends nudge_sent event on successful nudge
- confirm_watchdog_loop: CancelledError re-raises (not swallowed)
- confirm_watchdog_loop: Exception logs WARNING + loop continues (never-throws)
- boot_imports_confirm_watchdog_loop: source check proves boot wiring

## Deviations from Plan

**1. [Rule 1 - Bug] bare 'no' token excluded from CODE_RE Path 3**
- **Found during:** Task 1 TDD RED/GREEN
- **Issue:** "no" as a bare token matches CODE_RE (`^[A-Za-z][A-Za-z0-9]{1,3}$`) and would produce `{kind:'correction', code:'NO'}`, but the test spec requires bare "no" to be `{kind:'unknown'}`.
- **Fix:** Added `tokens[0].lower() != "no"` guard in Path 3 of parse_strain_ask_back_reply(). "no" without a code suffix is a refusal word (unknown), not a strain correction.
- **Files modified:** strain_ask_back.py
- **Commit:** 1016816

**2. [Rule 2 - Missing functionality] append_event_via_pool in FakeConfirmRepoForDispatch**
- **Found during:** Task 1 dispatch tests
- **Issue:** dispatch.py calls repo.append_event_via_pool for commit-trigger markers; test's FakeConfirmRepoForDispatch needed this method.
- **Fix:** Added append_event_via_pool to the test fake, returning {ok:True, seq:1}.
- **Files modified:** tests/confirm/test_strain_ask_back.py

## Known Stubs

- `_run_edit_reextraction_stub()` in dispatch.py: logs `[confirm] edit reextraction stub -- Phase 62 (draft_id=...)` and returns. Full Phase-60 extractor wire-up deferred to Phase 62 (RESEARCH A2 / Open Question 2). Does NOT prevent any Phase 61 SC from passing.

## Threat Flags

None -- no new network endpoints or auth paths introduced. confirm/ makes NO farmOS HTTP calls (Phase 61 commit boundary verified by grep -RIL). T-61-09 (no auto-remap), T-61-10 (no-silent-failure), T-61-11 (never-throws loop), T-61-12 (dup commit-trigger guard), T-61-13 (mask_number on e164 logs) all mitigated in implementation.

## Self-Check

| Check | Result |
|-------|--------|
| src/farm-agent/farm_agent/confirm/strain_ask_back.py | FOUND |
| src/farm-agent/farm_agent/confirm/watchdog.py | FOUND |
| src/farm-agent/farm_agent/confirm/dispatch.py | FOUND |
| src/farm-agent/tests/confirm/test_strain_ask_back.py | FOUND |
| src/farm-agent/tests/confirm/test_watchdog.py | FOUND |
| boot.py contains confirm_watchdog_loop | PASSED |
| watchdog.py contains asyncio.CancelledError re-raise | PASSED |
| No farmOS HTTP call in farm_agent/confirm/ | PASSED (grep -RIL confirms 0 matches) |
| 38 strain_ask_back tests pass | PASSED |
| 8 watchdog tests pass | PASSED |
| 71 total confirm/ tests pass (2 DB-gated skipped) | PASSED |

## Self-Check: PASSED
